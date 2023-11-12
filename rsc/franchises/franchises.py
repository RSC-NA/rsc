import discord
import logging

from pydantic import parse_obj_as
from redbot.core import app_commands, checks

from rscapi import ApiClient, FranchisesApi, TeamsApi
from rscapi.models.franchise import Franchise
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.team_list import TeamList

from rsc.abc import RSCMeta
from rsc.embeds import ErrorEmbed

from typing import List, Dict, Optional

log = logging.getLogger("red.rsc.franchises")


class FranchiseMixIn(metaclass=RSCMeta):
    def __init__(self):
        log.debug("Initializing FranchiseMixIn")
        self._franchise_cache: Dict[int, List[str]] = {}
        super().__init__()

    # Autocomplete

    async def franchise_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return []

        # Return nothing if cache does not exist.
        if not self._franchise_cache.get(interaction.guild_id):
            return []

        choices = []
        for f in self._franchise_cache[interaction.guild_id]:
            if current.lower() in f.lower():
                choices.append(app_commands.Choice(name=f, value=f))
        return choices

    # Commands

    @app_commands.command(
        name="franchises", description="Get a list of all RSC franchises"
    )
    @app_commands.guild_only()
    async def _franchises(self, interaction: discord.Interaction):
        """Get a list of all RSC franchises"""
        franchises = await self.franchises(interaction.guild)

        gm_names = []
        for f in franchises:
            member = interaction.guild.get_member(f.gm.discord_id)
            if member:
                gm_names.append(member.mention)
            else:
                gm_names.append(f.gm.rsc_name)

        embed = discord.Embed(
            title=f"{interaction.guild} Franchises",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Prefix", value="\n".join([f.prefix for f in franchises]), inline=True
        )
        embed.add_field(
            name="Franchise", value="\n".join([f.name for f in franchises]), inline=True
        )
        embed.add_field(
            name="General Manager",
            value="\n".join(gm_names),
            inline=True,
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        await interaction.response.send_message(embed=embed)

    # Functions

    async def franchises(
        self,
        guild: discord.Guild,
        prefix: Optional[str] = None,
        gm_name: Optional[str] = None,
        name: Optional[str] = None,
        tier: Optional[str] = None,
        tier_name: Optional[str] = None,
    ) -> List[FranchiseList]:
        async with ApiClient(self._api_conf[guild]) as client:
            api = FranchisesApi(client)
            franchises = await api.franchises_list(
                prefix=prefix,
                gm_name=gm_name,
                name=name,
                tier=tier,
                tier_name=tier_name,
                league=str(self._league[guild]),  # INT
            )

            # Populate cache
            if franchises:
                franchises.sort(key=lambda f: f.name)
                self._franchise_cache[guild.id] = [f.name for f in franchises]
            return franchises
