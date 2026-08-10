"""Tool registration and schema export for the RSC agent."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

# Handlers take (AgentContext, **tool arguments). Spelling that out as a
# Callable would need the context type imported here, which would be a circular
# import -- context imports the registry for ToolCallRecord.
ToolHandler = Callable[..., Awaitable[str]]


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
