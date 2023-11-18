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
from rscapi.models.franchise_list import FranchiseList

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
    ) -> MembersList200Response:
        ...


class CompositeMetaClass(DPYCogMeta, ABCMeta):
    """
    This allows the metaclass used for proper type detection to
    coexist with discord.py's metaclass
    """

    pass
