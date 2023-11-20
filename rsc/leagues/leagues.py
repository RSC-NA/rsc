import discord
import logging
from pydantic import parse_obj_as

from redbot.core import app_commands

from rscapi import ApiClient, LeaguesApi, SeasonsApi, LeaguePlayersApi, Configuration
from rscapi.models.league import League
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.league_players_list200_response import LeaguePlayersList200Response
from rscapi.models.season import Season

from rsc.abc import RSCMixIn
from rsc.enums import Status
from rsc.embeds import ErrorEmbed, BlueEmbed

from typing import List, Optional, Dict

log = logging.getLogger("red.rsc.leagues")


class LeagueMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing LeagueMixIn")
        super().__init__()
        # self._match_days: Dict[discord.Guild, List[str]] = []

    # Setup

    # Commands

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
        name="leagueinfo", description="Show league and current season information"
    )
    @app_commands.guild_only()
    async def _leagues_info(self, interaction: discord.Interaction):
        league_data = await self.current_season()

        if not league_data:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Unable to fetch league data. Is the league configured correctly?"
                )
            )
            return

        embed = discord.Embed(
            title=f"{league_data.league.name} League Information",
        )
        # TODO - Is this useful?

    @app_commands.command(
        name="season", description="Display current RSC season for league"
    )
    @app_commands.guild_only()
    async def _season(self, interaction: discord.Interaction):
        season = await self.current_season(interaction.guild)
        if not season:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    title="Current Season",
                    description="Currently there is not an ongoing season in the league.",
                ),
                ephemeral=True,
            )
            return
        embed = BlueEmbed(
            title="Current Season",
            description=f"The current season is **S{season.number}**",
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        await interaction.response.send_message(embed=embed)

    # Functionality

    async def leagues(self, guild: discord.Guild) -> List[League]:
        """Get a list of leagues from the API"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = LeaguesApi(client)
            return await api.leagues_list()

    async def league(self, guild: discord.Guild) -> Optional[League]:
        """Get data for the guilds configured league"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = LeaguesApi(client)
            return await api.leagues_read(self._league[guild.id])

    async def league_by_id(self, guild: discord.Guild, id: int) -> Optional[League]:
        """Fetch a league from the API by ID"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = LeaguesApi(client)
            return await api.leagues_read(id)

    async def current_season(self, guild: discord.Guild) -> Optional[Season]:
        """Get current season of league from API"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = LeaguesApi(client)
            return await api.leagues_current_season(self._league[guild.id])

    # async def season_by_number(self, guild: discord.Guild) -> List[Season]:
    #     async with ApiClient(self._api_conf[guild.id]) as client:
    #         api = SeasonsApi(client)
    #         return await api.seasons_league_season(1)

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
        discord_id: Optional[int] = None,
        limit: int = 0,
        offset: int = 0,
    ) -> List[LeaguePlayer]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = LeaguePlayersApi(client)
            players = await api.league_players_list(
                status=str(status) if status else None,
                name=name,
                tier=tier,
                tier_name=tier_name,
                season=season,
                season_number=season_number,
                league=self._league[guild.id],
                team_name=team_name,
                discord_id=discord_id,
                limit=limit,
                offset=offset,
            )
            return players.results
