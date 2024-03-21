import logging
from datetime import datetime

import discord
from redbot.core import app_commands
from rscapi import ApiClient, MatchesApi
from rscapi.exceptions import ApiException
from rscapi.models.match import Match
from rscapi.models.match_list import MatchList
from rscapi.models.matches_list200_response import MatchesList200Response

from rsc.abc import RSCMixIn
from rsc.embeds import BlueEmbed, ErrorEmbed
from rsc.enums import MatchFormat, MatchTeamEnum, MatchType, Status
from rsc.teams import TeamMixIn
from rsc.utils.utils import tier_color_by_name

log = logging.getLogger("red.rsc.matches")


class MatchMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing MatchMixIn")
        super().__init__()

    # App Commands

    @app_commands.command(  # type: ignore
        name="schedule",
        description="Display your team or another teams entire schedule",
    )
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)  # type: ignore
    @app_commands.describe(
        team="Get the schedule for a specific team (Optional)",
        preseason="Include preseason matches (Default: False)",
    )
    @app_commands.guild_only
    async def _schedule_cmd(
        self,
        interaction: discord.Interaction,
        team: str | None = None,
        preseason: bool = False,
    ):
        guild = interaction.guild
        if not (guild and isinstance(interaction.user, discord.Member)):
            return
        await interaction.response.defer()

        team_id = 0
        tier = None
        if team:
            # If team name was supplied, find the ID of that team
            log.debug(f"Searching for team: {team}")
            team_id = await self.team_id_by_name(guild, name=team)
        else:
            log.debug(f"Finding team for {interaction.user.display_name}")
            # Find the team ID of interaction user
            player = await self.players(guild, discord_id=interaction.user.id, limit=1)
            if not player:
                await interaction.followup.send(
                    embed=ErrorEmbed(
                        description="You are not currently signed up for the league."
                    ),
                )
                return

            pdata = player[0]
            if pdata.status not in (Status.ROSTERED, Status.IR, Status.AGMIR):
                await interaction.followup.send(
                    embed=ErrorEmbed(
                        description="You are not currently rostered on a team."
                    ),
                )
                return

            if not (pdata.team and pdata.tier and pdata.team.id):
                await interaction.followup.send(
                    embed=ErrorEmbed(
                        description="Malformed data returned from API. Please submit a modmail."
                    ),
                )
                return

            team = pdata.team.name
            tier = pdata.tier.name
            team_id = pdata.team.id

        if not team_id:
            await interaction.followup.send(
                embed=ErrorEmbed(description=f"**{team}** is not a valid team name."),
            )
            return

        # Fetch team schedule
        log.debug(f"Fetching next match for team id: {team_id}")
        schedule = await self.season_matches(guild, team_id, preseason=preseason)

        # Get tier color
        if tier:
            tier_color = await tier_color_by_name(guild, tier)
        else:
            tier_color = discord.Color.blue()

        if not schedule:
            await interaction.followup.send(
                embed=discord.Embed(
                    title=f"{team} Schedule",
                    description=f"There are no matches currently scheduled for **{team}**",
                    color=tier_color or discord.Color.blue(),
                )
            )
            return

        # Sorting
        if preseason:
            title = f"{team} Preseason Schedule"
            matches = [s for s in schedule if s.match_type == MatchType.PRESEASON]
        else:
            title = f"{team} Schedule"
            matches = [s for s in schedule if s.match_type == MatchType.REGULAR]
            matches.extend(
                [s for s in schedule if s.match_type == MatchType.POSTSEASON]
            )
            matches.extend([s for s in schedule if s.match_type == MatchType.FINALS])

        embed = discord.Embed(
            title=title,
            description="Full schedule for the current season",
            color=tier_color or discord.Color.blue(),
        )

        embed.add_field(
            name="Day",
            value="\n".join([f"{m.day}" for m in matches]),
            inline=True,
        )
        embed.add_field(
            name="Home",
            value="\n".join([m.home_team.name for m in matches]),
            inline=True,
        )
        embed.add_field(
            name="Away",
            value="\n".join([m.away_team.name for m in matches]),
            inline=True,
        )

        await interaction.followup.send(embed=embed)

    @app_commands.command(  # type: ignore
        name="match",
        description="Get information about your upcoming match",
    )
    @app_commands.guild_only
    async def _match_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not (guild and isinstance(interaction.user, discord.Member)):
            return

        await interaction.response.defer(ephemeral=True)

        # Find the team ID of interaction user
        player = await self.players(guild, discord_id=interaction.user.id, limit=1)
        if not player:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description="You are not currently signed up for the league."
                ),
                ephemeral=True,
            )
            return
        if not (player[0].team and player[0].team.name):
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description="You are not currently rostered on a team."
                ),
                ephemeral=True,
            )
            return

        # Get API id of team
        team_id = await self.team_id_by_name(guild, name=player[0].team.name)

        # Get teams next match
        try:
            match = await self.next_match(guild, team_id)
        except ApiException as exc:
            log.debug(f"Match Return Status: {exc.status}")
            await interaction.followup.send(
                embed=BlueEmbed(
                    title="Match Info",
                    description="You do not have any upcoming matches.",
                ),
                ephemeral=True,
            )
            return

        if not match:
            await interaction.followup.send(
                embed=BlueEmbed(
                    title="Match Info",
                    description="You do not have any upcoming matches.",
                ),
                ephemeral=True,
            )
            return

        # Is interaction user away/home
        user_team = await self.match_team_by_user(match, interaction.user)

        embed = await self.build_match_embed(guild, match, user_team=user_team)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # Functions

    async def is_match_day(self, guild: discord.Guild) -> bool:
        season = await self.current_season(guild)
        if not season:
            return False
        if not season.season_tier_data:
            return False

        tz = await self.timezone(guild)
        today = datetime.now(tz).strftime("%A")
        if today in season.season_tier_data[0].schedule.match_nights:
            return True
        return False

    async def matches_from_match_list(self, match_list: list[MatchList]):
        pass

    async def match_team_by_user(
        self, match: Match, member: discord.Member
    ) -> MatchTeamEnum:
        """Determine if the user is on the home or away team"""
        for p in match.home_team.players:
            if p.discord_id == member.id:
                return MatchTeamEnum.HOME

        for p in match.away_team.players:
            if p.discord_id == member.id:
                return MatchTeamEnum.AWAY
        raise ValueError(f"{member.display_name} is not a valid player in this match")

    async def build_match_embed(
        self,
        guild: discord.Guild,
        match: Match,
        user_team: MatchTeamEnum | None = None,
    ) -> discord.Embed:
        """Build the match information embed"""
        # Get embed color by tier
        tier = match.home_team.tier
        tier_color = await tier_color_by_name(guild, tier)

        # Format match day
        if match.match_type == MatchType.PRESEASON:
            md = f"Preseason Match {match.day}"
        elif match.match_type == MatchType.PRESEASON:
            md = f"Match Day {match.day}"
        else:
            md = f"Post-season match {match.day}"

        # Format Date
        date_str = match.var_date.strftime("%B %-m, %Y")

        # Description
        desc = f"**{match.home_team.name}**\nversus\n**{match.away_team.name}**"

        # Lobby Info
        lobby_info = f"Name: **{match.game_name}**\nPass: **{match.game_pass}**"

        # Teams
        home_fmt, away_fmt = await self.roster_fmt_from_match(guild, match)

        # Create embed
        embed = discord.Embed(
            title=f"{md}: {date_str}", description=desc, color=tier_color
        )

        embed.add_field(name="Lobby Info", value=lobby_info, inline=False)
        embed.add_field(name="Home Team", value=home_fmt, inline=False)
        embed.add_field(name="Away Team", value=away_fmt, inline=False)

        # User Team for additional info
        additional_fmt = ""
        if user_team == MatchTeamEnum.HOME or user_team == MatchTeamEnum.AWAY:
            additional_fmt += (
                f"You are the **{user_team.name}** team."
                " You will join the room using the above information once the other team contacts you."
                " Do not begin joining a team until your entire team is ready to begin playing.\n\n"
            )
        additional_fmt += (
            "Be sure that **crossplay is enabled** and to save all replays and screenshots of the end-of-game scoreboard."
            " Do not leave the game until screenshots have been taken."
            " These must be uploaded to the"
            " [RSC Website](https://www.rocketsoccarconfederation.com/replay-and-screenshot-uploads)"
            " after the game is finished."
        )
        embed.add_field(name="Additional Info", value=additional_fmt, inline=False)
        return embed

    async def roster_fmt_from_match(
        self, guild: discord.Guild, match: Match
    ) -> tuple[str, str]:
        """Return formatted roster string from Match"""
        home_players: list[str] = []
        away_players: list[str] = []

        # Home
        for p in match.home_team.players:
            m = guild.get_member(p.discord_id)
            name = m.display_name if m else p.name
            if p.captain:
                home_players.append(f"{name} (C)")
            else:
                home_players.append(name)

        # Away
        for p in match.away_team.players:
            m = guild.get_member(p.discord_id)
            name = m.display_name if m else p.name
            if p.captain:
                away_players.append(f"{name} (C)")
            else:
                away_players.append(name)

        home_fmt = "```\n"
        home_fmt += f"{match.home_team.name} - {match.home_team.franchise} - {match.home_team.tier}\n"
        home_fmt += "\n".join([f"\t{p}" for p in home_players])
        home_fmt += "\n```"

        away_fmt = "```\n"
        away_fmt += f"{match.away_team.name} - {match.away_team.franchise} - {match.away_team.tier}\n"
        away_fmt += "\n".join([f"\t{p}" for p in away_players])
        away_fmt += "\n```"

        return (home_fmt, away_fmt)

    # Api

    async def matches(
        self,
        guild: discord.Guild,
        date__lt: datetime | None = None,
        date__gt: datetime | None = None,
        season: int | None = None,
        season_number: int | None = None,
        match_team_type: MatchTeamEnum = MatchTeamEnum.ALL,
        team_name: str | None = None,
        day: int | None = None,
        match_type: MatchType | None = None,
        match_format: MatchFormat | None = None,
        limit: int = 0,
        offset: int = 0,
        preseason: int = 0,
    ) -> list[MatchList]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MatchesApi(client)
            matches: MatchesList200Response = await api.matches_list(
                date__lt=date__lt.isoformat() if date__lt else None,
                date__gt=date__gt.isoformat() if date__gt else None,
                season=season,
                season_number=season_number,
                match_team_type=str(match_team_type),
                team_name=team_name,
                day=day,
                match_type=str(match_type) if match_type else None,
                match_format=str(match_format) if match_format else None,
                league=self._league[guild.id],
                limit=limit,
                offset=offset,
                preseason=preseason,
            )
            return matches.results

    async def find_match(
        self,
        guild: discord.Guild,
        teams: str,
        date__lt: datetime | None = None,
        date__gt: datetime | None = None,
        season: int | None = None,
        season_number: int | None = None,
        day: int | None = None,
        match_type: MatchType | None = None,
        match_format: MatchFormat | None = None,
        limit: int = 0,
        offset: int = 0,
        preseason: int = 0,
    ) -> list[Match]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MatchesApi(client)
            return await api.matches_find_match(
                teams=teams,
                date__lt=date__lt.isoformat() if date__lt else None,
                date__gt=date__gt.isoformat() if date__gt else None,
                season=season,
                season_number=season_number,
                day=day,
                match_type=str(match_type) if match_type else None,
                match_format=str(match_format) if match_format else None,
                league=self._league[guild.id],
                limit=limit,
                offset=offset,
                preseason=preseason,
            )

    async def match_by_id(self, guild: discord.Guild, id: int) -> Match:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MatchesApi(client)
            return await api.matches_read(id)
