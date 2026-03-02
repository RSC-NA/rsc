"""Protocol definition for TeamMixIn."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable


if TYPE_CHECKING:
    import discord
    from rscapi.models import HighLevelMatch, LeaguePlayer, Match, Player, Team, TeamCreate, TeamList, TeamSeasonStats


@runtime_checkable
class TeamProtocol(Protocol):
    """Protocol for team-related operations."""

    async def teams_in_same_tier(self, teams: list[Team | TeamList]) -> bool:
        """Check if all teams are in the same tier."""
        ...

    async def team_id_by_name(self, guild: discord.Guild, name: str) -> int:
        """Get team ID from team name."""
        ...

    async def team_captain(self, guild: discord.Guild, team_name: str) -> LeaguePlayer | None:
        """Get the captain of a team."""
        ...

    async def tier_captains(self, guild: discord.Guild, tier_name: str) -> list[LeaguePlayer]:
        """Get all captains in a tier."""
        ...

    async def franchise_captains(self, guild: discord.Guild, franchise_name: str) -> list[LeaguePlayer]:
        """Get all captains in a franchise."""
        ...

    async def build_franchise_teams_embed(self, guild: discord.Guild, teams: list[TeamList]) -> discord.Embed:
        """Build an embed showing franchise teams."""
        ...

    async def build_roster_embed(self, guild: discord.Guild, players: list[LeaguePlayer]) -> discord.Embed:
        """Build an embed showing team roster."""
        ...

    async def teams(
        self,
        guild: discord.Guild,
        seasons: str | None = None,
        franchise: str | None = None,
        name: str | None = None,
        tier: str | None = None,
    ) -> list[TeamList]:
        """Fetch teams with optional filters."""
        ...

    async def team_by_id(
        self,
        guild: discord.Guild,
        id: int,
    ) -> Team:
        """Get a team by its ID."""
        ...

    async def team_players(
        self,
        guild: discord.Guild,
        id: int,
    ) -> list[Player]:
        """Get players on a team."""
        ...

    async def next_match(
        self,
        guild: discord.Guild,
        id: int,
    ) -> Match:
        """Get the next match for a team."""
        ...

    async def season_matches(
        self,
        guild: discord.Guild,
        id: int,
        season: int | None = None,
        preseason: bool = True,
    ) -> list[HighLevelMatch]:
        """Get all matches for a team in a season."""
        ...

    async def team_stats(
        self,
        guild: discord.Guild,
        team_id: int,
        season: int | None = None,
    ) -> TeamSeasonStats:
        """Get team statistics for a season."""
        ...

    async def create_team(
        self,
        guild: discord.Guild,
        name: str,
        franchise: str,
        tier: str,
    ) -> TeamCreate:
        """Create a new team."""
        ...

    async def delete_team(self, guild: discord.Guild, team_id: int) -> None:
        """Delete a team."""
        ...
