"""Tool registration and schema export for the RSC agent."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

# Handlers take (AgentContext, **tool arguments). Spelling that out as a
# Callable would need the context type imported here, which would be a circular
# import -- context imports the registry for ToolCallRecord.
ToolHandler = Callable[..., Awaitable[str]]


def _is_blank(value: object, declared_type: str | None) -> bool:
    """Whether a model-supplied value is a placeholder rather than a filter."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    # `False` is a real choice for a boolean -- and every boolean parameter's
    # default anyway -- so only numbers treat zero as a blank.
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return value == 0 and declared_type in ("integer", "number")
    return False


@dataclass(frozen=True, slots=True)
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    # Whether repeated calls within a request window may be served from cache.
    # Anything that moves intraday (rosters after a transaction, schedules)
    # must stay uncached -- a stale answer is worse than a slow one.
    cacheable: bool = False

    def schema(self) -> dict[str, Any]:
        """Tool definition in the shape the Responses API expects."""
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def clean_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Drop the placeholders a model fills optional parameters with.

        Models routinely send every declared property rather than only the ones
        they mean, padding the rest with type-shaped blanks -- a name lookup
        arrives as `{"name": "frostybrew", "discord_id": 0, "me": false}`. By
        the time a blank reaches the RSC API it is indistinguishable from a real
        filter: `discord_id=0` goes out as a query parameter and matches nobody,
        so a player who plainly exists comes back "No player found".

        Only optional parameters are pruned, because each has a working default
        to fall back on. A blank in a *required* parameter is left in place so
        the handler's own validation can tell the model what it did wrong, and
        an undeclared parameter is left in place so the resulting `TypeError`
        does the same.
        """
        properties: dict[str, Any] = self.parameters.get("properties") or {}
        required: list[str] = self.parameters.get("required") or []
        return {
            key: value
            for key, value in arguments.items()
            if key in required or key not in properties or not _is_blank(value, (properties[key] or {}).get("type"))
        }


TOOLS: dict[str, AgentTool] = {}


def tool(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
    *,
    cacheable: bool = False,
) -> Callable[[ToolHandler], ToolHandler]:
    """Register a coroutine as an agent tool.

    Schemas live in the cached system prefix, so descriptions are written to be
    short and to steer the model away from expensive access patterns (for
    example, pointing it at `top_players` rather than paging every roster).
    """

    def decorator(func: ToolHandler) -> ToolHandler:
        if name in TOOLS:
            raise ValueError(f"Duplicate agent tool name: {name}")
        TOOLS[name] = AgentTool(
            name=name,
            description=description,
            parameters={
                "type": "object",
                "properties": properties or {},
                "required": required or [],
                "additionalProperties": False,
            },
            handler=func,
            cacheable=cacheable,
        )
        return func

    return decorator


def tool_schemas() -> list[dict[str, Any]]:
    return [entry.schema() for entry in TOOLS.values()]


@dataclass(slots=True)
class ToolCallRecord:
    """What the agent consulted, for the sources footer and the usage log."""

    names: list[str] = field(default_factory=list)

    def record(self, name: str) -> None:
        if name not in self.names:
            self.names.append(name)

    def __bool__(self) -> bool:
        return bool(self.names)
