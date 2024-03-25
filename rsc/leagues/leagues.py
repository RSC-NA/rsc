import logging

import discord
from redbot.core import app_commands
from rscapi import ApiClient, LeaguePlayersApi, LeaguesApi
from rscapi.exceptions import ApiException
from rscapi.models.league import League
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.season import Season

from rsc.abc import RSCMixIn
from rsc.embeds import BlueEmbed, ErrorEmbed, YellowEmbed
from rsc.enums import Status
from rsc.exceptions import RscException
from rsc.utils import utils

log = logging.getLogger("red.rsc.leagues")


class LeagueMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing LeagueMixIn")
        super().__init__()

    # Setup

    # Commands

    @app_commands.command(name="leagues", description="Show all RSC leagues")  # type: ignore
    @app_commands.guild_only
    async def _leagues(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        leagues = await self.leagues(guild)

        embed = discord.Embed(title="RSC Leagues", color=discord.Color.blue())
        embed.add_field(
            name="League",
            value="\n".join(league.name for league in leagues),
            inline=True,
        )
        embed.add_field(
            name="Game Mode",
            value="\n".join(
                league.league_data.game_mode or "None" for league in leagues
            ),
            inline=True,
        )

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(  # type: ignore
        name="leagueinfo", description="Show league and current season information"
    )
    @app_commands.guild_only
    async def _leagues_info(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        await utils.not_implemented(interaction)

        league_data = await self.current_season(interaction.guild)

        if not league_data:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Unable to fetch league data. Is the league configured correctly?"
                )
            )
            return

        # embed = discord.Embed(
        #     title=f"{league_data.league.name} League Information",
        # )
        # TODO - Is this useful?

    @app_commands.command(  # type: ignore
        name="season", description="Display current RSC season for league"
    )
    @app_commands.guild_only
    async def _season(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        season = await self.current_season(guild)
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
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="dates", description="Display important RSC dates")  # type: ignore
    @app_commands.guild_only
    async def _dates_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        dates = await self._get_dates(guild)
        if not dates:
            await interaction.response.send_message(
                embed=YellowEmbed(description="No league dates have been posted.")
            )
            return

        embed = BlueEmbed(title="Important League Dates", description=dates)

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        await interaction.response.send_message(embed=embed)

    # API

    async def leagues(self, guild: discord.Guild) -> list[League]:
        """Get a list of leagues from the API"""
        try:
            async with ApiClient(self._api_conf[guild.id]) as client:
                api = LeaguesApi(client)
                return await api.leagues_list()
        except ApiException as exc:
            raise RscException(exc)

    async def league(self, guild: discord.Guild) -> League | None:
        """Get data for the guilds configured league"""
        try:
            async with ApiClient(self._api_conf[guild.id]) as client:
                api = LeaguesApi(client)
                return await api.leagues_read(self._league[guild.id])
        except ApiException as exc:
            raise RscException(exc)

    async def league_by_id(self, guild: discord.Guild, id: int) -> League | None:
        """Fetch a league from the API by ID"""
        try:
            async with ApiClient(self._api_conf[guild.id]) as client:
                api = LeaguesApi(client)
                return await api.leagues_read(id)
        except ApiException as exc:
            raise RscException(exc)

    async def current_season(self, guild: discord.Guild) -> Season | None:
        """Get current season of league from API"""
        try:
            async with ApiClient(self._api_conf[guild.id]) as client:
                api = LeaguesApi(client)
                return await api.leagues_current_season(self._league[guild.id])
        except ApiException as exc:
            raise RscException(exc)

    async def league_seasons(self, guild: discord.Guild) -> list[Season]:
        """Get current season of league from API"""
        try:
            async with ApiClient(self._api_conf[guild.id]) as client:
                api = LeaguesApi(client)
                return await api.leagues_seasons(self._league[guild.id])
        except ApiException as exc:
            raise RscException(exc)

    async def players(
        self,
        guild: discord.Guild,
        status: Status | None = None,
        name: str | None = None,
        tier: int | None = None,
        tier_name: str | None = None,
        season: int | None = None,
        season_number: int | None = None,
        team_name: str | None = None,
        franchise: str | None = None,
        discord_id: int | None = None,
        limit: int = 0,
        offset: int = 0,
    ) -> list[LeaguePlayer]:
        try:
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
                    franchise=franchise,
                    discord_id=discord_id,
                    limit=limit,
                    offset=offset,
                )
                return players.results
        except ApiException as exc:
            raise RscException(exc)

    async def league_player_partial_update(
        self, guild: discord.Guild, id: int, lp: LeaguePlayer
    ) -> LeaguePlayer:
        """Partial update to league player in API"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = LeaguePlayersApi(client)
            log.debug(f"[ID={id}] League Player Partial Update: {lp}")
            try:
                return await api.league_players_partial_update(id, lp)
            except ApiException as exc:
                raise RscException(response=exc)
