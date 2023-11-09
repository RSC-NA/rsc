import discord
import logging
from pydantic import parse_obj_as

from redbot.core import app_commands, checks

from rscapi import ApiClient, LeaguesApi, SeasonsApi
from rscapi.models.league import League
from rscapi.models.season import Season

from rsc.abc import RSCMeta
from rsc.embeds import ErrorEmbed

from typing import List

log = logging.getLogger("red.rsc.leagues")


class LeagueMixIn(metaclass=RSCMeta):
    # App Commands

    @app_commands.command(name="leagues", description="Show all configured RSC leagues")
    @app_commands.guild_only()
    async def _leagues(self, interaction: discord.Interaction):
        leagues = await self.leagues(interaction.guild)

        embed = discord.Embed(title="RSC Leagues", color=discord.Color.blue())
        embed.add_field(
            name="League", value="\n".join(l.name for l in leagues), inline=True
        )
        embed.add_field(
            name="Game Mode",
            value="\n".join(l.league_data.game_mode for l in leagues),
            inline=True,
        )

        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="season", description="Display current RSC season for league"
    )
    @app_commands.guild_only()
    async def _season(self, interaction: discord.Interaction):
        season = await self.season(interaction.guild)
        log.debug(season)
        # TODO
        # embed = discord.Embed(
        #     title="RSC Leagues",
        #     color=discord.Color.blue()
        # )
        # embed.add_field(name="League", value="\n".join(l.name for l in leagues), inline=True)
        # embed.add_field(name="Game Mode", value="\n".join(l.league_data.game_mode for l in leagues), inline=True)

        # if interaction.guild.icon:
        #     embed.set_thumbnail(url=interaction.guild.icon.url)
        # await interaction.response.send_message(embed=embed)

    # Functionality

    async def leagues(self, guild: discord.Guild) -> List[League]:
        async with ApiClient(self._api_conf) as client:
            api = LeaguesApi(client)
            return await api.leagues_list()

    async def season(self, guild: discord.Guild) -> List[Season]:
        async with ApiClient(self._api_conf) as client:
            api = SeasonsApi(client)
            return await api.seasons_league_season(1)
