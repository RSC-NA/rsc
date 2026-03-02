"""Protocol definition for MatchMixIn."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable


if TYPE_CHECKING:
    import discord
    from collections.abc import AsyncIterator
    from datetime import datetime
    from rscapi.models.match import Match
    from rscapi.models.match_list import MatchList
    from rscapi.models.match_results import MatchResults

    from rsc.enums import MatchFormat, MatchTeamEnum, MatchType


@runtime_checkable
class MatchProtocol(Protocol):
    """Protocol for match-related operations."""

    async def discord_member_in_match(self, member: discord.Member, match: Match) -> bool:
        """Check if a discord member is in a match."""
        ...

    @staticmethod
    async def get_match_from_list(home: str, away: str, matches: list[Match]) -> Match | None:
        """Find a match from a list by home/away team names."""
        ...

    async def is_match_day(self, guild: discord.Guild) -> bool:
        """Check if today is a match day."""
        ...

    async def match_team_by_user(self, match: Match, member: discord.Member) -> MatchTeamEnum:
        """Get which team a user belongs to in a match."""
        ...

    async def build_match_embed(
        self,
        guild: discord.Guild,
        match: Match,
        user_team: MatchTeamEnum | None = None,
        with_gm: bool = True,
    ) -> discord.Embed:
        """Build an embed displaying match information."""
        ...

    async def roster_fmt_from_match(self, guild: discord.Guild, match: Match, with_gm: bool = True) -> tuple[str, str]:
        """Format roster strings for a match."""
        ...

    async def is_match_franchise_gm(self, member: discord.Member, match: Match) -> bool:
        """Check if a member is the GM of a franchise in the match."""
        ...

    async def is_match_franchise_agm(self, member: discord.Member, match: Match) -> bool:
        """Check if a member is the AGM of a franchise in the match."""
        ...

    async def is_future_match_date(self, guild: discord.Guild, match: Match | MatchList) -> bool:
        """Check if a match is scheduled for a future date."""
        ...

    async def matches(
        self,
        guild: discord.Guild,
        date__lt: datetime | None = None,
        date__gt: datetime | None = None,
        season: int | None = None,
        season_number: int | None = None,
        match_team_type: MatchTeamEnum = ...,
        team_name: str | None = None,
        day: int | None = None,
        match_type: MatchType | None = None,
        match_format: MatchFormat | None = None,
        limit: int = 0,
        offset: int = 0,
    ) -> list[MatchList]:
        """Fetch matches with optional filters."""
        ...

    def paged_matches(
        self,
        guild: discord.Guild,
        season_number: int,
        date__lt: datetime | None = None,
        date__gt: datetime | None = None,
        season: int | None = None,
        match_team_type: MatchTeamEnum = ...,
        team_name: str | None = None,
        day: int | None = None,
        match_type: MatchType | None = None,
        match_format: MatchFormat | None = None,
        limit: int = 0,
        offset: int = 0,
        per_page: int = 100,
    ) -> AsyncIterator[MatchList]:
        """Iterate through matches with pagination."""
        ...

    async def match_by_day(self, guild: discord.Guild, team_id: int, day: int, preseason: bool = False) -> Match:
        """Get a match by team and day."""
        ...

    async def find_match(
        self,
        guild: discord.Guild,
        teams: list[str],
        date_lt: datetime | None = None,
        date_gt: datetime | None = None,
        season: int | None = None,
        season_number: int | None = None,
        day: int | None = None,
        match_type: MatchType | None = None,
        match_format: MatchFormat | None = None,
        limit: int = 0,
        offset: int = 0,
        preseason: int = 0,
    ) -> list[Match]:
        """Find matches with specific criteria."""
        ...

    async def match_by_id(self, guild: discord.Guild, id: int) -> Match:
        """Get a match by its ID."""
        ...

    async def report_match(
        self,
        guild: discord.Guild,
        match_id: int,
        ballchasing_group: str,
        home_score: int,
        away_score: int,
        executor: discord.Member,
        override: bool = False,
    ) -> MatchResults:
        """Report match results."""
        ...

    async def create_match(
        self,
        guild: discord.Guild,
        match_type: MatchType,
        match_format: MatchFormat,
        home_team_id: int,
        away_team_id: int,
        day: int,
    ) -> Match:
        """Create a new match."""
        ...

    async def match_results(self, guild: discord.Guild, id: int) -> MatchResults:
        """Get the results of a match."""
        ...
