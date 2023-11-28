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

from rsc.enums import Status

from typing import Dict, List, Optional


class RSCMixIn(ABC):
    """ABC class used for type hinting RSC Mix In modules"""

    bot: Red
    config: RedConfig

    _league: Dict[int, int]
    _api_conf: Dict[int, ApiConfig]

    _franchise_cache: Dict[int, List[str]]

    # Core

    @abstractmethod
    async def timezone(self, guild: discord.Guild) -> ZoneInfo:
        ...

    # Franchises

    @abstractmethod
    async def franchises(
        self,
        guild: discord.Guild,
        prefix: Optional[str] = None,
        gm_name: Optional[str] = None,
        name: Optional[str] = None,
        tier: Optional[str] = None,
        tier_name: Optional[str] = None,
    ) -> List[FranchiseList]:
        ...

    @abstractmethod
    async def franchise_by_id(
        self,
        guild: discord.Guild,
        id: int
    ) -> Optional[Franchise]:
        ...

    # League

    @abstractmethod
    async def leagues(self, guild: discord.Guild) -> List[League]:
        ...

    @abstractmethod
    async def league(self, guild: discord.Guild) -> Optional[League]:
        ...

    @abstractmethod
    async def league_by_id(self, guild: discord.Guild) -> Optional[League]:
        ...

    @abstractmethod
    async def current_season(self, guild: discord.Guild) -> Optional[Season]:
        ...

    @abstractmethod
    async def players(
        self,
        guild: discord.Guild,
        status: Optional[Status] = None,
        name: Optional[str] = None,
        tier: Optional[int] = None,
        tier_name: Optional[str] = None,
        season: Optional[int] = None,
        season_number: Optional[int] = None,
        team_name: Optional[str] = None,
        franchise: Optional[str] = None,
        discord_id: Optional[int] = None,
        limit: int = 0,
        offset: int = 0,
    ) -> List[LeaguePlayer]:
        ...

    # Members

    @abstractmethod
    async def members(
        self,
        guild: discord.Guild,
        rsc_name: Optional[str] = None,
        discord_username: Optional[str] = None,
        discord_id: Optional[int] = None,
        limit: int = 0,
        offset: int = 0,
    ) -> List[Member]:
        ...

    # Teams

    @abstractmethod
    async def teams(
        self,
        guild: discord.Guild,
        seasons: Optional[str] = None,
        franchise: Optional[str] = None,
        name: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> List[TeamList]:
        ...

    @abstractmethod
    async def season_matches(
        self,
        guild: discord.Guild,
        id: int,
        season: Optional[int] = None,
        preseason: bool = True,
    ) -> List[Match]:
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
    ) -> List[Player]:
        ...


class CompositeMetaClass(DPYCogMeta, ABCMeta):
    """
    This allows the metaclass used for proper type detection to
    coexist with discord.py's metaclass
    """

    pass
