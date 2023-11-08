import discord
import logging

from pydantic import parse_obj_as
from redbot.core import app_commands, checks

from rscapi import ApiClient, FranchisesApi
from rscapi.models.franchise import Franchise
from rscapi.models.franchise_list import FranchiseList

from rsc.embeds import ErrorEmbed

from typing import List

log = logging.getLogger("red.rsc.numbers")


class FranchiseMixIn:

    @app_commands.command(name="franchises", description="Get a list of all RSC franchises")
    @app_commands.guild_only()
    async def _franchises(self, interaction: discord.Interaction):
        """Get a list of all RSC franchises"""
        franchises = await self.franchises()

        # Sort franchises
        franchises.sort(key=lambda x: x.name)

        embed = discord.Embed(
            title="Franchises",
            description=f"List of franchises in {interaction.guild}",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Franchise", value="\n".join(f.name for f in franchises), inline=True)
        embed.add_field(name="General Manager", value="\n".join(f.gm.rsc_name for f in franchises), inline=True)
        await interaction.response.send_message(embed=embed)


    # Functions

    async def franchises(self) -> List[FranchiseList]:
        async with ApiClient(self._api_conf) as client:
            api = FranchisesApi(client)
            return await api.franchises_list(league="1")
