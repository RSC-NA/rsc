import discord
import logging

from discord import VoiceState

from redbot.core import app_commands, checks, commands

from rscapi import ApiClient, LeaguePlayersApi
from rscapi.models.tier import Tier

from rsc.abc import RSCMeta
from rsc.tiers import TierMixIn
from rsc.const import LEAGUE_ROLE, MUTED_ROLE
from rsc.embeds import ErrorEmbed, SuccessEmbed

from typing import List, Dict, Tuple, TypedDict

log = logging.getLogger("red.rsc.freeagents")

defaults_guild = {
    "CheckIns": {}
}

class CheckIn(TypedDict):
    match_day: int
    tier: str
    player: int



class FreeAgentMixIn(metaclass=RSCMeta):

    def __init__(self):
        log.debug("Initializing FreeAgentMixIn")

        self._check_ins: Dict[discord.Guild, List[int]] = {}

        self.config.init_custom("FreeAgents", 1)
        self.config.register_custom("FreeAgents", **defaults_guild)
        super().__init__()

    # Commands

    @app_commands.command(name="fa", description="List free agents in a specified tier")
    @app_commands.autocomplete(tier=TierMixIn.tiers_autocomplete)
    @app_commands.guild_only()
    async def _fa(self, interaction: discord.Interaction, tier: str):
        free_agents = await self.free_agents(interaction.guild, tier)


    # API Calls

    async def free_agents(self, guild: discord.Guild, tier: str):
        """Fetch a list of Free Agents for specified tier"""
        async with ApiClient(self._api_conf[guild]) as client:
            api = LeaguePlayersApi(client)
            players = await api.league_players_list(status="FA", tier_name=tier)
            log.debug(players)
