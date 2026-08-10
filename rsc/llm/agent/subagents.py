"""The rules sub-agent.

The only sub-agent in the system, and it exists for one measured reason: the
main loop re-sends its whole context on every iteration, so rule text returned
as a tool result is paid for again on each subsequent turn. A worst case
full-book load is ~18.5k tokens; returned into a main loop that then iterates
three more times that becomes ~74k. Inside a sub-agent that terminates, it is
sent once.

Its usage is recorded into the caller's accumulator, so the token ceiling and
the spend log account for it rather than treating it as free.
"""

import logging
from typing import Any

from openai import APIError

from rsc.llm.agent.context import AgentContext
from rsc.llm.config import (
    OPENAI_REQUEST_TIMEOUT,
    OPENAI_SUBAGENT_MODEL,
    RULES_SUBAGENT_MAX_CONTEXT_CHARS,
    RULES_SUBAGENT_MAX_SECTIONS,
    SUBAGENT_MAX_OUTPUT_TOKENS,
)
from rsc.llm.rulebook import (
    RULEBOOK_LABELS,
    RuleBook,
    render_book,
    render_rule,
    search_rules,
    select_book,
)
from rsc.logs import GuildLogAdapter

logger = logging.getLogger("red.rsc.llm.agent.rules")
log = GuildLogAdapter(logger)

SUBAGENT_SYSTEM = """\
You are the RSC rules authority. Answer only from the rule text provided below.

- Cite every claim as "{book} <number>", for example "{book} 3.1.1".
- Quote or closely paraphrase the rule; do not generalise beyond it.
- If the provided text does not cover the question, say so plainly and name the closest \
relevant rule. Do not speculate.
- Be brief: a short paragraph or a few bullets.\
"""


def _gather_sections(question: str, book: RuleBook) -> tuple[str, list[str]]:
    """Rule text scoped to the sections that matter, with the cited numbers.

    Scoping to sections rather than loading the book is where the saving is:
    a section is typically a few hundred tokens against 6k-19k for a whole
    book.
    """
    hits = search_rules(question, book=book, limit=RULES_SUBAGENT_MAX_SECTIONS * 2)
    if not hits:
        # Nothing matched lexically. Fall back to the whole book rather than
        # answering from nothing -- this is the expensive path and should be
        # rare.
        log.debug(f"No lexical hits for {question!r}; loading all of {book.value}.")
        return render_book(book)[:RULES_SUBAGENT_MAX_CONTEXT_CHARS], []

    sections: list[str] = []
    for hit in hits:
        if hit.entry.section not in sections:
            sections.append(hit.entry.section)
        if len(sections) >= RULES_SUBAGENT_MAX_SECTIONS:
            break

    chunks: list[str] = []
    for section in sections:
        rendered = render_rule(book, section, include_children=True)
        if rendered:
            chunks.append(rendered)

    citations = [hit.entry.citation for hit in hits[:RULES_SUBAGENT_MAX_SECTIONS]]
    return "\n\n".join(chunks)[:RULES_SUBAGENT_MAX_CONTEXT_CHARS], citations


async def run_rules_subagent(ctx: AgentContext, question: str, book: RuleBook | None = None) -> str:
    """Answer a rules question from scoped rule text."""
    # Book selection is lexical, not a model call. That saves a round trip and
    # avoids the classifier-misfire mode that made the old keyword router
    # unreliable; a wrong pick still returns real rule text.
    chosen = book or select_book(question)
    context, citations = _gather_sections(question, chosen)
    if not context.strip():
        return f"ERROR: no rule text found in the {chosen.value} rulebook."

    for citation in citations:
        ctx.cite(citation)

    label = RULEBOOK_LABELS[chosen]
    instructions = SUBAGENT_SYSTEM.format(book=label)

    try:
        response: Any = await ctx.client.responses.create(
            model=OPENAI_SUBAGENT_MODEL,
            instructions=instructions,
            input=[{"role": "user", "content": f"Rulebook: {label}\n\n{context}\n\nQuestion: {question}"}],
            max_output_tokens=SUBAGENT_MAX_OUTPUT_TOKENS,
            store=False,
            timeout=OPENAI_REQUEST_TIMEOUT,
        )
    except APIError as exc:
        log.warning(f"Rules sub-agent failed: {exc}", guild=ctx.guild)
        return f"ERROR: could not consult the {label} rulebook."

    ctx.usage.record(getattr(response, "usage", None))
    answer = (getattr(response, "output_text", "") or "").strip()
    if not answer:
        return f"ERROR: the {label} rulebook returned no answer."
    return answer
