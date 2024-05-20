import logging

import discord
from redbot.core import app_commands
from rscapi.models.player_season_stats import PlayerSeasonStats
from rscapi.models.team_season_stats import TeamSeasonStats

from rsc.abc import RSCMixIn
from rsc.embeds import ApiExceptionErrorEmbed, BlueEmbed, ErrorEmbed, YellowEmbed
from rsc.exceptions import RscException
from rsc.teams import TeamMixIn
from rsc.tiers import TierMixIn
from rsc.utils import utils

log = logging.getLogger("red.rsc.stats")


class StatsMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing StatsMixIn")
        super().__init__()

    # Groups

    _standings_group = app_commands.Group(
        name="standings",
        description="Display standings across the league",
        guild_only=True,
    )

    # App Commands

    @_standings_group.command(  # type: ignore
        name="franchise", description="Display franchise standings for season"
    )
    async def _franchise_standings_cmd(
        self, interaction: discord.Interaction, season: int | None = None
    ):
        guild = interaction.guild
        if not guild:
            return
        await interaction.response.defer(ephemeral=False)

        # fetch season data
        if not season:
            log.debug("No season specified, fetching current season.")
            sdata = await self.current_season(guild)
        else:
            log.debug(f"Getting season information for S{season}")
            slist = await self.league_seasons(guild)
            sdata = next((x for x in slist if x.number == season), None)

        log.debug(sdata)
        if not sdata:
            await interaction.followup.send(
                embed=ErrorEmbed(description=f"Invalid season provided: `{season}`")
            )
            return

        if not sdata.id:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API did not return a season ID. Please submit a modmail."
                )
            )
            return

        season = sdata.number
        season_id = sdata.id

        standings = await self.franchise_standings(guild, season_id=season_id)
        # standings = await self.franchise_standings(guild, season_id=1)  # REMOVE ME

        if not standings:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"No franchise standings returned for `S{season}`"
                )
            )
            return

        standings.sort(key=lambda x: x.franchise_standings_rank)

        embed = BlueEmbed(
            title=f"S{season} Franchise Standings",
            description="Displaying overall franchise standings.",
        )

        embed.add_field(
            name="Rank",
            value="\n".join([str(x.franchise_standings_rank) for x in standings]),
            inline=True,
        )
        embed.add_field(
            name="Franchise",
            value="\n".join([x.franchise for x in standings]),
            inline=True,
        )
        embed.add_field(
            name="Win Percent",
            value="\n".join([f"{x.win_percentage:.2%}" for x in standings]),
            inline=True,
        )

        await interaction.followup.send(embed=embed, ephemeral=False)

    @_standings_group.command(  # type: ignore
        name="tier", description="Display tier standings for season"
    )
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)  # type: ignore
    async def _tier_standings_cmd(
        self, interaction: discord.Interaction, tier: str, season: int | None = None
    ):
        tier = tier.capitalize()
        await utils.not_implemented(interaction)

    @app_commands.command(  # type: ignore
        name="playerstats", description="Display RSC stats for a player"
    )
    @app_commands.describe(player="RSC Discord Member")
    @app_commands.guild_only
    async def _player_stats_cmd(
        self,
        interaction: discord.Interaction,
        player: discord.Member | None = None,
        season: int | None = None,
        postseason: bool = False,
    ):
        guild = interaction.guild
        if not guild:
            return

        if not isinstance(interaction.user, discord.Member):
            return

        if not player:
            player = interaction.user

        await interaction.response.defer()

        try:
            stats = await self.player_stats(
                guild, player, season=season, postseason=postseason
            )
        except RscException as exc:
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc))
            return

        if not stats:
            await interaction.followup.send(
                embed=YellowEmbed(
                    title=f"{player.display_name} Stats",
                    description="No stats found for specified criteria.",
                )
            )
            return

        embed = await self.create_stats_embed(stats=stats, postseason=postseason)

        if player.avatar:
            embed.set_thumbnail(url=player.avatar.url)
        elif guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        await interaction.followup.send(embed=embed)

    @app_commands.command(  # type: ignore
        name="teamstats", description="Display RSC stats for an RSC team"
    )
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)  # type: ignore
    @app_commands.guild_only
    async def _team_stats_cmd(
        self,
        interaction: discord.Interaction,
        team: str,
        postseason: bool = False,
        season: int | None = None,
    ):
        guild = interaction.guild
        if not guild:
            return
        await interaction.response.defer()

        tlist = await self.teams(guild=guild, name=team)

        if not tlist:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"No team found with the name: `{team}`")
            )

        if len(tlist) > 1:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"Found multiple teams matching: `{team}`")
            )

        team_data = tlist.pop(0)

        if not team_data.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API returned a team with no ID. Please submit a modmail."
                )
            )

        team_id = team_data.id
        team_tier = None
        if team_tier:
            team_tier = team_data.tier.name

        try:
            team_stats = await self.team_stats(guild, team_id=team_id, season=season)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc))

        if not team_stats:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"No stats found for team: `{team}`")
            )

        embed = await self.create_stats_embed(stats=team_stats, postseason=postseason)

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        await interaction.followup.send(embed=embed)

    async def create_stats_embed(
        self,
        stats: PlayerSeasonStats | TeamSeasonStats,
        postseason: bool = False,
        thumbnail_url: str | None = None,
    ) -> discord.Embed:
        # Fix this when season is added to team stats serializer
        if isinstance(stats, TeamSeasonStats):
            desc = "Displaying team stats for current season"
        else:
            if postseason:
                desc = f"Displaying post season stats for RSC S{stats.season}"
            else:
                desc = f"Displaying regular season stats for RSC S{stats.season}"

        # Additional stats
        goals = stats.goals or 0
        points = stats.points or 0
        games_played = stats.games_played or 0

        if games_played:
            goals_per_game = goals / games_played
            points_per_game = points / games_played
        else:
            goals_per_game = 0
            points_per_game = 0

        if isinstance(stats, TeamSeasonStats):
            embed = BlueEmbed(title=f"{stats.team} Team Stats", description=desc)
        else:
            embed = BlueEmbed(title=f"{stats.player} Player Stats", description=desc)

        embed.add_field(name="Played", value=str(games_played), inline=True)
        embed.add_field(name="Wins", value=str(stats.games_won), inline=True)
        embed.add_field(name="Loss", value=str(stats.games_lost), inline=True)

        embed.add_field(name="", value="", inline=False)

        embed.add_field(name="Goals", value=str(stats.goals), inline=True)
        embed.add_field(name="Saves", value=str(stats.saves), inline=True)
        embed.add_field(name="Assists", value=str(stats.assists), inline=True)

        embed.add_field(name="", value="", inline=False)

        embed.add_field(name="GPG", value=f"{goals_per_game:.2f}")
        embed.add_field(name="Shots", value=str(stats.shots), inline=True)
        embed.add_field(
            name="Shot Percentage",
            value=f"{stats.shooting_percentage:.1%}",
            inline=True,
        )

        embed.add_field(name="", value="", inline=False)

        if isinstance(stats, PlayerSeasonStats):
            embed.add_field(name="MVPs", value=str(stats.mvps), inline=True)
            embed.add_field(name="Points", value=str(points), inline=True)
            embed.add_field(name="PPG", value=f"{points_per_game:.2f}", inline=True)
            embed.add_field(
                name="Avg Speed", value=f"{stats.avg_speed:.2f}", inline=True
            )
        else:
            embed.add_field(name="Points", value=str(points), inline=True)
            embed.add_field(name="PPG", value=f"{points_per_game:.2f}", inline=True)
            embed.add_field(name="Demos", value=f"{stats.demos_inflicted}")
            embed.add_field(name="", value="", inline=False)
            embed.add_field(
                name="Goal Differential",
                value=str(stats.goal_differential),
                inline=True,
            )

        return embed
