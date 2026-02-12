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

    @_standings_group.command(  # type: ignore[type-var]
        name="franchise", description="Display franchise standings for season"
    )
    async def _franchise_standings_cmd(self, interaction: discord.Interaction, season: int | None = None):
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
            slist = await self.seasons(guild, number=season)
            if not slist:
                await interaction.followup.send(embed=ErrorEmbed(description=f"No season data found for S{season}"))
                return
            sdata = slist.pop(0)

        log.debug(sdata)
        if not sdata:
            await interaction.followup.send(embed=ErrorEmbed(description=f"Invalid season provided: `{season}`"))
            return

        if not sdata.id:
            await interaction.followup.send(embed=ErrorEmbed(description="API did not return a season ID. Please submit a modmail."))
            return

        season = sdata.number
        season_id = sdata.id

        standings = await self.franchise_standings(guild, season_id=season_id)
        # standings = await self.franchise_standings(guild, season_id=1)  # REMOVE ME

        if not standings:
            await interaction.followup.send(embed=ErrorEmbed(description=f"No franchise standings returned for `S{season}`"))
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
            name="Record",
            value="\n".join([f"{x.wins} - {x.losses}" for x in standings]),
            inline=True,
        )

        await interaction.followup.send(embed=embed, ephemeral=False)

    @_standings_group.command(  # type: ignore[type-var]
        name="tier", description="Display tier standings for season"
    )
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)  # type: ignore[type-var]
    async def _tier_standings_cmd(self, interaction: discord.Interaction, tier: str, season: int | None = None):
        guild = interaction.guild
        if not guild:
            return
        await interaction.response.defer(ephemeral=False)

        tier_data = await self.tiers(guild, name=tier)
        if not tier_data:
            await interaction.followup.send(embed=ErrorEmbed(description=f"No tier found with the name: `{tier}`"))
            return

        if len(tier_data) > 1:
            await interaction.followup.send(embed=ErrorEmbed(description=f"Found multiple tiers matching: `{tier}`"))
            return

        tier_info = tier_data.pop(0)

        if not tier_info.id:
            await interaction.followup.send(embed=ErrorEmbed(description="API returned a tier with no ID. Please submit a modmail."))
            return

        if not season:
            current_season = await self.current_season(guild)
            if not current_season:
                await interaction.followup.send(
                    embed=ErrorEmbed(description="Could not determine current season. Please specify a season number.")
                )
                return
            season = current_season.number

        tier_id = tier_info.id

        standings = await self.tier_standings(guild, tier_id=tier_id, season=season)

        if not standings:
            await interaction.followup.send(embed=ErrorEmbed(description=f"No tier standings returned for `{tier}` in S{season}"))
            return

        embed = BlueEmbed(
            title=f"S{season} {tier} Standings",
            description=f"Displaying standings for {tier} tier.",
        )

        embed.add_field(
            name="Rank",
            value="\n".join([str(x.rank) for x in standings]),
            inline=True,
        )
        embed.add_field(
            name="Team",
            value="\n".join([x.team for x in standings]),
            inline=True,
        )
        embed.add_field(
            name="Record",
            value="\n".join([f"{x.games_won} - {x.games_lost}" for x in standings]),
            inline=True,
        )

        await interaction.followup.send(embed=embed, ephemeral=False)

    @app_commands.command(  # type: ignore[type-var]
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
            stats = await self.player_stats(guild, player, season=season, postseason=postseason)
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

    @app_commands.command(  # type: ignore[type-var]
        name="teamstats", description="Display RSC stats for an RSC team"
    )
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)  # type: ignore[type-var]
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
            return await interaction.followup.send(embed=ErrorEmbed(description=f"No team found with the name: `{team}`"))

        if len(tlist) > 1:
            return await interaction.followup.send(embed=ErrorEmbed(description=f"Found multiple teams matching: `{team}`"))

        team_data = tlist.pop(0)

        if not team_data.id:
            return await interaction.followup.send(embed=ErrorEmbed(description="API returned a team with no ID. Please submit a modmail."))

        team_id = team_data.id
        team_tier = None
        if team_tier:
            team_tier = team_data.tier.name

        try:
            team_stats = await self.team_stats(guild, team_id=team_id, season=season)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc))

        if not team_stats:
            return await interaction.followup.send(embed=ErrorEmbed(description=f"No stats found for team: `{team}`"))

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
        elif postseason:
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
            value=f"{stats.shooting_percentage:>.2f}%",
            inline=True,
        )

        embed.add_field(name="", value="", inline=False)

        if isinstance(stats, PlayerSeasonStats):
            embed.add_field(name="MVPs", value=str(stats.mvps), inline=True)
            embed.add_field(name="Points", value=str(points), inline=True)
            embed.add_field(name="PPG", value=f"{points_per_game:.2f}", inline=True)
            embed.add_field(name="Avg Speed", value=f"{stats.avg_speed:.2f}", inline=True)
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
