from abc import ABC, ABCMeta, abstractmethod
from datetime import datetime
from os import PathLike
from typing import TYPE_CHECKING, AsyncIterator
from zoneinfo import ZoneInfo

import aiohttp
import discord
from aiohttp.web_runner import AppRunner, TCPSite
from discord.ext.commands import CogMeta as DPYCogMeta
from redbot.core import Config as RedConfig
from redbot.core.bot import Red
from rscapi import Configuration as ApiConfig
from rscapi.models.activity_check import ActivityCheck
from rscapi.models.deleted import Deleted
from rscapi.models.franchise import Franchise
from rscapi.models.franchise_gm import FranchiseGM
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.franchise_standings import FranchiseStandings
from rscapi.models.high_level_match import HighLevelMatch
from rscapi.models.intent_to_play import IntentToPlay
from rscapi.models.league import League
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.match import Match
from rscapi.models.match_list import MatchList
from rscapi.models.match_results import MatchResults
from rscapi.models.member import Member as RSCMember
from rscapi.models.player import Player
from rscapi.models.player_season_stats import PlayerSeasonStats
from rscapi.models.rebrand_a_franchise import RebrandAFranchise
from rscapi.models.season import Season
from rscapi.models.team import Team
from rscapi.models.team_create import TeamCreate
from rscapi.models.team_list import TeamList
from rscapi.models.team_season_stats import TeamSeasonStats
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
    from rsc.combines.models import CombinesLobby


class RSCMixIn(ABC):
    """ABC class used for type hinting RSC Mix In modules"""

    bot: Red
    config: RedConfig

    _league: dict[int, int]
    _api_conf: dict[int, ApiConfig]

    _franchise_cache: dict[int, list[str]]
    _web_runner: AppRunner
    _web_site: TCPSite

    _team_cache: dict[int, list[str]]

    # Core

    @abstractmethod
    async def timezone(self, guild: discord.Guild) -> ZoneInfo:
        ...

    @abstractmethod
    async def _get_api_url(self, guild: discord.Guild) -> str | None:
        ...

    # Admin

    @abstractmethod
    async def _get_dates(self, guild: discord.Guild) -> str:
        ...

    # Combines

    @abstractmethod
    async def combine_players_from_lobby(
        self, guild: discord.Guild, lobby: "CombinesLobby"
    ) -> list[discord.Member]:
        ...

    @abstractmethod
    async def _set_combines_category(
        self, guild: discord.Guild, category: discord.CategoryChannel
    ):
        ...

    @abstractmethod
    async def _get_combines_category(
        self, guild: discord.Guild
    ) -> discord.CategoryChannel | None:
        ...

    @abstractmethod
    async def _get_combines_api(self, guild: discord.Guild) -> str | None:
        ...

    @abstractmethod
    async def _set_combines_api(self, guild: discord.Guild, url: str):
        ...

    @abstractmethod
    async def _get_combines_active(self, guild: discord.Guild) -> bool:
        ...

    @abstractmethod
    async def _set_combines_active(self, guild: discord.Guild, active: bool):
        ...

    # Franchises

    @abstractmethod
    async def franchises(
        self,
        guild: discord.Guild,
        prefix: str | None = None,
        gm_name: str | None = None,
        gm_discord_id: int | None = None,
        name: str | None = None,
        tier: int | None = None,
        tier_name: str | None = None,
    ) -> list[FranchiseList]:
        ...

    @abstractmethod
    async def franchise_gm_by_name(
        self, guild: discord.Guild, name: str
    ) -> FranchiseGM | None:
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
    async def full_logo_url(self, guild: discord.Guild, logo_url: str) -> str:
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
    async def league_player_update_handler(self, request: aiohttp.web.Request):
        ...

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

    @abstractmethod
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
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    async def league_seasons(self, guild: discord.Guild) -> list[Season]:
        ...

    # Free Agents

    @abstractmethod
    async def update_freeagent_visibility(
        self, guild: discord.Guild, player: discord.Member, visibility: bool
    ):
        ...

    # Matches

    @abstractmethod
    async def is_future_match_date(
        self, guild: discord.Guild, match: Match | MatchList
    ) -> bool:
        ...

    @abstractmethod
    async def is_match_franchise_gm(self, member: discord.Member, match: Match) -> bool:
        ...

    @abstractmethod
    async def discord_member_in_match(
        self, member: discord.Member, match: Match
    ) -> bool:
        ...

    @staticmethod
    @abstractmethod
    async def get_match_from_list(
        home: str, away: str, matches: list[Match]
    ) -> Match | None:
        ...

    @abstractmethod
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
        ...

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
    ) -> list[MatchList]:
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    async def match_by_id(self, guild: discord.Guild, id: int) -> Match:
        ...

    # Members

    @abstractmethod
    async def transfer_membership(
        self, guild: discord.Guild, old: int, new: discord.Member
    ) -> RSCMember:
        ...

    @abstractmethod
    async def league_player_from_member(
        self, guild: discord.Guild, member: RSCMember
    ) -> LeaguePlayer | None:
        ...

    @abstractmethod
    async def change_member_name(
        self,
        guild: discord.Guild,
        id: int,
        name: str,
    ) -> RSCMember:
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
    ) -> list[RSCMember]:
        ...

    @abstractmethod
    def paged_members(
        self,
        guild: discord.Guild,
        rsc_name: str | None = None,
        discord_username: str | None = None,
        discord_id: int | None = None,
        per_page: int = 100,
    ) -> AsyncIterator[RSCMember]:
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
        player: discord.Member,
        season: int | None = None,
        postseason: bool = False,
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
    ) -> RSCMember:
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

    @abstractmethod
    async def activity_check(
        self,
        guild: discord.Guild,
        player: discord.Member,
        returning_status: bool,
        executor: discord.Member,
        override: bool = False,
    ) -> ActivityCheck:
        ...

    # Seasons

    @abstractmethod
    async def seasons(self, guild: discord.Guild) -> list[Season]:
        ...

    @abstractmethod
    async def season_by_id(self, guild: discord.Guild, season_id: int) -> Season:
        ...

    @abstractmethod
    async def player_intents(
        self,
        guild: discord.Guild,
        season_id: int,
        player: discord.Member | None = None,
        returning: bool | None = None,
        missing: bool | None = None,
    ) -> list[IntentToPlay]:
        ...

    @abstractmethod
    async def franchise_standings(
        self, guild: discord.Guild, season_id: int
    ) -> list[FranchiseStandings]:
        ...

    @abstractmethod
    async def next_season(self, guild: discord.Guild) -> Season | None:
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

    @abstractmethod
    async def team_stats(
        self,
        guild: discord.Guild,
        team_id: int,
        season: int | None = None,
    ) -> TeamSeasonStats:
        ...

    @abstractmethod
    async def create_team(
        self,
        guild: discord.Guild,
        name: str,
        franchise: str,
        tier: str,
    ) -> TeamCreate:
        ...

    @abstractmethod
    async def delete_team(self, guild: discord.Guild, team_id: int):
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
    async def expire_sub(
        self,
        guild: discord.Guild,
        player: discord.Member,
        executor: discord.Member,
    ) -> LeaguePlayer:
        ...

    @abstractmethod
    async def _trans_role(self, guild: discord.Guild) -> discord.Role | None:
        ...

    @abstractmethod
    async def _trans_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        ...

    # Welcome

    @abstractmethod
    async def _get_welcome_roles(self, guild: discord.Guild) -> list[discord.Role]:
        ...


class MixInMetaClass(RSCMixIn, ABCMeta):
    pass


class CompositeMetaClass(DPYCogMeta, ABCMeta):
    """
    This allows the metaclass used for proper type detection to
    coexist with discord.py's metaclass
    """

    pass
