import discord
import logging


from redbot.core import app_commands, checks, commands

from rscapi import ApiClient, MembersApi
from rscapi.models.tier import Tier

from rsc.abc import RSCMeta
from rsc.tiers import TierMixIn
from rsc.const import LEAGUE_ROLE, MUTED_ROLE
from rsc.embeds import ErrorEmbed, SuccessEmbed
from rsc.enums import Status

from typing import List, Dict, Tuple, TypedDict, Optional

log = logging.getLogger("red.rsc.freeagents")

defaults_guild = {"CheckIns": {}}


class MemberMixIn(metaclass=RSCMeta):
    # API

    async def members(
        self,
        guild: discord.Guild,
        rsc_name: Optional[str] = None,
        discord_username: Optional[str] = None,
        limit: int = 0,
        offset: int = 0,
    ):
        async with ApiClient(self._api_conf[guild]) as client:
            api = MembersApi(client)
            members = await api.members_list(
                rsc_name=rsc_name,
                discord_username=discord_username,
                limit=limit,
                offset=offset,
            )
            log.debug(members)
            #TODO
