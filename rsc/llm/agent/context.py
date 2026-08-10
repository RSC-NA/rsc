"""Per-question state shared by the agent loop, its tools, and its sub-agents."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import discord
from openai import AsyncOpenAI

from rsc.llm.agent.budget import UsageAccumulator
from rsc.llm.agent.cache import ToolCache
from rsc.llm.agent.registry import ToolCallRecord

if TYPE_CHECKING:
    from rsc.abc import RSCMixIn


@dataclass(slots=True)
class UserIdentity:
    """Who is asking, resolved from the RSC API where possible."""

    name: str
    discord_id: int | None = None
    team: str | None = None
    franchise: str | None = None
    tier: str | None = None
    status: str | None = None

    def describe(self) -> str:
        if self.team and self.franchise:
            where = f"plays for {self.team} ({self.franchise})"
            if self.tier:
                where = f"{where} in the {self.tier} tier"
            return f"{self.name} {where}."
        if self.status and self.tier:
            return f"{self.name} is a {self.status} in the {self.tier} tier."
        if self.status:
            return f"{self.name} is a {self.status}."
        return f"{self.name} is not currently a rostered player."


@dataclass(slots=True)
class AgentContext:
    cog: "RSCMixIn"
    guild: discord.Guild
    client: AsyncOpenAI
    now: datetime
    identity: UserIdentity | None = None
    surface: str = "mention"
    usage: UsageAccumulator = field(default_factory=UsageAccumulator)
    tools_called: ToolCallRecord = field(default_factory=ToolCallRecord)
    citations: list[str] = field(default_factory=list)
    cache: ToolCache | None = None
    # Counted on the context rather than returned, so the usage log still
    # reports the real figure when a run raises partway through.
    iterations: int = 0
    # Resolved once per question so tools do not each re-fetch it, and so the
    # season id / season number distinction is settled in one place.
    season_id: int | None = None
    season_number: int | None = None

    def cite(self, citation: str) -> None:
        if citation not in self.citations:
            self.citations.append(citation)

    async def resolve_season(self) -> None:
        """Populate season id and number.

        These are not interchangeable: `franchise_standings` wants an id while
        `tier_standings` and player queries want a number, and mixing them
        returns empty results rather than an error.
        """
        if self.season_id is not None or self.season_number is not None:
            return
        season: Any = await self.cog.current_season(self.guild)
        if season is None:
            return
        self.season_id = season.id
        self.season_number = season.number
