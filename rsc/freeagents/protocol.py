"""Protocol definition for FreeAgentMixIn."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable


if TYPE_CHECKING:
    import discord
    from rscapi.models import LeaguePlayer
    from rsc.types import CheckIn


@runtime_checkable
class FreeAgentProtocol(Protocol):
    """Protocol for free agent-related operations."""

    async def checkins_by_tier(self, guild: discord.Guild, tier: str) -> list[CheckIn]:
        """Get check-ins filtered by tier."""
        ...

    async def checkins(self, guild: discord.Guild) -> list[CheckIn]:
        """Get all check-ins."""
        ...

    async def clear_checkins_by_tier(self, guild: discord.Guild, tier: str) -> None:
        """Clear all check-ins for a tier."""
        ...

    async def clear_all_checkins(self, guild: discord.Guild) -> None:
        """Clear all check-ins."""
        ...

    async def add_checkin(self, guild: discord.Guild, player: CheckIn) -> None:
        """Add a player check-in."""
        ...

    async def remove_checkin(self, guild: discord.Guild, player: CheckIn) -> None:
        """Remove a player check-in."""
        ...

    async def update_freeagent_visibility(self, guild: discord.Guild, player: discord.Member, visibility: bool) -> None:
        """Update a free agent's visibility status."""
        ...

    async def is_checked_in(self, player: discord.Member) -> bool:
        """Check if a player is checked in."""
        ...

    async def get_checkin(self, player: discord.Member) -> CheckIn | None:
        """Get check-in info for a player."""
        ...

    async def free_agents(self, guild: discord.Guild, tier_name: str) -> list[LeaguePlayer]:
        """Get free agents in a tier."""
        ...

    async def permanent_free_agents(self, guild: discord.Guild, tier_name: str) -> list[LeaguePlayer]:
        """Get permanent free agents in a tier."""
        ...
