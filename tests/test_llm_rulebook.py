"""Tests for the in-memory rulebook index.

These run against the real checked-in rule documents, like
`test_rule_document_loader.py`, because the parser is tightly coupled to the
markdown export shape and a silent regression there would be invisible against
synthetic fixtures. Bounds are deliberately loose so an ordinary rulebook
revision does not turn the suite red.
"""

import pytest

from rsc.llm.rulebook import (
    RULEBOOK_FILES,
    RULES_PATH,
    RuleBook,
    glossary_text,
    load_rulebooks,
    render_book,
    render_rule,
    render_section,
    rulebook_toc,
    search_rules,
    select_book,
)

# Lower bounds only. Actual counts at time of writing: 427 / 539 / 238.
MIN_RULES = {
    RuleBook.COMPETITIVE: 400,
    RuleBook.BEHAVIORAL: 500,
    RuleBook.ELEVATED: 200,
}


@pytest.fixture(autouse=True)
async def _rulebooks():
    await load_rulebooks()


async def test_all_three_rulebooks_parse() -> None:
    indexes = await load_rulebooks()

    assert set(indexes) == set(RuleBook)
    for book, minimum in MIN_RULES.items():
        assert len(indexes[book].entries) >= minimum, f"{book.value} parsed too few rules"


async def test_old_rulebook_is_not_indexed() -> None:
    """Superseded rules must never reach an answer."""
    assert "Old RSC Rules.md" not in RULEBOOK_FILES.values()
    assert (RULES_PATH / "Old RSC Rules.md").exists(), "fixture assumption: the old rulebook is still on disk"


async def test_behavioral_and_elevated_books_are_indexed() -> None:
    """Both were on disk but never ingested by the previous RAG pipeline."""
    indexes = await load_rulebooks()

    assert indexes[RuleBook.BEHAVIORAL].entries
    assert indexes[RuleBook.ELEVATED].entries


async def test_get_rule_includes_subtree() -> None:
    text = render_rule(RuleBook.COMPETITIVE, "5.7", include_children=True)

    assert text is not None
    assert "5.7.1" in text
    assert "5.7.3" in text


async def test_get_rule_without_children_is_just_the_rule() -> None:
    text = render_rule(RuleBook.COMPETITIVE, "5.7", include_children=False)

    assert text is not None
    assert "5.7.1" not in text


async def test_unknown_rule_number_returns_none() -> None:
    assert render_rule(RuleBook.COMPETITIVE, "99.99.99") is None
    assert render_section(RuleBook.COMPETITIVE, "99.99.99") is None


async def test_elevated_toc_lists_sections_not_prose() -> None:
    """A depth-based TOC would dump rule text here.

    `Elevated Rules.md` numbers ordinary prose sentences two levels deep, so
    rule 1.1 is a 283-character paragraph rather than a section title. Only
    markdown headings belong in the table of contents.
    """
    indexes = await load_rulebooks()
    toc = indexes[RuleBook.ELEVATED].toc
    rule_1_1 = indexes[RuleBook.ELEVATED].entries["1.1"].text

    assert "3.1 Active Committees" in toc
    assert rule_1_1[:80] not in toc


async def test_behavioral_synthetic_heading_is_present() -> None:
    """Behavioral's section 1 heading does not start with a digit, so the
    parser never produces it and it has to be synthesized."""
    indexes = await load_rulebooks()
    entry = indexes[RuleBook.BEHAVIORAL].get("1")

    assert entry is not None
    assert entry.title == "Introduction"
    assert indexes[RuleBook.BEHAVIORAL].toc.splitlines()[1] == "1 Introduction"


async def test_render_book_stays_compact() -> None:
    """Guards against re-introducing `page_content` scaffolding.

    `RuleDocumentLoader.page_content` prepends ancestry to every node, which
    inflates a book roughly fourfold. Rendering must join raw rule text.
    """
    for book, filename in RULEBOOK_FILES.items():
        raw = len((RULES_PATH / filename).read_text(encoding="utf-8"))
        rendered = len(render_book(book))
        assert rendered < raw * 1.2, f"{book.value} rendering is inflated -- is it using page_content?"
        assert rendered > raw * 0.7, f"{book.value} rendering lost content"


async def test_section_render_is_far_cheaper_than_whole_book() -> None:
    """The premise of routing to a section rather than loading a book."""
    section = render_section(RuleBook.COMPETITIVE, "5.7.3")

    assert section is not None
    assert len(section) < len(render_book(RuleBook.COMPETITIVE)) / 5


async def test_substitution_question_finds_the_governing_rule() -> None:
    """The question the old pipeline needed five hardcoded query rewrites for."""
    hits = search_rules("can a permFA sub for the same franchise twice in a row", book=RuleBook.COMPETITIVE, limit=3)

    numbers = [hit.entry.number for hit in hits]
    assert any(number.startswith("5.6.3") for number in numbers), numbers


async def test_explicit_rule_number_short_circuits() -> None:
    hits = search_rules("what does rule 5.7.3 say", book=RuleBook.COMPETITIVE)

    assert [hit.entry.number for hit in hits] == ["5.7.3"]


async def test_search_returns_nothing_for_stopword_only_query() -> None:
    assert search_rules("what is the") == []


async def test_citations_are_book_qualified() -> None:
    """Rule numbers collide across books, so a bare number is ambiguous."""
    indexes = await load_rulebooks()
    shared = [book for book in RuleBook if "3.1" in indexes[book].entries]

    assert len(shared) > 1, "fixture assumption: 3.1 exists in more than one book"
    citations = {indexes[book].entries["3.1"].citation for book in shared}
    assert len(citations) == len(shared)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("what are the responsibilities of a committee member", RuleBook.ELEVATED),
        ("what happens if I am toxic in chat", RuleBook.BEHAVIORAL),
        ("can a permFA sub for the same franchise twice in a row", RuleBook.COMPETITIVE),
    ],
)
async def test_select_book_routes_to_the_right_document(question: str, expected: RuleBook) -> None:
    """Regression guard for per-book scoring.

    With per-book BM25 statistics a term scored highest in the book it was
    least about -- "committee" is common in Elevated and so had the lowest idf
    there, ranking Elevated last on committee questions. Scoring must share one
    corpus-wide space.
    """
    assert select_book(question) is expected


async def test_prompt_prefix_content_stays_small() -> None:
    """TOC and glossary sit in the cached system prompt on every query."""
    assert len(rulebook_toc()) < 4_000
    assert len(glossary_text()) < 8_000
