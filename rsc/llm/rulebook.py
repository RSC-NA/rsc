"""In-memory index over the RSC rule documents.

Replaces vector search for rules. The rulebooks are small enough (~1,200 rules
across three files) that a lexical index built at startup answers precisely and
for free, with none of the recall gaps that made top-k similarity search
unreliable for rule lookups.

Two things this module is careful about:

* It renders *raw* rule text. `RuleDocumentLoader` builds `page_content` with
  ancestry scaffolding that inflates the corpus roughly fourfold -- ideal for
  embedding, ruinous for putting rules in a prompt.
* It scopes to sections. A whole book is ~6k-19k tokens, but the enclosing
  section of any given rule is usually a few hundred, so section-scoped answers
  cost an order of magnitude less than book-scoped ones.
"""

import asyncio
import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from rsc.llm.loaders.ruleloader import RuleDocumentLoader, RuleNode

log = logging.getLogger("red.rsc.llm.rulebook")

RULES_PATH = Path(__file__).parent.parent / "resources" / "rules"

# BM25 tuning. Standard defaults; the corpus is small and homogeneous enough
# that these have never needed tuning.
BM25_K1 = 1.5
BM25_B = 0.75

PHRASE_BONUS = 2.0
TITLE_BONUS = 0.5
# Section headings match many queries but rarely *answer* them -- the operative
# text lives in their children. Nudge them below leaf rules of equal relevance.
PARENT_PENALTY = 0.75

RULE_NUMBER_QUERY_RE = re.compile(r"\b(\d+(?:\.\d+)+)\b")
TOKEN_RE = re.compile(r"[a-z0-9']+")

# "up"/"out"/"in" are deliberately absent: they carry real meaning in rule text
# ("sub up to a higher tier", "substituted out").
_STOPWORD_TEXT = (
    "a an and any are as at be been but by can do does for from get got had has have how i if "
    "is it its me my no not of on or our so than that the their them then there these they this to "
    "was we were what when where which who whom why will with would you your rsc rule rules"
)
STOPWORDS: frozenset[str] = frozenset(_STOPWORD_TEXT.split())


class RuleBook(StrEnum):
    """The rule documents the bot answers from.

    `Old RSC Rules.md` sits in the same directory and is deliberately absent:
    superseded rules mixed with current ones are worse than no rules at all.
    """

    COMPETITIVE = "competitive"
    BEHAVIORAL = "behavioral"
    ELEVATED = "elevated"


RULEBOOK_FILES: dict[RuleBook, str] = {
    RuleBook.COMPETITIVE: "RSC Rules.md",
    RuleBook.BEHAVIORAL: "Behavioral Rules.md",
    RuleBook.ELEVATED: "Elevated Rules.md",
}

# How a book is named in a citation. Rule numbers collide across books -- `3.1`
# exists in all three -- so a bare number is ambiguous and every citation must
# carry one of these.
RULEBOOK_LABELS: dict[RuleBook, str] = {
    RuleBook.COMPETITIVE: "RSC Rules",
    RuleBook.BEHAVIORAL: "Behavioral",
    RuleBook.ELEVATED: "Elevated",
}

RULEBOOK_DESCRIPTIONS: dict[RuleBook, str] = {
    RuleBook.COMPETITIVE: "Competitive play: league format, game rules, franchises, transactions, eligibility.",
    RuleBook.BEHAVIORAL: "Conduct and moderation: behavior, harassment, penalties, appeals, enforcement.",
    RuleBook.ELEVATED: "Staff and elevated roles: committees, responsibilities, org structure.",
}

# `Behavioral Rules.md` heads its first section "Breakdowns, Explanations, And
# Philosophies 1 Introduction", which does not start with a digit and so never
# matches RULE_LINE_RE. Its children (1.1-1.3) parse fine. Patching the title in
# here beats loosening the regex across 74KB of prose, which would invent rules
# out of ordinary numbered sentences.
SYNTHETIC_HEADINGS: dict[RuleBook, dict[str, str]] = {
    RuleBook.BEHAVIORAL: {"1": "Introduction"},
}


@dataclass(frozen=True, slots=True)
class RuleEntry:
    book: RuleBook
    number: str
    title: str
    text: str
    parent: str
    ancestors: tuple[str, ...]
    depth: int
    path: str
    section: str
    is_heading: bool
    has_children: bool
    order: int

    @property
    def citation(self) -> str:
        return f"{RULEBOOK_LABELS[self.book]} {self.number}"


@dataclass(frozen=True, slots=True)
class RuleHit:
    entry: RuleEntry
    score: float

    def excerpt(self, limit: int = 300) -> str:
        text = " ".join(self.entry.text.split())
        return text if len(text) <= limit else text[:limit].rstrip() + "..."


@dataclass(slots=True)
class RuleBookIndex:
    book: RuleBook
    entries: dict[str, RuleEntry]
    order: tuple[str, ...]
    toc: str
    glossary: dict[str, str]

    def get(self, number: str) -> RuleEntry | None:
        return self.entries.get(number.strip().rstrip("."))


@dataclass(slots=True)
class SearchIndex:
    """One BM25 space spanning every book.

    Deliberately global rather than per-book. With per-book statistics a term is
    rarest -- and so scores highest -- in the book it is *least* about: "committee"
    appears in 62 of 238 Elevated rules but almost nowhere else, so per-book idf
    ranked Elevated last on committee questions. A shared space makes scores
    comparable and lets the term's rarity across the whole corpus speak.
    """

    entries: dict[str, RuleEntry]
    postings: dict[str, tuple[tuple[str, int], ...]]
    idf: dict[str, float]
    lengths: dict[str, int]
    avg_length: float


def _key(book: RuleBook, number: str) -> str:
    return f"{book.value}:{number}"


_INDEXES: dict[RuleBook, RuleBookIndex] = {}
_SEARCH: SearchIndex | None = None
_LOAD_LOCK = asyncio.Lock()


def _tokenize(text: str) -> list[str]:
    return [tok for tok in TOKEN_RE.findall(text.lower()) if tok not in STOPWORDS and len(tok) > 1]


def _section_of(number: str, numbers: set[str]) -> str:
    """The depth-2 ancestor that encloses a rule, falling back upward."""
    parts = number.split(".")
    if len(parts) >= 2:
        candidate = ".".join(parts[:2])
        if candidate in numbers:
            return candidate
    return parts[0]


def _apply_synthetic_headings(nodes: list[RuleNode], synthetic: dict[str, str]) -> list[RuleNode]:
    """Insert or retitle section headings the parser cannot recover.

    A synthetic number may be missing entirely (its heading line does not start
    with a digit, so nothing matched) rather than merely untitled, in which case
    the node is created and ordered just ahead of its first child so the table
    of contents reads in document order.
    """
    if not synthetic:
        return nodes

    existing = {node.number: node for node in nodes}
    patched = list(nodes)
    for number, title in synthetic.items():
        node = existing.get(number)
        if node is not None:
            if not node.title:
                node.title = title
            if not node.heading_level:
                node.heading_level = 1
            continue
        child_prefix = f"{number}."
        child_orders = [n.order for n in nodes if n.number.startswith(child_prefix)]
        order = min(child_orders) - 1 if child_orders else -1
        patched.append(RuleNode(number=number, title=title, lines=[f"{number}. {title}"], order=order, heading_level=1))

    return sorted(patched, key=lambda node: node.order)


def _build_index(book: RuleBook, nodes: list[RuleNode], glossary: dict[str, str]) -> RuleBookIndex:
    synthetic = SYNTHETIC_HEADINGS.get(book, {})
    nodes = _apply_synthetic_headings(nodes, synthetic)
    numbers = {node.number for node in nodes}
    by_number = {node.number: node for node in nodes}

    entries: dict[str, RuleEntry] = {}
    parents_with_children: set[str] = set()
    for node in nodes:
        if "." in node.number:
            parents_with_children.add(node.number.rsplit(".", maxsplit=1)[0])

    for node in nodes:
        parts = node.number.split(".")
        ancestors = tuple(".".join(parts[:idx]) for idx in range(1, len(parts)))
        title = node.title or synthetic.get(node.number, "")
        path_parts = []
        for ancestor in (*ancestors, node.number):
            anc_node = by_number.get(ancestor)
            anc_title = (anc_node.title if anc_node else "") or synthetic.get(ancestor, "")
            path_parts.append(f"{ancestor} {anc_title}".strip())
        entries[node.number] = RuleEntry(
            book=book,
            number=node.number,
            title=title,
            text="\n".join(node.lines),
            parent=ancestors[-1] if ancestors else "",
            ancestors=ancestors,
            depth=len(parts),
            path=" > ".join(path_parts),
            section=_section_of(node.number, numbers),
            is_heading=bool(node.heading_level) or node.number in synthetic,
            has_children=node.number in parents_with_children,
            order=node.order,
        )

    return RuleBookIndex(
        book=book,
        entries=entries,
        order=tuple(entry.number for entry in sorted(entries.values(), key=lambda e: e.order)),
        toc=_render_toc(book, entries),
        glossary=glossary,
    )


def _build_search_index(indexes: dict[RuleBook, RuleBookIndex]) -> SearchIndex:
    """Build the shared BM25 space over every rule in every book."""
    # Postings cover title + text, so a term in a heading is findable without
    # duplicating parent text into every child.
    postings: dict[str, list[tuple[str, int]]] = defaultdict(list)
    lengths: dict[str, int] = {}
    entries: dict[str, RuleEntry] = {}

    for index in indexes.values():
        for entry in index.entries.values():
            key = _key(entry.book, entry.number)
            entries[key] = entry
            counts: dict[str, int] = defaultdict(int)
            for token in _tokenize(f"{entry.title}\n{entry.text}"):
                counts[token] += 1
            lengths[key] = sum(counts.values()) or 1
            for token, freq in counts.items():
                postings[token].append((key, freq))

    total = len(entries) or 1
    idf = {token: math.log(1 + (total - len(plist) + 0.5) / (len(plist) + 0.5)) for token, plist in postings.items()}

    return SearchIndex(
        entries=entries,
        postings={token: tuple(plist) for token, plist in postings.items()},
        idf=idf,
        lengths=lengths,
        avg_length=sum(lengths.values()) / total,
    )


def _render_toc(book: RuleBook, entries: dict[str, RuleEntry]) -> str:
    """A table of contents from markdown headings only.

    Deliberately not depth-based: `Elevated Rules.md` numbers ordinary prose
    sentences two levels deep, so a depth<=2 filter would dump paragraphs of
    rule text into what should be a compact map of the book.
    """
    lines = [
        f"{entry.number} {entry.title}".strip()
        for entry in sorted(entries.values(), key=lambda e: e.order)
        if entry.is_heading and entry.title
    ]
    return "\n".join([f"## {RULEBOOK_LABELS[book]} ({book.value})", *lines])


def _load_book(book: RuleBook) -> RuleBookIndex:
    path = RULES_PATH / RULEBOOK_FILES[book]
    loader = RuleDocumentLoader(str(path))
    data = path.read_text(encoding="utf-8")
    nodes = loader.parse_rule_nodes(data)
    glossary = {
        str(doc.metadata["term"]): doc.page_content.split("Definition:", maxsplit=1)[-1].strip() for doc in loader.lazy_load_glossary()
    }
    log.debug(f"Indexed {book.value}: {len(nodes)} rules, {len(glossary)} glossary terms.")
    return _build_index(book, nodes, glossary)


async def load_rulebooks(*, force: bool = False) -> dict[RuleBook, RuleBookIndex]:
    """Build (once) and return the index for every rulebook."""
    global _INDEXES, _SEARCH
    if _INDEXES and not force:
        return _INDEXES
    async with _LOAD_LOCK:
        if _INDEXES and not force:
            return _INDEXES

        def build() -> tuple[dict[RuleBook, RuleBookIndex], SearchIndex]:
            indexes = {book: _load_book(book) for book in RuleBook}
            return indexes, _build_search_index(indexes)

        # Pure regex over ~164KB. Threaded so a cold first question does not
        # stall the event loop behind it.
        _INDEXES, _SEARCH = await asyncio.to_thread(build)
    return _INDEXES


def loaded_rulebooks() -> dict[RuleBook, RuleBookIndex]:
    """The already-built indexes. Raises if `load_rulebooks` has not run."""
    if not _INDEXES:
        raise RuntimeError("Rulebooks have not been loaded. Call load_rulebooks() first.")
    return _INDEXES


def _loaded_search() -> SearchIndex:
    if _SEARCH is None:
        raise RuntimeError("Rulebooks have not been loaded. Call load_rulebooks() first.")
    return _SEARCH


def rulebook_toc() -> str:
    """Compact map of all three books, for the cached system prompt."""
    return "\n\n".join(index.toc for index in loaded_rulebooks().values())


def glossary_text() -> str:
    """League vocabulary, for the cached system prompt."""
    glossary = loaded_rulebooks()[RuleBook.COMPETITIVE].glossary
    return "\n".join(f"{term}: {definition}" for term, definition in glossary.items())


def search_rules(query: str, book: RuleBook | None = None, limit: int = 8) -> list[RuleHit]:
    """Lexical BM25 search across one or all rulebooks.

    A query naming an explicit rule number short-circuits to that rule, since
    "what does 5.7.3 say" is a lookup, not a search.
    """
    indexes = loaded_rulebooks()
    search = _loaded_search()
    books = [book] if book else list(RuleBook)

    number_match = RULE_NUMBER_QUERY_RE.search(query)
    if number_match:
        wanted = number_match.group(1)
        hits = [RuleHit(entry=indexes[b].entries[wanted], score=100.0) for b in books if wanted in indexes[b].entries]
        if hits:
            return hits[:limit]

    tokens = _tokenize(query)
    if not tokens:
        return []
    phrase = " ".join(query.lower().split())
    wanted_books = set(books)

    scores: dict[str, float] = defaultdict(float)
    for token in set(tokens):
        postings = search.postings.get(token)
        if not postings:
            continue
        idf = search.idf[token]
        for key, freq in postings:
            if search.entries[key].book not in wanted_books:
                continue
            norm = 1 - BM25_B + BM25_B * (search.lengths[key] / search.avg_length)
            scores[key] += idf * (freq * (BM25_K1 + 1)) / (freq + BM25_K1 * norm)

    hits: list[RuleHit] = []
    for key, score in scores.items():
        entry = search.entries[key]
        if phrase and phrase in entry.text.lower():
            score += PHRASE_BONUS
        if entry.title and any(token in entry.title.lower() for token in tokens):
            score += TITLE_BONUS
        if entry.has_children:
            score -= PARENT_PENALTY
        hits.append(RuleHit(entry=entry, score=score))

    hits.sort(key=lambda hit: (-hit.score, hit.entry.book.value, hit.entry.order))
    return hits[:limit]


def render_rule(book: RuleBook, number: str, *, include_children: bool = True, include_parents: bool = False) -> str | None:
    """Raw text of one rule, optionally with its subtree and ancestry."""
    index = loaded_rulebooks()[book]
    entry = index.get(number)
    if entry is None:
        return None

    parts: list[str] = []
    if include_parents:
        parts.extend(index.entries[ancestor].text for ancestor in entry.ancestors if ancestor in index.entries)
    parts.append(entry.text)
    if include_children:
        prefix = f"{entry.number}."
        parts.extend(index.entries[num].text for num in index.order if num.startswith(prefix))
    return "\n".join(parts)


def render_section(book: RuleBook, number: str) -> str | None:
    """Raw text of the whole section enclosing a rule."""
    index = loaded_rulebooks()[book]
    entry = index.get(number)
    if entry is None:
        return None
    return render_rule(book, entry.section, include_children=True)


def render_book(book: RuleBook) -> str:
    """Raw text of an entire rulebook.

    Joins `RuleEntry.text`, never `page_content` -- see the module docstring.
    """
    index = loaded_rulebooks()[book]
    return "\n".join(index.entries[number].text for number in index.order)


def select_book(query: str) -> RuleBook:
    """Pick the most likely book for a query, using lexical score alone.

    Cheaper and more predictable than a classifier model call, and it fails
    softly: a wrong pick still returns real rule text the caller can reject.
    """
    totals: dict[RuleBook, float] = defaultdict(float)
    for hit in search_rules(query, limit=15):
        totals[hit.entry.book] += max(hit.score, 0.0)
    if not totals:
        return RuleBook.COMPETITIVE
    return max(totals, key=lambda book: totals[book])
