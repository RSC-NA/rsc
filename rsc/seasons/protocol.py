"""Protocol definition for SeasonsMixIn."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable


if TYPE_CHECKING:
    import discord
    from rscapi.models import FranchiseStandings, IntentToPlay, Season


@runtime_checkable
class SeasonProtocol(Protocol):
    """Protocol for season-related operations."""

    async def next_season(self, guild: discord.Guild) -> Season | None:
        """Get the next upcoming season."""
        ...

    async def seasons(self, guild: discord.Guild, number: int | None = None, current: bool = False) -> list[Season]:
        """Fetch seasons with optional filters."""
        ...

    async def season_by_id(self, guild: discord.Guild, season_id: int) -> Season:
        """Get a season by its ID."""
        ...

    async def player_intents(
        self,
        guild: discord.Guild,
        season_id: int,
        player: discord.Member | None = None,
        returning: bool | None = None,
        missing: bool | None = None,
    ) -> list[IntentToPlay]:
        """Get player intents for a season."""
        ...

    async def franchise_standings(self, guild: discord.Guild, season_id: int) -> list[FranchiseStandings]:
        """Get franchise standings for a season."""
        ...
