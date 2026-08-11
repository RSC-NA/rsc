import logging
from abc import ABC, ABCMeta, abstractmethod
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from os import PathLike
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from aiohttp import web
import discord
from aiohttp.web_runner import AppRunner, TCPSite
from discord.ext.commands import CogMeta as DPYCogMeta
from redbot.core import Config as RedConfig
from redbot.core.bot import Red
from rscapi import ApiClient, Configuration as ApiConfig
from rscapi.models.activity_check import ActivityCheck
from rscapi.models.deleted import Deleted
from rscapi.models.elevated_role import ElevatedRole
from rscapi.models import Franchise
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
from rscapi.models.name_change_history import NameChangeHistory
from rscapi.models.player_season_stats import PlayerSeasonStats
from rscapi.models.player_season_stats_in_depth import PlayerSeasonStatsInDepth
from rscapi.models.franchise_rebrand import FranchiseRebrand
from rscapi.models.season import Season
from rscapi.models.team import Team
from rscapi.models.team_create import TeamCreate
from rscapi.models.team_list import TeamList
from rscapi.models.team_player import TeamPlayer
from rscapi.models.team_season_stats import TeamSeasonStats
from rscapi.models.team_standings import TeamStandings
from rscapi.models.tier import Tier
from rscapi.models.tracker_link import TrackerLink
from rscapi.models.tracker_link_stats import TrackerLinkStats
from rscapi.models.transaction_response import TransactionResponse

from rsc.enums import (
    MatchFormat,
    MatchTeamEnum,
    MatchType,
    Platform,
    PlayerType,
    Referrer,
    RegionPreference,
    StaffPositions,
    Status,
    TrackerLinksStatus,
    TransactionType,
)

if TYPE_CHECKING:
    from rsc.combines.models import CombinesLobby
    from rsc.events.models import EventPage, LeagueEventData
    from rsc.utils.dm import DMHelper


logger = logging.getLogger("red.rsc.abc")


class RSCMixIn(ABC):
    """ABC class used for type hinting RSC Mix In modules"""

    bot: Red
    config: RedConfig

    _league: dict[int, int]
    _api_conf: dict[int, ApiConfig]
    # Long lived API clients. One session per guild, reused for the process
    # lifetime so calls do not pay a TLS handshake each time.
    _api_clients: dict[int, ApiClient]

    _franchise_cache: dict[int, list[str]]
    _web_runner: AppRunner | None
    _web_site: TCPSite | None

    _team_cache: dict[int, list[str]]

    # guild.id -> discord_id -> (monotonic expiry, positions held in that guild's league)
    _elevated_role_cache: dict[int, dict[int, tuple[float, frozenset[str]]]]

    _dm_helper: "DMHelper"

    # Core

    @asynccontextmanager
    async def api_client(self, guild: discord.Guild) -> AsyncIterator[ApiClient]:
        """Yield the guild's long lived API client.

        Deliberately does NOT close the client on exit. `ApiClient` owns an
        `aiohttp.ClientSession` created on first request and closed by
        `ApiClient.close()`, so the previous `async with ApiClient(...)` pattern
        paid a fresh TCP + TLS handshake on every single call. The session is
        safe for concurrent use and is torn down by `close_api_clients()`.
        """
        # Lazily initialized: a mixin used standalone has not run RSC.__init__.
        cache = getattr(self, "_api_clients", None)
        if cache is None:
            cache = self._api_clients = {}

        client = cache.get(guild.id)
        if client is None:
            client = ApiClient(self._api_conf[guild.id])
            cache[guild.id] = client
        yield client

    async def close_api_clients(self):
        """Close every long lived API client and drop them from the cache."""
        cache = getattr(self, "_api_clients", None)
        if cache is None:
            return
        for guild_id, client in list(cache.items()):
            del cache[guild_id]
            try:
                await client.close()
            except Exception as exc:
                logger.warning(f"Error closing API client for guild {guild_id}: {exc}")

    @abstractmethod
    async def timezone(self, guild: discord.Guild) -> ZoneInfo: ...

    @abstractmethod
    async def _get_api_url(self, guild: discord.Guild) -> str | None: ...

    @abstractmethod
    async def _get_modmail_bot(self, guild: discord.Guild) -> int: ...

    # Events

    @abstractmethod
    async def fetch_league_events(
        self,
        guild: discord.Guild,
        *,
        id__gt: int,
        limit: int,
        include_private: bool = False,
        include_global: bool = False,
    ) -> "EventPage": ...

    @abstractmethod
    async def newest_league_event(
        self,
        guild: discord.Guild,
        *,
        include_private: bool = False,
        include_global: bool = False,
    ) -> "LeagueEventData | None": ...

    @abstractmethod
    async def league_event(self, guild: discord.Guild, event_id: int) -> "LeagueEventData | None": ...

    @abstractmethod
    async def _get_event_channel(self, guild: discord.Guild) -> "discord.TextChannel | discord.Thread | None": ...

    @abstractmethod
    async def _try_post_embeds(self, guild: discord.Guild, embeds: Sequence[discord.Embed]) -> None: ...

    # Admin

    @abstractmethod
    async def _get_dates(self, guild: discord.Guild) -> str: ...

    # @abstractmethod
    # async def _set_permfa_announce_chnanel(
    #     self, guild: discord.Guild, channel: discord.TextChannel
    # ): ...

    # @abstractmethod
    # async def _get_permfa_announce_channel(
    #     self, guild: discord.Guild
    # ) -> discord.TextChannel | None: ...

    # @abstractmethod
    # async def _set_permfa_msg_ids(self, guild: discord.Guild, msg_ids: list[int]): ...

    # @abstractmethod
    # async def _get_permfa_msg_ids(self, guild: discord.Guild) -> list[int]: ...

    # Combines

    @abstractmethod
    async def combine_players_from_lobby(self, guild: discord.Guild, lobby: "CombinesLobby") -> list[discord.Member]: ...

    @abstractmethod
    async def _set_combines_category(self, guild: discord.Guild, category: discord.CategoryChannel): ...

    @abstractmethod
    async def _get_combines_category(self, guild: discord.Guild) -> discord.CategoryChannel | None: ...

    @abstractmethod
    async def _get_combines_api(self, guild: discord.Guild) -> str | None: ...

    @abstractmethod
    async def _set_combines_api(self, guild: discord.Guild, url: str): ...

    @abstractmethod
    async def _get_combines_active(self, guild: discord.Guild) -> bool: ...

    @abstractmethod
    async def _set_combines_active(self, guild: discord.Guild, active: bool): ...

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
    ) -> list[FranchiseList]: ...

    @abstractmethod
    async def franchise_gm_by_name(self, guild: discord.Guild, name: str) -> FranchiseGM | None: ...

    @abstractmethod
    async def upload_franchise_logo(
        self,
        guild: discord.Guild,
        id: int,
        logo: str | bytes | PathLike,
    ) -> Franchise: ...

    @abstractmethod
    async def franchise_by_id(self, guild: discord.Guild, id: int) -> Franchise | None: ...

    @abstractmethod
    async def franchise_logo(self, guild: discord.Guild, id: int) -> str | None: ...

    @abstractmethod
    async def full_logo_url(self, guild: discord.Guild, logo_url: str) -> str: ...

    @abstractmethod
    async def rebrand_franchise(self, guild: discord.Guild, id: int, rebrand: FranchiseRebrand) -> Franchise: ...

    @abstractmethod
    async def delete_franchise(self, guild: discord.Guild, id: int) -> None: ...

    @abstractmethod
    async def transfer_franchise(self, guild: discord.Guild, id: int, gm: discord.Member) -> Franchise: ...

    @abstractmethod
    async def create_franchise(
        self,
        guild: discord.Guild,
        name: str,
        prefix: str,
        gm: discord.Member,
    ) -> Franchise: ...

    @abstractmethod
    async def fetch_franchise(self, guild: discord.Guild, name: str) -> FranchiseList | None: ...

    @abstractmethod
    async def add_agm(
        self,
        guild: discord.Guild,
        id: int,
        agm: discord.Member | discord.User | int,
        executor: discord.Member | discord.User | int,
    ) -> Franchise: ...

    @abstractmethod
    async def remove_agm(
        self,
        guild: discord.Guild,
        id: int,
        agm: discord.Member | discord.User | int,
        executor: discord.Member | discord.User | int,
    ) -> Franchise: ...

    @abstractmethod
    async def franchises_agm_of(self, guild: discord.Guild, discord_id: int) -> list[FranchiseList]: ...

    # League

    @abstractmethod
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
    ) -> LeaguePlayer: ...

    @abstractmethod
    async def league_player_update_handler(self, request: web.Request): ...

    @abstractmethod
    async def leagues(self, guild: discord.Guild) -> list[League]: ...

    @abstractmethod
    async def league(self, guild: discord.Guild) -> League | None: ...

    @abstractmethod
    async def league_by_id(self, guild: discord.Guild, id: int) -> League | None: ...

    @abstractmethod
    async def current_season(self, guild: discord.Guild) -> Season | None: ...

    @abstractmethod
    async def season_activity_checks(
        self,
        guild: discord.Guild,
        season_id: int | None = None,
        season_number: int | None = None,
        discord_id: int | None = None,
        completed: bool | None = None,
        returning: bool | None = None,
        missing: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ActivityCheck]: ...

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
    ) -> list[LeaguePlayer]: ...

    @abstractmethod
    async def player_count(
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
    ) -> int: ...

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
    ) -> int: ...

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
    ) -> AsyncIterator[LeaguePlayer]: ...

    @abstractmethod
    async def league_seasons(self, guild: discord.Guild) -> list[Season]: ...

    # Free Agents

    @abstractmethod
    async def update_freeagent_visibility(self, guild: discord.Guild, player: discord.Member, visibility: bool): ...

    # Matches

    @abstractmethod
    async def create_match(
        self,
        guild: discord.Guild,
        match_type: MatchType,
        match_format: MatchFormat,
        home_team_id: int,
        away_team_id: int,
        day: int,
    ) -> Match: ...

    @abstractmethod
    async def is_future_match_date(self, guild: discord.Guild, match: Match | MatchList) -> bool: ...

    @abstractmethod
    async def is_match_franchise_gm(self, member: discord.Member, match: Match) -> bool: ...

    @abstractmethod
    async def discord_member_in_match(self, member: discord.Member, match: Match) -> bool: ...

    @staticmethod
    @abstractmethod
    async def get_match_from_list(home: str, away: str, matches: list[Match]) -> Match | None: ...

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
    ) -> MatchResults: ...

    @abstractmethod
    async def is_match_day(self, guild: discord.Guild) -> bool: ...

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
    ) -> list[MatchList]: ...

    @abstractmethod
    def paged_matches(
        self,
        guild: discord.Guild,
        season_number: int,
        date__lt: datetime | None = None,
        date__gt: datetime | None = None,
        season: int | None = None,
        match_team_type: MatchTeamEnum = MatchTeamEnum.ALL,
        team_name: str | None = None,
        day: int | None = None,
        match_type: MatchType | None = None,
        match_format: MatchFormat | None = None,
        limit: int = 0,
        offset: int = 0,
        per_page: int = 100,
    ) -> AsyncIterator[MatchList]: ...

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
    ) -> list[Match]: ...

    @abstractmethod
    async def match_results(self, guild: discord.Guild, id: int) -> MatchResults: ...

    @abstractmethod
    async def match_by_id(self, guild: discord.Guild, id: int) -> Match: ...

    # Members

    @abstractmethod
    async def name_history(self, guild: discord.Guild, member: discord.Member) -> list[NameChangeHistory]: ...

    @abstractmethod
    async def transfer_membership(self, guild: discord.Guild, old: int, new: discord.Member) -> RSCMember: ...

    @abstractmethod
    async def league_player_from_member(self, guild: discord.Guild, member: RSCMember) -> LeaguePlayer | None: ...

    @abstractmethod
    async def change_member_name(
        self,
        guild: discord.Guild,
        id: int,
        name: str,
        override: bool = False,
    ) -> RSCMember: ...

    @abstractmethod
    async def members(
        self,
        guild: discord.Guild,
        rsc_name: str | None = None,
        discord_username: str | None = None,
        discord_id: int | None = None,
        limit: int = 0,
        offset: int = 0,
    ) -> list[RSCMember]: ...

    @abstractmethod
    def paged_members(
        self,
        guild: discord.Guild,
        rsc_name: str | None = None,
        discord_username: str | None = None,
        discord_id: int | None = None,
        per_page: int = 100,
    ) -> AsyncIterator[RSCMember]: ...

    @abstractmethod
    async def member_elevated_roles(
        self,
        guild: discord.Guild,
        discord_id: int,
        position: str | None = None,
    ) -> list[ElevatedRole]: ...

    @abstractmethod
    async def create_elevated_role(
        self,
        guild: discord.Guild,
        member: discord.Member | discord.User | int,
        executor: discord.Member | discord.User | int,
        position: StaffPositions,
    ) -> RSCMember: ...

    @abstractmethod
    async def delete_elevated_role(self, guild: discord.Guild, discord_id: int, role_id: int) -> None: ...

    @abstractmethod
    def invalidate_elevated_role_cache(self, guild: discord.Guild, discord_id: int | None = None) -> None: ...

    @abstractmethod
    async def elevated_positions(self, guild: discord.Guild, discord_id: int) -> frozenset[str]: ...

    @abstractmethod
    async def league_elevated_roles(
        self,
        guild: discord.Guild,
        position: str | None = None,
        limit: int = 200,
    ) -> list[ElevatedRole]: ...

    @abstractmethod
    async def declare_intent(
        self,
        guild: discord.Guild,
        member: discord.Member | int,
        returning: bool,
        executor: discord.Member | None = None,
        admin_overrride: bool = False,
    ) -> Deleted: ...

    @abstractmethod
    async def player_stats(
        self,
        guild: discord.Guild,
        player: discord.Member,
        season: int | None = None,
        postseason: bool = False,
    ) -> PlayerSeasonStats: ...

    @abstractmethod
    async def delete_member(
        self,
        guild: discord.Guild,
        member: discord.Member,
    ): ...

    @abstractmethod
    async def create_member(
        self,
        guild: discord.Guild,
        member: discord.Member,
        rsc_name: str | None = None,
    ) -> RSCMember: ...

    @abstractmethod
    async def signup(
        self,
        guild: discord.Guild,
        member: discord.Member,
        rsc_name: str,
        trackers: list[str],
        region_preference: RegionPreference,
        player_type: PlayerType,
        platform: Platform,
        referrer: Referrer,
        accepted_rules: bool = True,
        accepted_match_nights: bool = True,
        executor: discord.Member | None = None,
        override: bool = False,
    ) -> LeaguePlayer: ...

    @abstractmethod
    async def activity_check(
        self,
        guild: discord.Guild,
        player: discord.Member,
        returning_status: bool,
        executor: discord.Member,
        override: bool = False,
    ) -> ActivityCheck: ...

    # Seasons

    @abstractmethod
    async def seasons(self, guild: discord.Guild, number: int | None = None, current: bool = False) -> list[Season]: ...

    @abstractmethod
    async def season_by_id(self, guild: discord.Guild, season_id: int) -> Season: ...

    @abstractmethod
    async def player_intents(
        self,
        guild: discord.Guild,
        season_id: int,
        player: discord.Member | None = None,
        returning: bool | None = None,
        missing: bool | None = None,
    ) -> list[IntentToPlay]: ...

    @abstractmethod
    async def franchise_standings(self, guild: discord.Guild, season_id: int) -> list[FranchiseStandings]: ...

    @abstractmethod
    async def next_season(self, guild: discord.Guild) -> Season | None: ...

    @abstractmethod
    async def next_signup_season(self, guild: discord.Guild) -> Season | None: ...

    # Teams

    @abstractmethod
    async def build_franchise_teams_embed(self, guild: discord.Guild, teams: list[TeamList]) -> discord.Embed: ...

    @abstractmethod
    async def build_roster_embed(self, guild: discord.Guild, players: list[LeaguePlayer]) -> discord.Embed: ...

    @abstractmethod
    async def team_id_by_name(self, guild: discord.Guild, name: str) -> int: ...

    @abstractmethod
    async def teams_in_same_tier(self, teams: list[Team | TeamList]) -> bool: ...

    @abstractmethod
    async def teams(
        self,
        guild: discord.Guild,
        seasons: str | None = None,
        franchise: str | None = None,
        name: str | None = None,
        tier: str | None = None,
    ) -> list[TeamList]: ...

    @abstractmethod
    async def tier_standings(self, guild: discord.Guild, tier_id: int, season: int) -> list[TeamStandings]: ...

    @abstractmethod
    async def tier_player_stats(
        self,
        guild: discord.Guild,
        tier_id: int,
        season: int | None = None,
        name: str | None = None,
    ) -> list[PlayerSeasonStatsInDepth]: ...

    @abstractmethod
    async def tier_team_stats(
        self,
        guild: discord.Guild,
        tier_id: int,
        season: int | None = None,
        name: str | None = None,
    ) -> list[TeamSeasonStats]: ...

    @abstractmethod
    async def season_matches(
        self,
        guild: discord.Guild,
        id: int,
        season: int | None = None,
        preseason: bool = True,
    ) -> list[HighLevelMatch]: ...

    @abstractmethod
    async def next_match(
        self,
        guild: discord.Guild,
        id: int,
    ) -> Match | None: ...

    @abstractmethod
    async def team_by_id(
        self,
        guild: discord.Guild,
        id: int,
    ) -> Team: ...

    @abstractmethod
    async def team_players(
        self,
        guild: discord.Guild,
        id: int,
    ) -> list[TeamPlayer]: ...

    @abstractmethod
    async def team_stats(
        self,
        guild: discord.Guild,
        team_id: int,
        season: int | None = None,
    ) -> TeamSeasonStats: ...

    @abstractmethod
    async def create_team(
        self,
        guild: discord.Guild,
        name: str,
        franchise: str,
        tier: str,
    ) -> TeamCreate: ...

    @abstractmethod
    async def delete_team(self, guild: discord.Guild, team_id: int): ...

    # Tiers

    @abstractmethod
    async def tiers(self, guild: discord.Guild, name: str | None = None) -> list[Tier]: ...

    @abstractmethod
    async def is_valid_tier(self, guild: discord.Guild, name: str) -> bool: ...

    @abstractmethod
    async def tier_id_by_name(self, guild: discord.Guild, tier: str) -> int: ...

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
    ) -> list[TrackerLink]: ...

    @abstractmethod
    async def tracker_stats(
        self,
        guild: discord.Guild,
    ) -> list[TrackerLinkStats]:
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
    ): ...

    @abstractmethod
    async def fetch_tracker_by_id(
        self,
        guild: discord.Guild,
        tracker_id: int,
    ) -> TrackerLink: ...

    @abstractmethod
    async def unlink_tracker(
        self,
        guild: discord.Guild,
        tracker_id: int,
        player: discord.Member,
        executor: discord.Member,
    ) -> TrackerLink: ...

    @abstractmethod
    async def rm_tracker(
        self,
        guild: discord.Guild,
        tracker_id: int,
    ) -> None: ...

    @abstractmethod
    async def link_tracker(
        self,
        guild: discord.Guild,
        tracker_id: int,
        player: discord.Member,
        executor: discord.Member,
    ) -> TrackerLink: ...

    # Transactions

    @abstractmethod
    async def transaction_history_by_id(self, guild: discord.Guild, transaction_id: int) -> TransactionResponse: ...

    @abstractmethod
    async def transaction_history(
        self,
        guild: discord.Guild,
        player: discord.Member | None = None,
        executor: discord.Member | None = None,
        season: int | None = None,
        trans_type: TransactionType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TransactionResponse]: ...

    @abstractmethod
    async def get_franchise_transaction_channel_name(self, franchise_name: str) -> str: ...

    @abstractmethod
    async def get_franchise_transaction_channel(self, guild: discord.Guild, franchise_name: str) -> discord.TextChannel | None: ...

    @abstractmethod
    async def expire_sub(
        self,
        guild: discord.Guild,
        player: discord.Member,
        executor: discord.Member,
    ) -> LeaguePlayer: ...

    @abstractmethod
    async def _trans_role(self, guild: discord.Guild) -> discord.Role | None: ...

    @abstractmethod
    async def _trans_channel(self, guild: discord.Guild) -> discord.TextChannel | None: ...

    # Welcome

    @abstractmethod
    async def _get_welcome_roles(self, guild: discord.Guild) -> list[discord.Role]: ...

    @abstractmethod
    async def add_devleague_role(self, member: discord.Member): ...

    @abstractmethod
    async def remove_devleague_role(self, member: discord.Member): ...

    @abstractmethod
    async def should_get_devleague_role(self, member: discord.Member) -> bool: ...


class MixInMetaClass(RSCMixIn, ABCMeta): ...


class CompositeMetaClass(DPYCogMeta, ABCMeta):
    """
    This allows the metaclass used for proper type detection to
    coexist with discord.py's metaclass
    """
