import asyncio
import logging
from datetime import datetime
from collections.abc import AsyncIterator

import discord
from redbot.core import app_commands
from rscapi import MatchesApi, TeamsApi
from rscapi.exceptions import ApiException
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.match import Match
from rscapi.models.match_list import MatchList
from rscapi.models.match_results import MatchResults
from rscapi.models.match_score_report_request import MatchScoreReportRequest
from rscapi.models.match_submission import MatchSubmission
from rscapi.models.match_team import MatchTeam
from rscapi.models.pending_series import PendingSeries

from rsc.abc import RSCMixIn
from rsc.ballchasing.views import match_label
from rsc.const import MATCH_CHECK_IN_CHANNEL
from rsc.embeds import BlueEmbed, ErrorEmbed, ExceptionErrorEmbed, YellowEmbed, ApiExceptionErrorEmbed
from rsc.enums import (
    MatchFormat,
    MatchTeamEnum,
    MatchType,
    PostSeasonType,
    Status,
)
from rsc.exceptions import RscException
from rsc.logs import GuildLogAdapter
from rsc.matches.views import NO_UPCOMING_MATCH, Contact, MatchCard, PendingSeriesCard, TeamBlock, player_line, series_label
from rsc.teams import TeamMixIn
from rsc.pagination import API_MAX_PAGE_SIZE, check_page_limit, iter_pages
from rsc.utils.utils import strip_trailing_accolades, tier_color_by_name
from rsc.utils.website import bracket_url, website_url

from rscapi.models.paginated_match_list_list import PaginatedMatchListList
from rscapi.models.match_format_enum import MatchFormatEnum
from rscapi.models.match_type_enum import MatchTypeEnum

logger = logging.getLogger("red.rsc.matches")
log = GuildLogAdapter(logger)


class MatchMixIn(RSCMixIn):
    # guild.id -> the `/reportmatch` mention the /match card ends with
    _reportmatch_mentions: dict[int, str]

    def __init__(self) -> None:
        log.debug("Initializing MatchMixIn")
        self._reportmatch_mentions = {}
        super().__init__()

    # App Commands

    @app_commands.command(
        name="schedule",
        description="Display your team or another teams entire schedule",
    )
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)
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
        tier_color = discord.Color.default()
        if tier:
            tier_color = await tier_color_by_name(guild, tier)
        elif schedule[0].home_team.tier:
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

    @app_commands.command(
        name="match",
        description="Get information about your upcoming match",
    )
    @app_commands.describe(
        team="Get match information for a specific team (Franchise Management Only)", day="Get match information for a specific match day"
    )
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)
    @app_commands.guild_only
    async def _match_cmd(self, interaction: discord.Interaction, team: str | None = None, day: int | None = None):
        guild = interaction.guild
        if not (guild and isinstance(interaction.user, discord.Member)):
            return

        await interaction.response.defer(ephemeral=True)

        # Find the team ID
        if team:
            # Get API id of team
            try:
                team_id = await self.team_id_by_name(guild, name=team)
            except ValueError as exc:
                return await interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(exc)), ephemeral=True)
        else:
            plist = await self.players(guild, discord_id=interaction.user.id, limit=1)
            if not plist:
                await interaction.followup.send(
                    embed=ErrorEmbed(description="You are not currently signed up for the league."),
                    ephemeral=True,
                )
                return

            player = plist.pop(0)
            if not (player.team and player.team.id and player.team.name):
                await interaction.followup.send(
                    embed=ErrorEmbed(description="You are not currently rostered on a team."),
                    ephemeral=True,
                )
                return

            team_id = player.team.id

        reply = await self.match_reply(guild, interaction.user, team_id, asked=bool(team), day=day)
        if reply is None:
            reply = BlueEmbed(title="Match Info", description=NO_UPCOMING_MATCH)
        if isinstance(reply, discord.Embed):
            return await interaction.followup.send(embed=reply, ephemeral=True)
        view, files = reply.render()
        await interaction.followup.send(view=view, files=files, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    # Functions

    async def match_reply(
        self,
        guild: discord.Guild,
        member: discord.Member,
        team_id: int,
        *,
        asked: bool,
        day: int | None = None,
    ) -> MatchCard | PendingSeriesCard | discord.Embed | None:
        """What `/match` shows `member` for a team: its match card, its pending playoff series,
        an error embed, or None when it has no upcoming match. Refresh on the pending card asks again.

        `asked` is whether `/match` named the team. A named team's match carries a lobby, so only
        its franchise managers and staff may see it.
        """
        try:
            if day:
                log.debug(f"Getting match for team: {team_id} on day: {day}", guild=guild)
                # Does not support preseason matches currently
                match = await self.match_by_day(guild, team_id, day, preseason=False)
            else:
                log.debug(f"Getting match for team: {team_id}", guild=guild)
                match = await self.next_match(guild, team_id)

            if not match:
                if day:
                    return None
                # A bye seed's next playoff series has no match until the series feeding it is
                # reported, which on a playoff night is minutes before it starts. It carries no
                # lobby, so it is safe to show whoever asked, franchise manager or not.
                series = await self.pending_series(guild, team_id)
                return await self.pending_series_card(guild, series, team_id=team_id, asked=asked) if series else None

            # Resolved once and reused below, so the command makes a single AGM
            # lookup instead of one per check.
            agm_franchise = await self.agm_franchise_of(guild, member.id)
            try:
                is_gm = asked and await self.is_match_franchise_gm(member=member, match=match)
            except AttributeError as exc:
                # A Refresh click is already acknowledged, so an exception here would leave it unanswered
                return ExceptionErrorEmbed(str(exc))
            if asked and not (
                is_gm
                or await self.is_match_franchise_agm(member=member, match=match, agm_franchise=agm_franchise)
                or member.guild_permissions.manage_guild
            ):
                return ErrorEmbed(
                    description=(
                        "Only franchise managers can specify a team for match information. "
                        "If you are not a GM or AGM, please simply run `/match` to get your teams match information."
                    )
                )

            try:
                side = await self.match_team_by_user(match, member, agm_franchise=agm_franchise)
            except ValueError as exc:
                return ExceptionErrorEmbed(str(exc))
            return await self.match_card(guild, match, side)
        except RscException as exc:
            log.debug(f"Match Return Status: {exc.status}")
            return ApiExceptionErrorEmbed(exc, title="Match Info")

    async def match_card(self, guild: discord.Guild, match: Match, side: MatchTeamEnum | None) -> MatchCard:
        """Gather what the `/match` card shows. See `MatchCard.render`."""
        home, away = match.home_team, match.away_team
        colour = await tier_color_by_name(guild, home.tier) if home.tier else discord.Colour.default()
        home_logo, away_logo = await asyncio.gather(
            self.franchise_logo_url(guild, home.franchise),
            self.franchise_logo_url(guild, away.franchise),
        )

        contact = None
        if side:
            opponent = away if side is MatchTeamEnum.HOME else home
            captain = next((m for p in opponent.players or [] if p.captain and (m := guild.get_member(p.discord_id))), None)
            gm = guild.get_member(opponent.gm.discord_id) if opponent.gm and opponent.gm.discord_id else None
            if captain:
                contact = Contact(captain.mention, "captain")
            elif gm:
                contact = Contact(gm.mention, "GM")
        check_in = discord.utils.get(guild.text_channels, name=MATCH_CHECK_IN_CHANNEL)

        playoffs = match.match_type in (MatchType.POSTSEASON, MatchType.FINALS)
        return MatchCard(
            tier=home.tier,
            label=match_label(match),
            series=series_label(match.match_format, match.num_games),
            starts=match.var_date,
            lobby_name=match.game_name,
            lobby_pass=match.game_pass,
            home=self._team_block(guild, home, home_logo),
            away=self._team_block(guild, away, away_logo),
            side=side,
            contact=contact,
            check_in_channel=check_in.mention if check_in else None,
            match_url=await self.match_page_link(guild, match),
            bracket_url=await self.bracket_link(guild, home.tier, match.season_number) if playoffs else None,
            reportmatch=await self.reportmatch_mention(guild),
            colour=colour,
        )

    @staticmethod
    def _team_block(guild: discord.Guild, team: MatchTeam, logo_url: str | None) -> TeamBlock:
        gm_id = team.gm.discord_id if team.gm else None
        gm_member = guild.get_member(gm_id) if gm_id else None
        if gm_member:
            gm = gm_member.mention
        elif team.gm and team.gm.rsc_name:
            gm = discord.utils.escape_markdown(team.gm.rsc_name)
        else:
            gm = None

        players: list[str] = []
        for p in team.players or []:
            member = guild.get_member(p.discord_id)
            name = strip_trailing_accolades(member.display_name) if member else p.name
            if line := player_line(name, p, is_gm=p.discord_id == gm_id):
                players.append(line)
        return TeamBlock(name=team.name, franchise=team.franchise, gm=gm, logo_url=logo_url, players=tuple(players))

    async def pending_series_card(self, guild: discord.Guild, series: PendingSeries, *, team_id: int, asked: bool) -> PendingSeriesCard:
        """Gather what the pending-opponent card shows. See `PendingSeriesCard.render`."""
        feeder = series.feeder_match
        try:
            feeder_round = PostSeasonType(feeder.day).name.title() if feeder.day else None
        except ValueError:
            feeder_round = None
        return PendingSeriesCard(
            team_id=team_id,
            asked=asked,
            tier=series.tier,
            round_label=series.round_label,
            series=series_label(series.match_format, series.num_games),
            team=series.team.name,
            opponents=tuple(t.name for t in series.possible_opponents),
            starts=series.var_date,
            feeder_round=feeder_round,
            feeder_starts=feeder.var_date,
            home=series.home,
            logo_url=await self.team_logo_url(guild, series.team.name, team_id),
            # A pending series is always in the current season, which the bracket opens on
            bracket_url=await self.bracket_link(guild, series.tier),
            colour=await tier_color_by_name(guild, series.tier),
        )

    async def franchise_logo_url(self, guild: discord.Guild, franchise: str | None) -> str | None:
        """The franchise's logo, else the server icon."""
        logo_url = None
        if franchise:
            try:
                fsearch = await self.franchises(guild, name=franchise)
                if fsearch and fsearch[0].id:
                    logo_url = await self.franchise_logo(guild=guild, id=fsearch[0].id)
            except RscException as exc:
                log.warning(f"Unable to fetch the {franchise} logo: {exc}", guild=guild)
        return logo_url or (guild.icon.url if guild.icon else None)

    async def team_logo_url(self, guild: discord.Guild, name: str, team_id: int) -> str | None:
        """The logo of the team's franchise, else the server icon."""
        logo_url = None
        try:
            team = next((t for t in await self.teams(guild, name=name) if t.id == team_id), None)
            if team and team.franchise.id:
                logo_url = await self.franchise_logo(guild=guild, id=team.franchise.id)
        except RscException as exc:
            log.warning(f"Unable to fetch the {name} franchise logo: {exc}", guild=guild)
        return logo_url or (guild.icon.url if guild.icon else None)

    async def bracket_link(self, guild: discord.Guild, tier: str | None, season_number: int | None = None) -> str | None:
        """The tier's playoff bracket on the league website, or None if it can't be built."""
        conf = self._api_conf.get(guild.id)
        league_id = self._league.get(guild.id)
        site = website_url(conf.host) if conf else None
        if not (site and league_id and tier):
            return None
        season_id = await self.season_id_for_number(guild, season_number) if season_number else None
        return bracket_url(site, tier, league_id=league_id, season_id=season_id)

    async def reportmatch_mention(self, guild: discord.Guild) -> str:
        """A clickable `/reportmatch`, looked up once per server: fetching synced commands is an API call."""
        if mention := self._reportmatch_mentions.get(guild.id):
            return mention
        try:
            synced = await self.bot.tree.fetch_commands() or await self.bot.tree.fetch_commands(guild=guild)
        except discord.HTTPException as exc:
            log.warning(f"Unable to look up the /reportmatch mention: {exc}", guild=guild)
            return "`/reportmatch`"
        command = next((c for c in synced if c.name == "reportmatch"), None)
        mention = command.mention if command else "`/reportmatch`"
        self._reportmatch_mentions[guild.id] = mention
        return mention

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

    async def matches_from_match_list(self, match_list: list[MatchList]) -> None:
        pass

    async def match_team_by_user(
        self,
        match: Match,
        member: discord.Member,
        agm_franchise: FranchiseList | None = None,
    ) -> MatchTeamEnum | None:
        """The member's side of the match, or None for staff with no part in it."""
        # Check if GM of team
        if match.home_team.gm and match.home_team.gm.discord_id == member.id:
            return MatchTeamEnum.HOME

        if match.away_team.gm and match.away_team.gm.discord_id == member.id:
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

        # Ahead of the staff check below, so an admin who is also the away
        # franchise's AGM gets AWAY rather than no side.
        agm_team = await self.match_franchise_agm_team(member, match, agm_franchise)
        if agm_team:
            return agm_team

        # Staff may look at any match. They get the card without a side.
        if member.guild_permissions.manage_guild:
            return None

        raise ValueError(f"{member.display_name} is not a valid player in this match")

    async def is_match_franchise_gm(self, member: discord.Member, match: Match) -> bool:
        if not (match.home_team.gm and match.away_team.gm):
            raise AttributeError("Match is missing GM information.")
        if not (match.home_team.gm.discord_id and match.away_team.gm.discord_id):
            raise AttributeError("Match is missing GM Discord IDs.")
        return member.id in (match.home_team.gm.discord_id, match.away_team.gm.discord_id)

    async def match_franchise_agm_team(
        self,
        member: discord.Member,
        match: Match,
        agm_franchise: FranchiseList | None = None,
    ) -> MatchTeamEnum | None:
        """Which side of this match the member is an AGM of, or `None`.

        Asks the API, the same way `is_match_franchise_gm` reads GM discord IDs
        straight off the match. The old answer came from discord: it required a
        role named "Assistant GM" and then substring matched the franchise name
        against every role the member held, so an AGM of "Eagles" also passed for
        a match involving "Eagles Nest".

        Pass `agm_franchise` when the caller has already resolved it, so a single
        command does not ask twice.
        """
        guild = member.guild
        franchise = agm_franchise if agm_franchise is not None else await self.agm_franchise_of(guild, member.id)
        if not (franchise and franchise.name):
            log.debug("Member is not an AGM", guild=guild)
            return None

        fname = franchise.name.casefold()
        log.debug(f"AGM of {franchise.name}. Home: {match.home_team.franchise} Away: {match.away_team.franchise}", guild=guild)

        if match.home_team.franchise and match.home_team.franchise.casefold() == fname:
            return MatchTeamEnum.HOME
        if match.away_team.franchise and match.away_team.franchise.casefold() == fname:
            return MatchTeamEnum.AWAY
        return None

    async def is_match_franchise_agm(
        self,
        member: discord.Member,
        match: Match,
        agm_franchise: FranchiseList | None = None,
    ) -> bool:
        return await self.match_franchise_agm_team(member, match, agm_franchise) is not None

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
        check_page_limit(limit, caller="matches()")
        async with self.api_client(guild) as client:
            api = MatchesApi(client)
            try:
                matches: PaginatedMatchListList = await api.matches_list(
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

    async def paged_matches(
        self,
        guild: discord.Guild,
        season_number: int,
        date__lt: datetime | None = None,
        date__gt: datetime | None = None,
        season: int | None = None,
        match_team_type: MatchTeamEnum = MatchTeamEnum.ALL,
        team_name: str | None = None,
        day: int | None = None,
        match_type: MatchType | None = None,
        match_format: MatchFormat | None = None,
        per_page: int = API_MAX_PAGE_SIZE,
    ) -> AsyncIterator[MatchList]:
        """Generator to page through matches (Must have season number due to high API load)"""
        async with self.api_client(guild) as client:
            api = MatchesApi(client)

            async def fetch(limit: int, offset: int) -> PaginatedMatchListList:
                try:
                    return await api.matches_list(
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
                except ApiException as exc:
                    raise RscException(exc)

            async for match in iter_pages(fetch, per_page=per_page):
                yield match

    async def match_by_day(self, guild: discord.Guild, team_id: int, day: int, preseason: bool = False) -> Match:
        async with self.api_client(guild) as client:
            api = TeamsApi(client)
            try:
                log.debug(f"Fetching match for team ID: {team_id} on day: {day} (preseason={preseason})", guild=guild)
                match: Match = await api.teams_match_retrieve(
                    id=team_id,
                    day=day,
                    preseason=preseason,
                )
                return match
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
    ) -> list[Match]:
        async with self.api_client(guild) as client:
            api = MatchesApi(client)
            teams_fmt = ",".join(teams)
            try:
                resp = await api.matches_find_match_retrieve(
                    teams=teams_fmt,
                    date__lt=date_lt,
                    date__gt=date_gt,
                    season=season,
                    season_number=season_number,
                    day=day,
                    match_type=str(match_type) if match_type else None,
                    match_format=str(match_format) if match_format else None,
                    league=self._league[guild.id],
                )
                return resp.results
            except ApiException as exc:
                raise RscException(response=exc)

    async def match_by_id(self, guild: discord.Guild, id: int) -> Match:
        async with self.api_client(guild) as client:
            api = MatchesApi(client)
            return await api.matches_retrieve(id)

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
        async with self.api_client(guild) as client:
            api = MatchesApi(client)
            try:
                data = MatchScoreReportRequest(
                    ballchasing_group=ballchasing_group,
                    home_score=home_score,
                    away_score=away_score,
                    executor=executor.id,
                    override=override,
                )
                log.debug(f"Match Score Report ({match_id}): {data}")
                return await api.matches_score_report_create(match_id, data)
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
        async with self.api_client(guild) as client:
            api = MatchesApi(client)
            try:
                data = MatchSubmission(
                    home_team=home_team_id,
                    away_team=away_team_id,
                    match_format=MatchFormatEnum(match_format.value),
                    match_type=MatchTypeEnum(match_type.value),
                    day=day,
                )
                log.debug(f"Match Create: {data}")
                return await api.matches_create(data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def match_results(self, guild: discord.Guild, id: int) -> MatchResults:
        """Fetch Match results object by ID"""
        async with self.api_client(guild) as client:
            api = MatchesApi(client)
            try:
                return await api.matches_results_retrieve(id)
            except ApiException as exc:
                raise RscException(response=exc)
