import logging
from datetime import datetime
from typing import TYPE_CHECKING

import discord
from redbot.core import app_commands
from rscapi import ApiClient, MatchesApi
from rscapi.exceptions import ApiException
from rscapi.models.match import Match
from rscapi.models.match_list import MatchList
from rscapi.models.match_results import MatchResults
from rscapi.models.match_score_report import MatchScoreReport
from rscapi.models.match_submission import MatchSubmission

from rsc.abc import RSCMixIn
from rsc.embeds import BlueEmbed, ErrorEmbed, ExceptionErrorEmbed, YellowEmbed
from rsc.enums import (
    MatchFormat,
    MatchTeamEnum,
    MatchType,
    PostSeasonType,
    Status,
    SubStatus,
)
from rsc.exceptions import RscException
from rsc.logs import GuildLogAdapter
from rsc.teams import TeamMixIn
from rsc.utils import utils
from rsc.utils.utils import tier_color_by_name

if TYPE_CHECKING:
    from rscapi.models.matches_list200_response import MatchesList200Response

logger = logging.getLogger("red.rsc.matches")
log = GuildLogAdapter(logger)


class MatchMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing MatchMixIn")
        super().__init__()

    # App Commands

    @app_commands.command(  # type: ignore[type-var]
        name="schedule",
        description="Display your team or another teams entire schedule",
    )
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)  # type: ignore[type-var]
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
            try:
                team_id = await self.team_id_by_name(guild, name=team)
            except ValueError as exc:
                return await interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(exc)), ephemeral=True)
        else:
            log.debug(f"Finding team for {interaction.user.display_name}")
            # Find the team ID of interaction user
            player = await self.players(guild, discord_id=interaction.user.id, limit=1)
            if not player:
                await interaction.followup.send(
                    embed=ErrorEmbed(description="You are not currently signed up for the league."),
                )
                return

            pdata = player[0]
            if pdata.status not in (
                Status.ROSTERED,
                Status.IR,
                Status.AGMIR,
                Status.RENEWED,
            ):
                return await interaction.followup.send(
                    embed=ErrorEmbed(description="You are not currently rostered on a team."),
                )

            if not (pdata.team and pdata.tier and pdata.team.id):
                return await interaction.followup.send(
                    embed=ErrorEmbed(description="Malformed data returned from API. Please submit a modmail."),
                )

            team = pdata.team.name
            tier = pdata.tier.name
            team_id = pdata.team.id

        if not team_id:
            await interaction.followup.send(
                embed=ErrorEmbed(description=f"**{team}** is not a valid team name."),
            )
            return

        # Fetch team schedule
        log.debug(f"Fetching matches for team id: {team_id}")
        schedule = await self.season_matches(guild, team_id, preseason=preseason)

        if not schedule:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title=f"{team} Schedule",
                    description=f"There are no matches currently scheduled for **{team}**",
                )
            )

        # Get tier color
        if tier:
            tier_color = await tier_color_by_name(guild, tier)
        else:
            tier_color = await tier_color_by_name(guild, schedule[0].home_team.tier)

        # Sorting
        if preseason:
            title = f"{team} Preseason Schedule"
            matches = [s for s in schedule if s.match_type == MatchType.PRESEASON]
        else:
            title = f"{team} Schedule"
            matches = [s for s in schedule if s.match_type == MatchType.REGULAR]
            matches.extend([s for s in schedule if s.match_type == MatchType.POSTSEASON])
            matches.extend([s for s in schedule if s.match_type == MatchType.FINALS])

        if not (all(m.home_team.name for m in matches) and all(m.away_team.name for m in matches)):
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Schedule data has a missing home or away team name. Please open a modmail ticket.")
            )

        embed = discord.Embed(
            title=title,
            description="Full schedule for the current season",
            color=tier_color or discord.Color.blue(),
        )

        embed.add_field(
            name="Date",
            value="\n".join([f"{m.var_date.strftime('%-m/%-d')}" for m in matches if m.var_date]),
            inline=True,
        )
        embed.add_field(
            name="Home",
            value="\n".join([str(m.home_team.name) for m in matches]),
            inline=True,
        )
        embed.add_field(
            name="Away",
            value="\n".join([str(m.away_team.name) for m in matches]),
            inline=True,
        )

        await interaction.followup.send(embed=embed)

    @app_commands.command(  # type: ignore[type-var]
        name="match",
        description="Get information about your upcoming match",
    )
    @app_commands.describe(team="Get match information for a specific team (General Manager Only)")
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)  # type: ignore[type-var]
    @app_commands.guild_only
    async def _match_cmd(self, interaction: discord.Interaction, team: str | None = None):
        guild = interaction.guild
        if not (guild and isinstance(interaction.user, discord.Member)):
            return

        await interaction.response.defer(ephemeral=True)

        # Find the team ID of interaction user
        if team:
            # Get API id of team
            try:
                team_id = await self.team_id_by_name(guild, name=team)
            except ValueError as exc:
                return await interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(exc)), ephemeral=True)
        else:
            player = await self.players(guild, discord_id=interaction.user.id, limit=1)
            if not player:
                await interaction.followup.send(
                    embed=ErrorEmbed(description="You are not currently signed up for the league."),
                    ephemeral=True,
                )
                return
            if not (player[0].team and player[0].team.name):
                await interaction.followup.send(
                    embed=ErrorEmbed(description="You are not currently rostered on a team."),
                    ephemeral=True,
                )
                return

            # Get API id of team
            try:
                if team:
                    log.debug(f"Getting Team ID: {team}")
                    team_id = await self.team_id_by_name(guild, name=team)
                else:
                    log.debug(f"Getting Team ID: {player[0].team.name}")
                    team_id = await self.team_id_by_name(guild, name=player[0].team.name)
            except ValueError as exc:
                return await interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(exc)), ephemeral=True)

        # Get teams next match
        try:
            log.debug(f"Getting match for team: {team_id}", guild=guild)
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
            return await interaction.followup.send(
                embed=BlueEmbed(
                    title="Match Info",
                    description="You do not have any upcoming matches.",
                ),
                ephemeral=True,
            )

        # If team was specified, user must be GM or admin
        if team and not (
            await self.is_match_franchise_gm(member=interaction.user, match=match)
            or await self.is_match_franchise_agm(member=interaction.user, match=match)
            or interaction.user.guild_permissions.manage_guild
        ):
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=(
                        "Only general managers can specify a team for match information. "
                        "If you are not a GM, please simply run `/match` to get your teams match information."
                    )
                )
            )

        # Is interaction user away/home
        try:
            user_team = await self.match_team_by_user(match, interaction.user)
            embed = await self.build_match_embed(guild, match, user_team=user_team, with_gm=True)
        except ValueError as exc:
            return await interaction.followup.send(embed=ExceptionErrorEmbed(str(exc)))
        await interaction.followup.send(embed=embed, ephemeral=True)

    # Functions

    async def discord_member_in_match(self, member: discord.Member, match: Match) -> bool:
        if not (match.home_team.players and match.away_team.players):
            return False

        for hplayer in match.home_team.players:
            if member.id == hplayer.discord_id:
                return True

        for aplayer in match.away_team.players:  # noqa: SIM110
            if member.id == aplayer.discord_id:
                return True
        return False

    @staticmethod
    async def get_match_from_list(home: str, away: str, matches: list[Match]) -> Match | None:
        match = None
        for m in matches:
            if not (m.home_team.name and m.away_team.name):
                continue

            log.debug(f"Match List Data: {m.home_team.name} v {m.away_team.name}")
            if home.lower() in (
                m.home_team.name.lower(),
                m.away_team.name.lower(),
            ) and away.lower() in (
                m.home_team.name.lower(),
                m.away_team.name.lower(),
            ):
                match = m
        return match

    async def is_match_day(self, guild: discord.Guild) -> bool:
        season = await self.current_season(guild)
        if not season:
            return False
        if not season.season_tier_data:
            return False

        tz = await self.timezone(guild)
        today = datetime.now(tz).strftime("%A")

        if not season.season_tier_data[0].schedule:
            raise AttributeError("Season does not have any match nights configured.")

        return today in season.season_tier_data[0].schedule.match_nights

    async def matches_from_match_list(self, match_list: list[MatchList]):
        pass

    async def match_team_by_user(self, match: Match, member: discord.Member) -> MatchTeamEnum:
        """Determine if the user is on the home or away team"""
        # Check if GM of team
        if match.home_team.gm.discord_id == member.id:
            return MatchTeamEnum.HOME

        if match.away_team.gm.discord_id == member.id:
            return MatchTeamEnum.AWAY

        # Iterate players for member ID match
        if match.home_team.players:
            for p in match.home_team.players:
                if p.discord_id == member.id:
                    return MatchTeamEnum.HOME

        if match.away_team.players:
            for p in match.away_team.players:
                if p.discord_id == member.id:
                    return MatchTeamEnum.AWAY

        # As a final check, we need to return a value to admins running the command.
        # Without this, we block the use of commands that validate players.
        if member.guild_permissions.manage_guild:
            return MatchTeamEnum.HOME

        raise ValueError(f"{member.display_name} is not a valid player in this match")

    async def build_match_embed(
        self,
        guild: discord.Guild,
        match: Match,
        user_team: MatchTeamEnum | None = None,
        with_gm: bool = True,
    ) -> discord.Embed:
        """Build the match information embed"""
        # Get embed color by tier
        tier = match.home_team.tier
        tier_color = await tier_color_by_name(guild, tier)

        # Format match day
        if match.match_type == MatchType.PRESEASON:
            md = f"Preseason Match {match.day}"
        elif match.match_type == MatchType.REGULAR:
            md = f"Match Day {match.day}"
        else:
            if match.day is None:
                raise ValueError(f"Unknown postseason match day (round): {match.day}")
            playoff_round = PostSeasonType(match.day)
            md = f"{playoff_round.name} Match".title()

        # Format Date
        if not match.var_date:
            raise AttributeError("Match does not contain a valid DateTime object")
        date_str = match.var_date.strftime("%B %-d, %Y")

        # Description
        desc = f"**{match.home_team.name}**\nversus\n**{match.away_team.name}**"

        # Lobby Info
        lobby_info = f"Name: **{match.game_name}**\nPass: **{match.game_pass}**"

        # Teams
        home_fmt, away_fmt = await self.roster_fmt_from_match(guild, match, with_gm=with_gm)

        # Create embed
        embed = discord.Embed(title=f"{md}: {date_str}", description=desc, color=tier_color)

        embed.add_field(name="Lobby Info", value=lobby_info, inline=False)
        embed.add_field(name="Home Team", value=home_fmt, inline=False)
        embed.add_field(name="Away Team", value=away_fmt, inline=False)

        # User Team for additional info
        additional_fmt = ""
        if user_team == MatchTeamEnum.HOME:
            additional_fmt += (
                "You are the **HOME** team.\x20"
                "You will create the room using the above information.\x20"
                "Contact the other team when your team is ready to begin the match.\x20"
                "Do **not** join a team before the away team does.\n\n"
            )
        elif user_team == MatchTeamEnum.AWAY:
            additional_fmt += (
                "You are the **AWAY** team.\x20"
                "You will join the room using the above information once the other team contacts you.\x20"
                "Do not begin joining a team until your entire team is ready to begin playing.\n\n"
            )
        additional_fmt += (
            "Be sure that **crossplay is enabled** and to save all replays and screenshots of the end-of-game scoreboard.\x20"
            "Do not leave the game until screenshots have been taken.\x20"
            "These must be uploaded to the [RSC Website](https://www.rocketsoccarconfederation.com/replay-and-screenshot-uploads) after the game is finished."  # noqa: E501
        )
        embed.add_field(name="Additional Info", value=additional_fmt, inline=False)
        return embed

    async def roster_fmt_from_match(self, guild: discord.Guild, match: Match, with_gm: bool = True) -> tuple[str, str]:
        """Return formatted roster string from Match"""
        home_players: list[str] = []
        away_players: list[str] = []

        if not (match.home_team.players and match.away_team.players):
            raise AttributeError("Match is missing players on home or away team.")

        home_gm: str | None = None
        away_gm: str | None = None

        # Get GM for each team.
        if with_gm:
            hgm = await self.franchise_gm_by_name(guild, name=match.home_team.franchise)
            if hgm and hgm.rsc_name:
                home_gm = hgm.rsc_name

            agm = await self.franchise_gm_by_name(guild, name=match.away_team.franchise)
            if agm and agm.rsc_name:
                away_gm = agm.rsc_name

        # Home
        for p in match.home_team.players:
            m = guild.get_member(p.discord_id)
            name = m.display_name if m else p.name

            # Captain
            if p.captain:
                name = f"{name} (C)"

            # Additional status formatting
            match p.status:
                case Status.FREE_AGENT | Status.PERM_FA:
                    if p.sub_status == SubStatus.OUT:
                        name = f"{name} (Subbed Out)"
                    elif p.sub_status == SubStatus.IN:
                        name = f"{name} (Subbed In)"
                    else:
                        name = f"{name} (Sub)"
                case Status.IR:
                    name = f"{name} (IR)"
                case Status.AGMIR | Status.IR:
                    name = f"{name} (AGM IR)"
                case Status.ROSTERED | Status.RENEWED:
                    pass
                case _:
                    # Not a valid status for rostered player
                    continue

            # GM
            if isinstance(m, discord.Member) and match.home_team.gm.discord_id == m.id:
                name = f"{name} (GM)"

            home_players.append(name)

        # Away
        for p in match.away_team.players:
            m = guild.get_member(p.discord_id)
            name = m.display_name if m else p.name

            # Captain
            if p.captain:
                name = f"{name} (C)"

            # Additional status formatting
            match p.status:
                case Status.FREE_AGENT | Status.PERM_FA:
                    if p.sub_status == SubStatus.OUT:
                        name = f"{name} (Subbed Out)"
                    elif p.sub_status == SubStatus.IN:
                        name = f"{name} (Subbed In)"
                    else:
                        name = f"{name} (Sub)"
                case Status.IR:
                    name = f"{name} (IR)"
                case Status.AGMIR | Status.IR:
                    name = f"{name} (AGM IR)"
                case Status.ROSTERED | Status.RENEWED:
                    pass
                case _:
                    # Not a valid status for rostered player
                    continue

            # GM
            if isinstance(m, discord.Member) and match.away_team.gm.discord_id == m.id:
                name = f"{name} (GM)"

            away_players.append(name)

        # Home team roster formatting
        home_fmt = "```\n"
        if home_gm:
            home_fmt += f"{match.home_team.name} - {match.home_team.franchise} ({home_gm})\n"
        else:
            home_fmt += f"{match.home_team.name} - {match.home_team.franchise}\n"
        home_fmt += "\n".join([f"\t{p}" for p in home_players])
        home_fmt += "\n```"

        # Away team roster formatting
        away_fmt = "```\n"
        if away_gm:
            away_fmt += f"{match.away_team.name} - {match.away_team.franchise} ({away_gm})\n"
        else:
            away_fmt += f"{match.away_team.name} - {match.away_team.franchise}\n"
        away_fmt += "\n".join([f"\t{p}" for p in away_players])
        away_fmt += "\n```"

        return (home_fmt, away_fmt)

    async def is_match_franchise_gm(self, member: discord.Member, match: Match) -> bool:
        return member.id in (match.home_team.gm.discord_id, match.away_team.gm.discord_id)

    async def is_match_franchise_agm(self, member: discord.Member, match: Match) -> bool:
        guild = member.guild
        agm_role = await utils.get_agm_role(guild)
        if agm_role not in member.roles:
            log.debug("Member is not AGM", guild=guild)
            return False

        hfranchise = match.home_team.franchise.lower()
        afranchise = match.away_team.franchise.lower()
        log.debug(f"Home Franchise: {hfranchise} Away Franchise: {afranchise}", guild=guild)
        matching_franchise = False
        for role in member.roles:
            log.debug(f"Checking for franchise role: {role.name}", guild=guild)
            if hfranchise in role.name.lower():
                matching_franchise = True
                break
            if afranchise in role.name.lower():
                matching_franchise = True
                break

        return matching_franchise

    async def is_future_match_date(self, guild: discord.Guild, match: Match | MatchList) -> bool:
        tz = await self.timezone(guild=guild)
        today = datetime.now(tz=tz)

        if not match.var_date:
            raise AttributeError("Match has no date associated with it in the API.")

        return today.date() < match.var_date.date()

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
    ) -> list[MatchList]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MatchesApi(client)
            try:
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
                )
                return matches.results
            except ApiException as exc:
                raise RscException(response=exc)

    async def find_match(
        self,
        guild: discord.Guild,
        teams: list[str],
        date_lt: datetime | None = None,
        date_gt: datetime | None = None,
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
            teams_fmt = ",".join(teams)
            try:
                return await api.matches_find_match(
                    teams=teams_fmt,
                    date__lt=date_lt.isoformat() if date_lt else None,
                    date__gt=date_gt.isoformat() if date_gt else None,
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
            except ApiException as exc:
                raise RscException(response=exc)

    async def match_by_id(self, guild: discord.Guild, id: int) -> Match:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MatchesApi(client)
            return await api.matches_read(id)

    async def report_match(
        self,
        guild: discord.Guild,
        match_id: int,
        ballchasing_group: str,
        home_score: int,
        away_score: int,
        executor: discord.Member,
        override: bool = False,
    ) -> MatchResults:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MatchesApi(client)
            try:
                data = MatchScoreReport(
                    ballchasing_group=ballchasing_group,
                    home_score=home_score,
                    away_score=away_score,
                    executor=executor.id,
                    override=override,
                )
                log.debug(f"Match Score Report ({match_id}): {data}")
                return await api.matches_score_report(match_id, data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def create_match(
        self,
        guild: discord.Guild,
        match_type: MatchType,
        match_format: MatchFormat,
        home_team_id: int,
        away_team_id: int,
        day: int,
    ) -> Match:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MatchesApi(client)
            try:
                data = MatchSubmission(
                    home_team=home_team_id,
                    away_team=away_team_id,
                    match_format=match_format,
                    match_type=match_type,
                    day=day,
                )
                log.debug(f"Match Create: {data}")
                return await api.matches_create(data)
            except ApiException as exc:
                raise RscException(response=exc)
