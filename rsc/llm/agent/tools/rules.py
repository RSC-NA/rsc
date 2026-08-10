"""Rulebook tools.

Three tools at deliberately different price points, so the model can pay only
for what a question needs:

* `get_rule` -- a known number. Hundreds of tokens.
* `search_rules` -- excerpts to locate a rule. Hundreds of tokens.
* `ask_rulebook` -- a full answer via the sub-agent. Thousands, but isolated
  from the main loop's context.
"""

from rsc.llm.agent.context import AgentContext
from rsc.llm.agent.registry import tool
from rsc.llm.agent.subagents import run_rules_subagent
from rsc.llm.rulebook import RULEBOOK_LABELS, RuleBook, render_rule, search_rules

BOOK_PARAM = {
    "type": "string",
    "enum": [book.value for book in RuleBook],
    "description": "Which rulebook: competitive (play, transactions), behavioral (conduct), elevated (staff).",
}


def _parse_book(value: str | None) -> RuleBook | None:
    if not value:
        return None
    try:
        return RuleBook(value.strip().lower())
    except ValueError:
        raise ValueError(f"unknown rulebook {value!r}. Valid: {', '.join(b.value for b in RuleBook)}") from None


@tool(
    "ask_rulebook",
    "Answer a rules question from the RSC rulebooks, with citations. Use this for any question "
    "about what the rules say, permit or forbid. Omit book to let it choose.",
    properties={
        "question": {"type": "string", "description": "The rules question, in full."},
        "book": BOOK_PARAM,
    },
    required=["question"],
)
async def ask_rulebook(ctx: AgentContext, question: str, book: str | None = None) -> str:
    return await run_rules_subagent(ctx, question, _parse_book(book))


@tool(
    "get_rule",
    "The exact text of a rule by number, including its sub-rules. Use when you already know the "
    "number, for example from the table of contents or a search result.",
    properties={
        "number": {"type": "string", "description": "Rule number, e.g. 5.7.3."},
        "book": BOOK_PARAM,
        "include_children": {"type": "boolean", "description": "Include sub-rules (default true)."},
    },
    required=["number"],
)
async def get_rule(ctx: AgentContext, number: str, book: str | None = None, include_children: bool = True) -> str:
    parsed = _parse_book(book)
    # Rule numbers repeat across books, so without an explicit book every book
    # that has the number is a candidate and the model must be shown which is
    # which.
    books = [parsed] if parsed else list(RuleBook)

    blocks = []
    for candidate in books:
        text = render_rule(candidate, number, include_children=include_children)
        if text:
            ctx.cite(f"{RULEBOOK_LABELS[candidate]} {number}")
            blocks.append(f"=== {RULEBOOK_LABELS[candidate]} {number} ===\n{text}")

    if not blocks:
        where = RULEBOOK_LABELS[parsed] if parsed else "any rulebook"
        return f"No rule {number} found in {where}."
    return "\n\n".join(blocks)


@tool(
    "search_rules",
    "Find rules matching a phrase, returning short excerpts with their numbers. Follow up with "
    "get_rule for full text, or use ask_rulebook if you want a written answer instead.",
    properties={
        "query": {"type": "string", "description": "Words or phrase to search for."},
        "book": BOOK_PARAM,
        "limit": {"type": "integer", "description": "Max results (default 5, max 8)."},
    },
    required=["query"],
)
async def search_rules_tool(ctx: AgentContext, query: str, book: str | None = None, limit: int = 5) -> str:
    limit = max(1, min(int(limit), 8))
    hits = search_rules(query, book=_parse_book(book), limit=limit)
    if not hits:
        return f"No rules matched {query!r}."

    blocks = []
    for hit in hits:
        ctx.cite(hit.entry.citation)
        title = f" - {hit.entry.title}" if hit.entry.title else ""
        blocks.append(f"[{hit.entry.citation}{title}]\n{hit.excerpt()}")
    return "\n\n".join(blocks)
