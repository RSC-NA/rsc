"""RSC Protocol definitions for type checking across mixins.

This module provides Protocol classes that define the interfaces
for cross-mixin communication without creating circular dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypeVar

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    import discord
    from aiohttp.web_runner import AppRunner, TCPSite
    from redbot.core import Config as RedConfig
    from redbot.core.bot import Red

    from rscapi import Configuration as ApiConfig

from rsc.admin.protocol import AdminProtocol
from rsc.combines.protocol import CombineProtocol
from rsc.franchises.protocol import FranchiseProtocol
from rsc.freeagents.protocol import FreeAgentProtocol
from rsc.leagues.protocol import LeagueProtocol
from rsc.matches.protocol import MatchProtocol
from rsc.members.protocol import MemberProtocol
from rsc.seasons.protocol import SeasonProtocol
from rsc.teams.protocol import TeamProtocol
from rsc.tiers.protocol import TierProtocol
from rsc.trackers.protocol import TrackerProtocol
from rsc.transactions.protocol import TransactionProtocol


class RSCBaseProtocol(Protocol):
    """Base protocol defining shared attributes across all RSC mixins."""

    bot: Red
    config: RedConfig

    _league: dict[int, int]
    _api_conf: dict[int, ApiConfig]

    _franchise_cache: dict[int, list[str]]
    _team_cache: dict[int, list[str]]
    _tier_cache: dict[int, list[str]]

    _web_runner: AppRunner
    _web_site: TCPSite

    # Core methods from RSC class
    async def timezone(self, guild: discord.Guild) -> ZoneInfo:
        """Get the timezone configured for a guild."""
        ...

    async def _get_welcome_roles(self, guild: discord.Guild) -> list[discord.Role]: ...

    async def _get_api_url(self, guild: discord.Guild) -> str | None: ...


# Combined protocol that includes all mixin capabilities
class RSCProtocol(
    RSCBaseProtocol,
    AdminProtocol,
    CombineProtocol,
    FranchiseProtocol,
    FreeAgentProtocol,
    LeagueProtocol,
    MatchProtocol,
    MemberProtocol,
    SeasonProtocol,
    TeamProtocol,
    TierProtocol,
    TrackerProtocol,
    TransactionProtocol,
    Protocol,
):
    """Combined protocol representing the full RSC capability.

    This protocol is used for type hints when a mixin needs to call
    methods from other mixins. Individual mixin protocols are combined
    here to provide complete type information.

    Usage in mixins:
        from typing import TYPE_CHECKING, cast
        if TYPE_CHECKING:
            from rsc.protocols import RSCProtocol

        class MyMixIn:
            async def my_method(self, guild: discord.Guild):
                # When calling methods from other mixins:
                self_typed = cast("RSCProtocol", self)
                players = await self_typed.players(guild)
    """


# TypeVar bound to RSCProtocol for generic functions
RSC_T = TypeVar("RSC_T", bound="RSCProtocol")
