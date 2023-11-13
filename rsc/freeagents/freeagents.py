import discord
import logging

from discord import VoiceState

from redbot.core import app_commands, checks, commands

from rscapi import ApiClient, LeaguePlayersApi
from rscapi.models.tier import Tier
from rscapi.models.league_player import LeaguePlayer

from rsc.abc import RSCMeta
from rsc.tiers import TierMixIn
from rsc.const import LEAGUE_ROLE, MUTED_ROLE
from rsc.embeds import ErrorEmbed, SuccessEmbed
from rsc.enums import Status
from rsc.utils.utils import get_role_by_name, get_member_from_rsc_name

from typing import List, Dict, Tuple, TypedDict

log = logging.getLogger("red.rsc.freeagents")

defaults_guild = {"CheckIns": {}}


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
    async def _free_agents(self, interaction: discord.Interaction, tier: str):
        free_agents = await self.free_agents(interaction.guild, tier)
        free_agents.extend(await self.permanent_free_agents(interaction.guild, tier))

        # Remove this shit. Damn it monty
        data: List[str] = []
        for fa in free_agents:
            fmember = await get_member_from_rsc_name(interaction.guild, fa.player.name)
            fstr = fmember.display_name if fmember else fa.player.name
            if fa.status == Status.PERM_FA:
                fstr += " (Permanent FA)"
            data.append(fstr)
        data = "\n".join(data)

        tier_role = await get_role_by_name(interaction.guild, tier)

        embed = discord.Embed(
            title=f"{tier} Free Agents",
            description=f"```\n{data}\n```",
            color=tier_role.color if tier else discord.Color.blue(),
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="checkin",
        description="Check in as an available free agent for the current match day",
    )
    @app_commands.guild_only()
    async def _fa_checkin(self, interaction: discord.Interaction):
        # Validate user is FA, change to a role check?
        member = await self.members(
            interaction.guild, discord_id=interaction.user.id, limit=1
        )
        log.debug(member)
        # Get Tier / Player Info
        # Check if it's a match day for that tier
        # Check in
        # TODO

    @app_commands.command(
        name="checkout",
        description="Check out as an available free agent for the current match day",
    )
    @app_commands.guild_only()
    async def _fa_checkout(self, interaction: discord.Interaction):
        pass

    @app_commands.command(
        name="availability",
        description="Get list of available free agents for specified tier",
    )
    @app_commands.autocomplete(tier=TierMixIn.tiers_autocomplete)
    @app_commands.guild_only()
    async def _fa_availability(self, interaction: discord.Interaction, tier: str):
        pass

    @app_commands.command(
        name="clearavailability",
        description="Clear free agent availability for a specified tier",
    )
    @app_commands.autocomplete(tier=TierMixIn.tiers_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def _clear_fa_availability(self, interaction: discord.Interaction, tier: str):
        pass

    @app_commands.command(
        name="clearallavailability",
        description="Clear free agent availability for all tiers",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def _clear_all_fa_availability(self, interaction: discord.Interaction):
        pass

    # API Calls

    async def free_agents(
        self, guild: discord.Guild, tier_name: str
    ) -> List[LeaguePlayer]:
        """Fetch a list of Free Agents for specified tier"""
        free_agents = await self.players(
            guild, status=Status.FREE_AGENT, tier_name=tier_name
        )
        return free_agents.results

    async def permanent_free_agents(
        self, guild: discord.Guild, tier_name: str
    ) -> List[LeaguePlayer]:
        """Fetch a list of Permanent Free Agents for specified tier"""
        free_agents = await self.players(
            guild, status=Status.PERM_FA, tier_name=tier_name
        )
        return free_agents.results
