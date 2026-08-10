"""Compact renderers for tool output.

Tool results are re-sent on every subsequent iteration of the agent loop, so
their size is multiplied by the iterations that follow. Everything here favours
terse pipe-delimited rows over JSON or prose, and every list reports its true
total so the model can say "30 franchises" even when it only sees 25 rows.
"""

from datetime import datetime

from rsc.enums import Status
from rsc.llm.config import TOOL_RESULT_MAX_CHARS


def clamp(text: str, limit: int = TOOL_RESULT_MAX_CHARS) -> str:
    """Truncate on a line boundary, telling the model what it lost.

    The trailing note matters: without it a truncated list reads as a complete
    one, which is the exact failure the old top-k retrieval produced.
    """
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = head.rfind("\n")
    if cut > 0:
        head = head[:cut]
    shown = len(head.splitlines())
    total = len(text.splitlines())
    return f"{head}\n... truncated ({shown} of {total} lines). Narrow your filters."


def table(header: str, rows: list[str], total: int | None = None) -> str:
    """A header line, an explicit total, then one row per record."""
    if not rows:
        return "No results."
    count = total if total is not None else len(rows)
    lines = [header, f"total={count}"]
    if total is not None and total > len(rows):
        lines.append(f"showing={len(rows)}")
    lines.extend(rows)
    return clamp("\n".join(lines))


def fields(pairs: dict[str, object]) -> str:
    """Key/value block for single-entity lookups, skipping empty values."""
    return "\n".join(f"{key}: {value}" for key, value in pairs.items() if value not in (None, "", []))


def humanize_status(status: object) -> str:
    """Turn a status code into the league's own wording for it."""
    if status is None:
        return "Unknown"
    raw = str(getattr(status, "value", status))
    try:
        return Status(raw).full_name
    except ValueError:
        return raw


def parse_status(value: str) -> Status:
    """Coerce a model-supplied status code, raising a message it can act on."""
    try:
        return Status(value.strip().upper())
    except ValueError:
        valid = ", ".join(member.value for member in Status)
        raise ValueError(f"unknown status {value!r}. Valid codes: {valid}") from None


def format_date(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return str(value)


def name_of(entity: object) -> str:
    """Best-effort display name for the nested API models.

    The generated client nests differently per endpoint -- a team may be a bare
    string on one model and an object with `.name` on another -- so tools would
    otherwise each need their own defensive unwrapping.
    """
    if entity is None:
        return ""
    if isinstance(entity, str):
        return entity
    for attr in ("name", "rsc_name", "team", "franchise"):
        value = getattr(entity, attr, None)
        if isinstance(value, str) and value:
            return value
        if value is not None and not isinstance(value, str):
            nested = getattr(value, "name", None)
            if isinstance(nested, str) and nested:
                return nested
    return str(entity)
