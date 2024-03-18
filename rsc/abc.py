from abc import ABC, ABCMeta, abstractmethod
from datetime import datetime
from os import PathLike
from typing import TYPE_CHECKING, Optional
from zoneinfo import ZoneInfo

import discord
from discord.ext.commands import CogMeta as DPYCogMeta
from redbot.core import Config as RedConfig
from redbot.core.bot import Red
from rscapi import Configuration as ApiConfig
from rscapi.models.deleted import Deleted
from rscapi.models.franchise import Franchise
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.high_level_match import HighLevelMatch
from rscapi.models.league import League
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.match import Match
from rscapi.models.match_list import MatchList
from rscapi.models.member import Member
from rscapi.models.player import Player
from rscapi.models.player_season_stats import PlayerSeasonStats
from rscapi.models.rebrand_a_franchise import RebrandAFranchise
from rscapi.models.season import Season
from rscapi.models.team import Team
from rscapi.models.team_list import TeamList
from rscapi.models.tier import Tier
from rscapi.models.tracker_link import TrackerLink
from rscapi.models.tracker_link_stats import TrackerLinkStats

from rsc.enums import (
    MatchFormat,
    MatchTeamEnum,
    MatchType,
    Platform,
    PlayerType,
    Referrer,
    RegionPreference,
    Status,
    TrackerLinksStatus,
)

if TYPE_CHECKING:
    from rsc.ranks.api import RapidApi


class RSCMixIn(ABC):
    """ABC class used for type hinting RSC Mix In modules"""

    bot: Red
    config: RedConfig

    rapid_api: dict[int, "RapidApi"]

    _league: dict[int, int]
    _api_conf: dict[int, ApiConfig]

    _franchise_cache: dict[int, list[str]]

    # Core

    @abstractmethod
    async def timezone(self, guild: discord.Guild) -> ZoneInfo:
        ...

    @abstractmethod
    async def rapid_connector(self, guild: discord.Guild) -> Optional["RapidApi"]:
        ...

    @abstractmethod
    async def _get_api_url(self, guild: discord.Guild) -> str | None:
        ...

    # Admin

    @abstractmethod
    async def _get_dates(self, guild: discord.Guild) -> str:
        ...

    # Franchises

    @abstractmethod
    async def franchises(
        self,
        guild: discord.Guild,
        prefix: str | None = None,
        gm_name: str | None = None,
        name: str | None = None,
        tier: str | None = None,
        tier_name: str | None = None,
    ) -> list[FranchiseList]:
        ...

    @abstractmethod
    async def upload_franchise_logo(
        self,
        guild: discord.Guild,
        id: int,
        logo: str | bytes | PathLike,
    ) -> Franchise:
        ...

    @abstractmethod
    async def franchise_by_id(self, guild: discord.Guild, id: int) -> Franchise | None:
        ...

    @abstractmethod
    async def franchise_logo(self, guild: discord.Guild, id: int) -> str | None:
        ...

    @abstractmethod
    async def full_logo_url(self, guild: discord.Guild, logo_url: str) -> str | None:
        ...

    @abstractmethod
    async def rebrand_franchise(
        self, guild: discord.Guild, id: int, rebrand: RebrandAFranchise
    ) -> Franchise:
        ...

    @abstractmethod
    async def delete_franchise(self, guild: discord.Guild, id: int) -> None:
        ...

    @abstractmethod
    async def transfer_franchise(
        self, guild: discord.Guild, id: int, gm: discord.Member
    ) -> Franchise:
        ...

    @abstractmethod
    async def create_franchise(
        self,
        guild: discord.Guild,
        name: str,
        prefix: str,
        gm: discord.Member,
    ) -> Franchise:
        ...

    # League

    @abstractmethod
    async def leagues(self, guild: discord.Guild) -> list[League]:
        ...

    @abstractmethod
    async def league(self, guild: discord.Guild) -> League | None:
        ...

    @abstractmethod
    async def league_by_id(self, guild: discord.Guild, id: int) -> League | None:
        ...

    @abstractmethod
    async def current_season(self, guild: discord.Guild) -> Season | None:
        ...

    @abstractmethod
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
        ...

    # Matches

    @abstractmethod
    async def is_match_day(self, guild: discord.Guild) -> bool:
        ...

    @abstractmethod
    async def matches(
        self,
        guild: discord.Guild,
        date__lt: datetime | None = None,
        date__gt: datetime | None = None,
        season: int | None = None,
        season_number: int | None = None,
        match_team_type: MatchTeamEnum = MatchTeamEnum.ALL,
        team_name: str | None = None,
        day: int | None = None,
        match_type: MatchType | None = None,
        match_format: MatchFormat | None = None,
        limit: int = 0,
        offset: int = 0,
        preseason: int = 0,
    ) -> list[MatchList]:
        ...

    @abstractmethod
    async def find_match(
        self,
        guild: discord.Guild,
        teams: str,
        date__lt: datetime | None = None,
        date__gt: datetime | None = None,
        season: int | None = None,
        season_number: int | None = None,
        day: int | None = None,
        match_type: MatchType | None = None,
        match_format: MatchFormat | None = None,
        limit: int = 0,
        offset: int = 0,
        preseason: int = 0,
    ) -> list[Match]:
        ...

    @abstractmethod
    async def match_by_id(self, guild: discord.Guild, id: int) -> Match:
        ...

    # Members

    @abstractmethod
    async def change_member_name(
        self,
        guild: discord.Guild,
        id: int,
        name: str,
    ) -> Member:
        ...

    @abstractmethod
    async def members(
        self,
        guild: discord.Guild,
        rsc_name: str | None = None,
        discord_username: str | None = None,
        discord_id: int | None = None,
        limit: int = 0,
        offset: int = 0,
    ) -> list[Member]:
        ...

    @abstractmethod
    async def declare_intent(
        self,
        guild: discord.Guild,
        member: discord.Member,
        returning: bool,
        executor: discord.Member | None = None,
        admin_overrride: bool = False,
    ) -> Deleted:
        ...

    @abstractmethod
    async def player_stats(
        self,
        guild: discord.Guild,
        id: int,
        season: int | None = None,
    ) -> PlayerSeasonStats:
        ...

    @abstractmethod
    async def delete_member(
        self,
        guild: discord.Guild,
        member: discord.Member,
    ):
        ...

    @abstractmethod
    async def create_member(
        self,
        guild: discord.Guild,
        member: discord.Member,
        rsc_name: str | None = None,
    ) -> Member:
        ...

    @abstractmethod
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
        ...

    # Teams

    @abstractmethod
    async def teams(
        self,
        guild: discord.Guild,
        seasons: str | None = None,
        franchise: str | None = None,
        name: str | None = None,
        tier: str | None = None,
    ) -> list[TeamList]:
        ...

    @abstractmethod
    async def season_matches(
        self,
        guild: discord.Guild,
        id: int,
        season: int | None = None,
        preseason: bool = True,
    ) -> list[HighLevelMatch]:
        ...

    @abstractmethod
    async def next_match(
        self,
        guild: discord.Guild,
        id: int,
    ) -> Match | None:
        ...

    @abstractmethod
    async def team_id_by_name(self, guild: discord.Guild, name: str) -> int:
        ...

    @abstractmethod
    async def team_by_id(
        self,
        guild: discord.Guild,
        id: int,
    ) -> Team:
        ...

    @abstractmethod
    async def team_players(
        self,
        guild: discord.Guild,
        id: int,
    ) -> list[Player]:
        ...

    # Tiers

    @abstractmethod
    async def tiers(self, guild: discord.Guild, name: str | None = None) -> list[Tier]:
        ...

    @abstractmethod
    async def is_valid_tier(self, guild: discord.Guild, name: str) -> bool:
        ...

    # Trackers

    @abstractmethod
    async def trackers(
        self,
        guild: discord.Guild,
        status: TrackerLinksStatus | None = None,
        player: discord.Member | int | None = None,
        name: str | None = None,
        limit: int = 0,
        offset: int = 0,
    ) -> list[TrackerLink]:
        ...

    @abstractmethod
    async def tracker_stats(
        self,
        guild: discord.Guild,
    ) -> TrackerLinkStats:
        """Fetch RSC Tracker Stats"""
        ...

    @abstractmethod
    async def next_tracker(
        self,
        guild: discord.Guild,
        limit: int = 25,
    ) -> list[TrackerLink]:
        """Get list of trackers ready to be updated"""

    @abstractmethod
    async def add_tracker(
        self,
        guild: discord.Guild,
        player: discord.Member,
        tracker: str,
    ):
        ...

    # Transactions

    @abstractmethod
    async def _trans_role(self, guild: discord.Guild) -> discord.Role | None:
        ...

    @abstractmethod
    async def _trans_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        ...


class CompositeMetaClass(DPYCogMeta, ABCMeta):
    """
    This allows the metaclass used for proper type detection to
    coexist with discord.py's metaclass
    """

    pass
