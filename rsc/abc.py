from abc import ABCMeta, ABC, abstractmethod
import discord
from discord.ext.commands import CogMeta as DPYCogMeta
from rscapi import Configuration as ApiConfig
from redbot.core import Config as RedConfig
from redbot.core.bot import Red

from zoneinfo import ZoneInfo

from rscapi.models.league import League
from rscapi.models.members_list200_response import MembersList200Response
from rscapi.models.season import Season
from rscapi.models.franchise import Franchise
from rscapi.models.member import Member
from rscapi.models.match import Match
from rscapi.models.player import Player
from rscapi.models.team import Team
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.team_list import TeamList
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.tracker_link_stats import TrackerLinkStats
from rscapi.models.tracker_link import TrackerLink

from rsc.enums import Status, TrackerLinksStatus

from typing import Dict, List, Optional, TYPE_CHECKING

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
    async def franchise_by_id(
        self,
        guild: discord.Guild,
        id: int
    ) -> Franchise | None:
        ...

    @abstractmethod
    async def franchise_logo(self, guild: discord.Guild, id: int) -> str | None:
        ...

    # League

    @abstractmethod
    async def leagues(self, guild: discord.Guild) -> list[League]:
        ...

    @abstractmethod
    async def league(self, guild: discord.Guild) -> League | None:
        ...

    @abstractmethod
    async def league_by_id(self, guild: discord.Guild) -> League | None:
        ...

    @abstractmethod
    async def current_season(self, guild: discord.Guild) -> Optional[Season]:
        ...

    @abstractmethod
    async def players(
        self,
        guild: discord.Guild,
        status: Optional[Status] = None,
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

    # Members

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
    ) -> list[Match]:
        ...

    @abstractmethod
    async def next_match(
        self,
        guild: discord.Guild,
        id: int,
    ) -> Optional[Match]:
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

    # Trackers

    @abstractmethod
    async def trackers(
        self,
        guild: discord.Guild,
        status: TrackerLinksStatus | None = None,
        player: discord.Member | int | None = None,
        name: str | None = None,
        limit: int=0,
        offset: int=0
    ) -> list[TrackerLink]:
        ...


class CompositeMetaClass(DPYCogMeta, ABCMeta):
    """
    This allows the metaclass used for proper type detection to
    coexist with discord.py's metaclass
    """

    pass
