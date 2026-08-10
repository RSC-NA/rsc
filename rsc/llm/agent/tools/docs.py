"""Static league documents: help pages and the joke files.

These are small, rarely-changing markdown files. Only `rsc.md` and
`important_channels.md` are cheap and general enough to live in the cached
system prefix; the rest are fetched on demand because most questions never
need them.
"""

import logging
from pathlib import Path

from rsc.llm.agent.context import AgentContext
from rsc.llm.agent.format import clamp
from rsc.llm.agent.registry import tool

log = logging.getLogger("red.rsc.llm.agent.docs")

RESOURCES_PATH = Path(__file__).parent.parent.parent.parent / "resources"

# Explicit allowlist rather than a directory glob: the topic name reaches this
# from model output, and a glob plus a path join is a traversal waiting to
# happen.
DOC_TOPICS: dict[str, Path] = {
    "about_rsc": RESOURCES_PATH / "help" / "rsc.md",
    "important_channels": RESOURCES_PATH / "help" / "important_channels.md",
    "combines": RESOURCES_PATH / "help" / "combines_help.md",
    "combines_how_to_play": RESOURCES_PATH / "help" / "combines_how_to_play.md",
    "glossary": RESOURCES_PATH / "help" / "glossary.md",
    "best_chip": RESOURCES_PATH / "funny" / "best_chip.md",
    "feet": RESOURCES_PATH / "funny" / "feet.md",
    "nickm": RESOURCES_PATH / "funny" / "nickm.md",
    "whatami": RESOURCES_PATH / "funny" / "whatami.md",
}


@tool(
    "get_help_doc",
    "Read a static league help document, for example how combines work or which channels matter.",
    properties={
        "topic": {
            "type": "string",
            "enum": sorted(DOC_TOPICS),
            "description": "Which document to read.",
        }
    },
    required=["topic"],
    cacheable=True,
)
async def get_help_doc(ctx: AgentContext, topic: str) -> str:
    path = DOC_TOPICS.get(topic)
    if path is None:
        return f"ERROR: unknown topic {topic!r}. Valid: {', '.join(sorted(DOC_TOPICS))}"
    try:
        return clamp(path.read_text(encoding="utf-8"))
    except OSError as exc:
        log.warning(f"Could not read help doc {topic}: {exc}")
        return f"ERROR: could not read the {topic} document."
