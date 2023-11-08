import discord
import logging

from redbot.core import app_commands, checks

from rscapi import ApiClient, NumbersApi

from rsc.embeds import ErrorEmbed

from typing import Optional

log = logging.getLogger("red.rsc.numbers")


class TeamMixIn:
    pass

    # @app_commands.command(name="mmr", description="Fetch mmr for a specific RSC player")
    # @app_commands.guild_only()
    # async def fetchmmr(self, interaction: discord.Interaction, player: discord.Member):
    #     """Fetch mmr for a specific RSC player"""

    #     log.debug(f"Getting MMR for {player.id}")
    #     async with ApiClient(self._api_conf) as client:
    #         numbers = NumbersApi(client)

    #         resp = await numbers.numbers_mmr_read(player.id)
    #         log.debug(f"Response: {resp}")
    #         await interaction.response.send_message(embed=discord.Embed(
    #             title=f"{player.display_name} MMR",
    #             description=resp,
    #             color=discord.Color.green()
    #         ))
