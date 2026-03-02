"""Protocol definition for MemberMixIn."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable


if TYPE_CHECKING:
    import discord
    from collections.abc import AsyncIterator
    from rsc.enums import Status
    from rscapi.models import (
        LeaguePlayerPatch,
        ActivityCheck,
        Deleted,
        LeaguePlayer,
        Member as RSCMember,
        NameChangeHistory,
        PlayerSeasonStats,
    )

    from rsc.enums import Platform, PlayerType, Referrer, RegionPreference


@runtime_checkable
class MemberProtocol(Protocol):
    """Protocol for member-related operations."""

    async def league_player_from_member(self, guild: discord.Guild, member: RSCMember) -> LeaguePlayer | None:
        """Get league player data from an RSC member."""
        ...

    async def members(
        self,
        guild: discord.Guild,
        rsc_name: str | None = None,
        discord_username: str | None = None,
        discord_id: int | None = None,
        limit: int = 0,
        offset: int = 0,
    ) -> list[RSCMember]:
        """Fetch members with optional filters."""
        ...

    def paged_members(
        self,
        guild: discord.Guild,
        rsc_name: str | None = None,
        discord_username: str | None = None,
        discord_id: int | None = None,
        per_page: int = 100,
    ) -> AsyncIterator[RSCMember]:
        """Iterate through members with pagination."""
        ...

    async def signup(
        self,
        guild: discord.Guild,
        member: discord.Member,
        rsc_name: str,
        trackers: list[str],
        region_preference: RegionPreference | None = None,
        player_type: PlayerType | None = None,
        platform: Platform | None = None,
        referrer: Referrer | None = None,
        accepted_rules: bool = True,
        accepted_match_nights: bool = True,
        executor: discord.Member | None = None,
        override: bool = False,
    ) -> LeaguePlayer:
        """Sign up a new player."""
        ...

    async def create_member(
        self,
        guild: discord.Guild,
        member: discord.Member,
        rsc_name: str | None = None,
    ) -> RSCMember:
        """Create a new RSC member."""
        ...

    async def delete_member(
        self,
        guild: discord.Guild,
        member: discord.Member,
    ) -> None:
        """Delete an RSC member."""
        ...

    async def change_member_name(
        self,
        guild: discord.Guild,
        id: int,
        name: str,
        override: bool = False,
    ) -> RSCMember:
        """Change a member's RSC name."""
        ...

    async def player_stats(
        self,
        guild: discord.Guild,
        player: discord.Member,
        season: int | None = None,
        postseason: bool = False,
    ) -> PlayerSeasonStats:
        """Get player statistics."""
        ...

    async def declare_intent(
        self,
        guild: discord.Guild,
        member: discord.Member,
        returning: bool,
        executor: discord.Member | None = None,
        admin_overrride: bool = False,
    ) -> Deleted:
        """Declare a player's intent to return."""
        ...

    async def activity_check(
        self,
        guild: discord.Guild,
        player: discord.Member,
        returning_status: bool,
        executor: discord.Member,
        override: bool = False,
    ) -> ActivityCheck:
        """Perform an activity check for a player."""
        ...

    async def transfer_membership(self, guild: discord.Guild, old: int, new: discord.Member) -> RSCMember:
        """Transfer membership to a new discord account."""
        ...

    async def name_history(self, guild: discord.Guild, member: discord.Member) -> list[NameChangeHistory]:
        """Get name change history for a member."""
        ...

    async def make_league_player(
        self,
        guild: discord.Guild,
        member: discord.Member,
        base_mmr: int,
        current_mmr: int,
        tier: int,
        status: Status | None = None,
        team_name: str | None = None,
        contract_length: int | None = None,
    ) -> LeaguePlayerPatch:
        """Make a member into a league player in a specific tier."""
        ...

    async def drop_player_from_league(
        self,
        guild: discord.Guild,
        member: discord.Member,
    ) -> RSCMember:
        """Drop a player from the league."""
        ...
