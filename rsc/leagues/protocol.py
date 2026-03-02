"""Protocol definition for LeagueMixIn."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable


if TYPE_CHECKING:
    import discord
    import aiohttp.web

    from collections.abc import AsyncIterator
    from datetime import datetime

    from rscapi.models.league import League
    from rscapi.models.league_player import LeaguePlayer
    from rscapi.models.season import Season

    from rsc.enums import Status


@runtime_checkable
class LeagueProtocol(Protocol):
    """Protocol for league-related operations."""

    async def league_player_update_handler(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """Handle league player update webhook."""
        ...

    async def leagues(self, guild: discord.Guild) -> list[League]:
        """Get all leagues."""
        ...

    async def league(self, guild: discord.Guild) -> League | None:
        """Get the configured league for a guild."""
        ...

    async def league_by_id(self, guild: discord.Guild, id: int) -> League | None:
        """Get a league by its ID."""
        ...

    async def current_season(self, guild: discord.Guild) -> Season | None:
        """Get the current season for the guild's league."""
        ...

    async def league_seasons(self, guild: discord.Guild) -> list[Season]:
        """Get all seasons for the guild's league."""
        ...

    async def players(
        self,
        guild: discord.Guild,
        status: Status | None = None,
        name: str | None = None,
        tier: int | None = None,
        tier_name: str | None = None,
        season: int | None = None,
        season_number: int | None = None,
        team_name: str | None = None,
        franchise: str | None = None,
        discord_id: int | None = None,
        limit: int = 0,
        offset: int = 0,
    ) -> list[LeaguePlayer]:
        """Fetch league players with optional filters."""
        ...

    async def total_players(
        self,
        guild: discord.Guild,
        status: Status | None = None,
        name: str | None = None,
        tier: int | None = None,
        tier_name: str | None = None,
        season: int | None = None,
        season_number: int | None = None,
        team_name: str | None = None,
        franchise: str | None = None,
        discord_id: int | None = None,
    ) -> int:
        """Get total count of players matching filters."""
        ...

    def paged_players(
        self,
        guild: discord.Guild,
        status: Status | None = None,
        name: str | None = None,
        tier: int | None = None,
        tier_name: str | None = None,
        season: int | None = None,
        season_number: int | None = None,
        team_name: str | None = None,
        franchise: str | None = None,
        discord_id: int | None = None,
        per_page: int = 100,
    ) -> AsyncIterator[LeaguePlayer]:
        """Iterate through players with pagination."""
        ...

    async def update_league_player(
        self,
        guild: discord.Guild,
        player_id: int,
        executor: discord.Member,
        base_mmr: int | None = None,
        current_mmr: int | None = None,
        tier: int | None = None,
        status: Status | None = None,
        team: str | None = None,
        contract_length: int | None = None,
        waiver_period: datetime | None = None,
    ) -> LeaguePlayer:
        """Update a league player's attributes."""
        ...
