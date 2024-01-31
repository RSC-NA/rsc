import asyncio
import difflib
import logging
import random
import statistics
import string
import time
from datetime import datetime, timedelta, timezone
from hashlib import md5
from urllib.parse import urljoin

import ballchasing
import discord
from discord.app_commands import Transform
from redbot.core import app_commands
from rscapi.models.match import Match
from rscapi.models.match_list import MatchList
from rscapi.models.tracker_link import TrackerLink

from rsc.abc import RSCMixIn
from rsc.ballchasing.views import BallchasingProcessingView
from rsc.embeds import BlueEmbed, ErrorEmbed, RedEmbed, SuccessEmbed, YellowEmbed
from rsc.enums import MatchFormat, MatchType, TrackerLinksStatus
from rsc.teams import TeamMixIn
from rsc.tiers import TierMixIn
from rsc.transformers import DateTransformer
from rsc.types import BallchasingCollisions, BallchasingResult
from rsc.utils import utils
from rsc.views import LinkButton

log = logging.getLogger("red.rsc.ballchasing")

defaults_guild = {
    "AuthToken": None,
    "TopLevelGroup": None,
    "LogChannel": None,
    "ManagerRole": None,
    "RscSteamId": None,
    "ReportCategory": None,
}

verify_timeout = 30
BALLCHASING_URL = "https://ballchasing.com"
DONE = "Done"
WHITE_X_REACT = "\U0000274E"  # :negative_squared_cross_mark:
WHITE_CHECK_REACT = "\U00002705"  # :white_check_mark:
# RSC_STEAM_ID = 76561199096013422  # RSC Steam ID
# RSC_STEAM_ID = 76561197960409023  # REMOVEME - my steam id for development

LARGE_BATCH_SIZE = 10
SMALL_BATCH_SIZE = 5


class BallchasingMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing BallchasingMixIn")

        self.config.init_custom("Ballchasing", 1)
        self.config.register_custom("Ballchasing", **defaults_guild)
        self._ballchasing_api: dict[int, ballchasing.Api] = {}
        # self.task = asyncio.create_task(self.pre_load_data())
        # self.ffp = {}  # forfeit processing
        super().__init__()

    # Setup

    async def prepare_ballchasing(self, guild: discord.Guild):
        token = await self._get_bc_auth_token(guild)
        if token:
            self._ballchasing_api[guild.id] = ballchasing.Api(auth_key=token)
            await self._ballchasing_api[guild.id].ping()

    # Settings
    _ballchasing: app_commands.Group = app_commands.Group(
        name="ballchasing",
        description="Ballchasing commands and configuration",
        guild_only=True,
    )

    @_ballchasing.command(
        name="settings",
        description="Display settings for ballchasing replay management",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_settings(self, interaction: discord.Interaction):
        """Show transactions settings"""
        guild = interaction.guild
        if not guild:
            return

        url = BALLCHASING_URL
        token = (
            "Configured" if await self._get_bc_auth_token(guild) else "Not Configured"
        )
        log_channel = await self._get_bc_log_channel(guild)
        score_category = await self._get_score_reporting_category(guild)
        role = await self._get_bc_manager_role(guild)
        tlg = await self._get_top_level_group(guild)

        if tlg:
            tlg_url = await self.bc_group_full_url(tlg)
        else:
            tlg_url = "None"

        embed = discord.Embed(
            title="Ballchasing Settings",
            description="Current configuration for Ballchasing replay management",
            color=discord.Color.blue(),
        )

        embed.add_field(name="Ballchasing URL", value=url, inline=False)
        embed.add_field(name="Ballchasing API Token", value=token, inline=False)
        embed.add_field(
            name="Management Role", value=role.mention if role else "None", inline=False
        )
        embed.add_field(
            name="Log Channel",
            value=log_channel.mention if log_channel else "None",
            inline=False,
        )
        embed.add_field(
            name="Report Category",
            value=score_category,
            inline=False,
        )
        embed.add_field(
            name="Top Level Ballchasing Group",
            value=tlg_url,
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_ballchasing.command(
        name="key", description="Configure the Ballchasing API key for the server"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_key(self, interaction: discord.Interaction, key: str):
        if not interaction.guild:
            return
        await self._save_bc_auth_token(interaction.guild, key)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description="Ballchasing API key have been successfully configured"
            ),
            ephemeral=True,
        )

    @_ballchasing.command(
        name="manager",
        description="Configure the ballchasing management role (Ex: @Stats Committee)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_management_role(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        if not interaction.guild:
            return
        await self._save_bc_manager_role(interaction.guild, role)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"Ballchasing management role set to {role.mention}"
            ),
            ephemeral=True,
        )

    @_ballchasing.command(
        name="log",
        description="Configure the logging channel for Ballchasing commands (Ex: #stats-committee)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_log_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        if not interaction.guild:
            return
        await self._save_bc_log_channel(interaction.guild, channel)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"Ballchasing log channel set to {channel.mention}"
            ),
            ephemeral=True,
        )

    @_ballchasing.command(
        name="category",
        description="Configure the score reporting category for the server",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_score_category(
        self, interaction: discord.Interaction, category: discord.CategoryChannel
    ):
        await self._save_score_reporting_category(interaction.guild, category)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"Score reporting category set to **{category.name}**"
            ),
            ephemeral=True,
        )

    @_ballchasing.command(
        name="toplevelgroup",
        description="Configure the top level ballchasing group for RSC",
    )
    @app_commands.describe(group='Ballchasing group string (Ex: "rsc-v4rxmuxj6o")')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_top_level_group(self, interaction: discord.Interaction, group: str):
        if not interaction.guild:
            return
        await self._save_top_level_group(interaction.guild, group)
        full_url = await self.bc_group_full_url(group)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                title="Ballchasing Group",
                description=f"Ballchasing top level group set to **{group}**",
                url=full_url,
            ),
            ephemeral=True,
        )

    # Commands

    @_ballchasing.command(
        name="reportall",
        description="Find and report all matches for the day on ballchasing",
    )
    @app_commands.describe(
        matchday="Match day to report (Optional: Defaults to current match day)",
        matchtype="Match type to find. (Default: Regular Season)",
        force="Force reporting even if match has been marked completed. (Default: False)",
        upload="Enable or disable replay uploads to RSC ballchasing group. (Default: True)",
        announce="Announce the match result to the tier score reporting channel. (Default: True)",
    )
    async def _bc_reportall(
        self,
        interaction: discord.Interaction,
        matchday: int | None = None,
        matchtype: MatchType = MatchType.REGULAR,
        force: bool = False,
        upload: bool = True,
        announce: bool = True,
    ):
        guild = interaction.guild
        if not (guild and isinstance(interaction.user, discord.Member)):
            return

        if not await self.has_bc_permissions(interaction.user):
            await interaction.response.send_message(
                "You do not have permission to run this command.", ephemeral=True
            )
            return

        log_channel = await self._get_bc_log_channel(guild)
        if not log_channel:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Ballchasing log channel is not configured."
                ),
                ephemeral=True,
            )
            return

        # Send loading...
        await interaction.response.send_message(
            embed=BlueEmbed(
                title="Replay Processing Started",
                description="Please be patient while match data is collected...",
            ),
            ephemeral=True,
        )

        date_gt = None
        date_lt = None
        if not matchday:
            log.debug("Match day not specified. Searching by todays date")
            # Get guild timezone
            tz = await self.timezone(guild)
            date = datetime.now(tz=tz).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            date_gt, date_lt = await self.get_match_date_range(date)

        # Get match by teams and date
        log.debug(f"Fetching matches for {matchday or 'today'}. Type: {matchtype}")
        mlist: list[MatchList] = await self.matches(
            guild,
            date__lt=date_lt,
            date__gt=date_gt,
            day=matchday,
            match_type=matchtype,
            # limit=40,  # Development limit. TODO FIX ME
            limit=500,
        )
        log.debug(f"Found {len(mlist)} matches")

        # No match found
        if not mlist:
            await interaction.followup.send(
                embed=ErrorEmbed(description="No matches found."), ephemeral=True
            )
            return

        log.debug("Fetching detailed match data")
        mtasks: list[asyncio.Task] = []
        # Workaround for now
        for i in range(0, len(mlist), LARGE_BATCH_SIZE):
            log.debug(f"Fetching batch {i}")
            mbatch = mlist[i : i + LARGE_BATCH_SIZE]
            try:
                async with asyncio.TaskGroup() as tg:
                    for m in mbatch:
                        if m.id:
                            mtasks.append(tg.create_task(self.match_by_id(guild, m.id)))
            except ExceptionGroup as eg:
                for err in eg.exceptions:
                    log.error(f"ExceptionGroup Err: {err}")
                raise eg
        matches: list[Match] = [r.result() for r in mtasks]

        log.debug("Fetching tier data")
        tiers = await self.tiers(guild)
        if not tiers:
            await interaction.edit_original_response(
                embed=ErrorEmbed(description="Unable to fetch tier data.")
            )

        if not matches:
            await interaction.edit_original_response(
                embed=ErrorEmbed(description="Unable to fetch detailed match data.")
            )
            return

        stats_role = await self._get_bc_manager_role(guild)

        # ballchasing match day groups
        tgroups: dict[str, str | None] = {}
        for match in matches:
            if tgroups.get(match.home_team.tier):
                continue
            grp = await self.match_day_bc_group(guild, match)
            if grp:
                url = await self.bc_group_full_url(grp)
                tgroups[match.home_team.tier] = url

        report_view = BallchasingProcessingView(
            interaction, matches, tiers, log_channel, stats_role
        )
        report_view.tier_groups = tgroups
        await report_view.prompt()

        # Shuffle because it looks better :)
        random.shuffle(matches)

        log.debug("Fetching matches from ballchasing")
        bc_results: list[BallchasingResult] = []
        for i in range(0, len(matches), LARGE_BATCH_SIZE):
            if report_view.cancelled:
                continue

            log.debug(f"Fetching batch {i}")
            bcbatch = matches[i : i + LARGE_BATCH_SIZE]

            await report_view.next_batch(bcbatch)

            # Discovery replays
            task_results: list[BallchasingResult] = []
            bc_tasks: list[asyncio.Task] = []
            try:
                async with asyncio.TaskGroup() as tg:
                    for b in bcbatch:
                        bc_tasks.append(tg.create_task(self.process_match(guild, b)))
            except ExceptionGroup as eg:
                for err in eg.exceptions:
                    log.error(err)
                raise eg

            # Store successful results
            task_results = [r.result() for r in bc_tasks]

            upload_tasks = []
            if upload:
                # Upload to ballchasing
                log.debug("Uploading result batch to ballchasing")
                async with asyncio.TaskGroup() as tg:
                    for result in task_results:
                        utask = tg.create_task(
                            self.create_and_upload_replays(guild, result)
                        )
                        upload_tasks.append(utask)
                upload_results = [u.result() for u in upload_tasks]

                for i in range(len(upload_results)):
                    url = await self.bc_group_full_url(upload_results[i])
                    task_results[i]["link"] = url

            # Announce to score report channel
            if announce:
                log.debug("Announcing result batch")
                embed_tasks = []
                async with asyncio.TaskGroup() as tg:
                    for result in task_results:
                        log.debug(f"Match Valid: {result['valid']}")
                        log.debug(
                            f"Home Wins {result['home_wins']} Away Wins: {result['away_wins']}"
                        )
                        if not result["valid"]:
                            continue
                        mtier = result["match"].home_team.tier
                        etask = tg.create_task(
                            self.build_match_result_embed(
                                guild, result=result, link=result["link"]
                            )
                        )
                        embed_tasks.append(etask)

                embed_results = [e.result() for e in embed_tasks]

                log.debug(f"Embed Len: {len(embed_results)}")
                for i in range(len(embed_results)):
                    mtier = task_results[i]["match"].home_team.tier
                    await self.announce_to_score_reporting(
                        guild, tier=mtier, embed=embed_results[i]
                    )

            bc_results.extend(task_results)
            await report_view.update(
                [tr["match"] for tr in task_results if tr["valid"]]
            )

        await report_view.finished()
        await report_view.prompt()

        # Missing matches
        for r in bc_results:
            if not r["valid"]:
                rmatch = r["match"]
                log.debug(
                    (
                        f"{rmatch.home_team.name} vs {rmatch.away_team.name} not found."
                        f" Total Replays: {len(r['replays'])}"
                    )
                )

        # Statistics
        exc_times = [x["execution_time"] for x in bc_results]
        median = statistics.median(exc_times)
        fmean = statistics.fmean(exc_times)
        stdev = statistics.stdev(exc_times)
        log.debug(f"Median execution time: {median}")
        log.debug(f"Mean execution time: {fmean}")
        log.debug(f"Standard deviation: {stdev}")
        for x in bc_results:
            if x["execution_time"] > (median + 2 * stdev):
                match = x["match"]
                home = match.home_team.name
                away = match.away_team.name
                log.warning(
                    f"Very slow execution time for {home} vs {away}. ExecutionTime={x['execution_time']}"
                )

            # match_group = await self.rsc_match_bc_group(interaction.guild, match)
            # if match_group:
            #     await self.upload_replays(
            #         guild=interaction.guild,
            #         group=match_group,
            #         match=match,
            #         result=result,
            #     )
            # else:
            #     log.error("Failed to retrieve or create a ballchasing group for match.")

    @_ballchasing.command(
        name="reporttier",
        description="Report a specific tier on ballchasing",
    )
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)
    @app_commands.describe(
        tier="Tier name to report",
        matchday="Match day to report (Optional: Defaults to current match day)",
        matchtype="Match type to find. (Default: Regular Season)",
        force="Force reporting even if match has been marked completed. (Default: False)",
        upload="Enable or disable replay uploads to RSC ballchasing group. (Default: True)",
        announce="Announce the match result to the tier score reporting channel. (Default: True)",
    )
    async def _bc_reporttier(
        self,
        interaction: discord.Interaction,
        tier: str,
        matchday: int | None = None,
        matchtype: MatchType = MatchType.REGULAR,
        force: bool = False,
        upload: bool = True,
        announce: bool = True,
    ):
        guild = interaction.guild
        if not (guild and isinstance(interaction.user, discord.Member)):
            return

        if not await self.has_bc_permissions(interaction.user):
            await interaction.response.send_message(
                "You do not have permission to run this command.", ephemeral=True
            )
            return

        # Defer
        await interaction.response.defer()

        date_gt = None
        date_lt = None
        if not matchday:
            log.debug("Match day not specified. Searching by todays date")
            # Get guild timezone
            tz = await self.timezone(guild)
            date = datetime.now(tz=tz).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            date_gt, date_lt = await self.get_match_date_range(date)

        # Get match by teams and date
        log.debug(f"Fetching matches for {tier}. Type: {matchtype}")
        mlist: list[MatchList] = await self.matches(
            guild,
            date__lt=date_lt,
            date__gt=date_gt,
            day=matchday,
            match_type=matchtype,
            limit=100,
        )
        log.debug("Done searching")

        # No match found
        if not mlist:
            await interaction.followup.send(
                embed=ErrorEmbed(description="No matches found.")
            )
            return
        # TODO need monty to add tier search

    @_ballchasing.command(
        name="reportmatch",
        description="Report a specific match on ballchasing",
    )
    @app_commands.autocomplete(
        home=TeamMixIn.teams_autocomplete,
        away=TeamMixIn.teams_autocomplete,
    )  # type: ignore
    @app_commands.describe(
        home="Home team name",
        away="Away team name",
        date='Match date in ISO 8601 format. Defaults to todays date. (Example: "2023-01-25")',
        force="Force reporting even if match has been marked completed. (Default: False)",
        upload="Enable or disable replay uploads to RSC ballchasing group. (Default: True)",
        announce="Announce the match result to the tier score reporting channel. (Default: True)",
    )
    async def _bc_manager_reportmatch(
        self,
        interaction: discord.Interaction,
        home: str,
        away: str,
        date: Transform[datetime, DateTransformer] | None = None,
        force: bool = False,
        upload: bool = True,
        announce: bool = True,
    ):
        if not (interaction.guild and isinstance(interaction.user, discord.Member)):
            return

        if not await self.has_bc_permissions(interaction.user):
            await interaction.response.send_message(
                "You do not have permission to run this command.", ephemeral=True
            )
            return

        # Defer
        await interaction.response.defer()

        # Get guild timezone
        tz = await self.timezone(interaction.guild)

        # Add timezone to date. If date not supplied, use todays date()
        if date:
            date = date.replace(tzinfo=tz)
        else:
            date = datetime.now(tz=tz).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

        # date = datetime(2023, 9, 11, tzinfo=tz)  # TEST REMOVE ME
        log.info(
            f"Searching for individual match. Home: {home} Away: {away} Date: {date}"
        )

        # Get match by teams and date
        date_gt, date_lt = await self.get_match_date_range(date)
        log.debug(f"Search Start: {date_gt} Search End: {date_lt}")
        matches: list[Match] = await self.find_match(
            interaction.guild,
            date__lt=date_lt,
            date__gt=date_gt,
            teams=f"{home}, {away}",
            limit=1,
        )
        log.debug("Done searching")

        # No match found
        if not matches:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description="No matches found for specified teams and date."
                )
            )
            return

        match = None
        for m in matches:
            if m.home_team.name == home and m.away_team.name == away:
                match = m

        if not match:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description=(
                        f"Unable to find match for **{home}** vs **{away}**."
                        " Try specifying a date."
                    )
                )
            )
            return

        log.debug("Match found in RSC API.")

        # Check if match is already complete
        if await self.match_already_complete(match) and not force:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description=(
                        "This match has already been completed and recorded."
                        "\n\nRun the command again with `force` parameter to pull regardless."
                    )
                )
            )
            return

        # Check if team name matches
        if not await self.check_team_type_match(home, away, match):
            log.debug("Team names do not match home/away")
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description="Home or away team name is not correct for the match found."
                )
            )
            return

        # log.debug("Team names match home/away")

        log.debug(f"Match ID: {match.id}")

        # Send "working" message
        await interaction.followup.send(
            embed=YellowEmbed(
                title="Processing Match",
                description=f"Searching ballchasing for match **{home}** vs **{away}** on **{match.var_date.date()}**",
            )
        )

        result = await self.process_match(interaction.guild, match)

        if not result or not result["valid"]:
            fembed = RedEmbed(
                title="Match Processing Failed",
                description="Unable to find a valid replay set.",
            )
            if match.var_date:
                fembed.add_field(
                    name="Date",
                    value=discord.utils.format_dt(match.var_date),
                    inline=True,
                )
            fembed.add_field(name="Home", value=home, inline=True)
            fembed.add_field(name="Away", value=away, inline=True)
            await interaction.edit_original_response(embed=fembed)
            return

        match_group = None
        tier = match.home_team.tier
        embed = await self.build_match_result_embed(
            guild=interaction.guild, result=result, link=None
        )  # TODO give link

        # Give notice that replays are not being uploaded
        if not upload:
            embed.set_footer(text="Replays were NOT uploaded to ballchasing.")
        else:
            match_group = await self.rsc_match_bc_group(interaction.guild, match)
            if match_group:
                await self.upload_replays(
                    guild=interaction.guild,
                    group=match_group,
                    result=result,
                )
            else:
                log.error("Failed to retrieve or create a ballchasing group for match.")

        if match_group:
            url = await self.bc_group_full_url(match_group)
            embed.url = url

        if announce:
            await self.announce_to_score_reporting(
                guild=interaction.guild, tier=tier, embed=embed
            )

        await interaction.edit_original_response(embed=embed)

    @_ballchasing.command(
        name="scanmissing",
        description="Find missing matches in ballchasing",
    )
    @app_commands.describe(
        matchday="Match day to report (Optional: Defaults to current match day)",
        matchtype="Match type to find. (Default: Regular Season)",
    )
    async def _bc_scan_missing_matches(
        self,
        interaction: discord.Interaction,
        matchday: int | None = None,
        matchtype: MatchType = MatchType.REGULAR,
    ):
        await utils.not_implemented(interaction)

    @app_commands.command(
        name="reportmatch",
        description="Report the results of your RSC match",
    )
    @app_commands.autocomplete(
        home=TeamMixIn.teams_autocomplete,
        away=TeamMixIn.teams_autocomplete,
    )  # type: ignore
    @app_commands.describe(
        matchday="Match day number",
        home="Home team name",
        away="Away team name",
        replay1="Rocket League replay file",
        replay2="Rocket League replay file",
        replay3="Rocket League replay file",
        replay4="Rocket League replay file",
        replay5="Rocket League replay file",
        replay6="Rocket League replay file",
        replay7="Rocket League replay file",
        replay8="Rocket League replay file",
    )
    async def _reportmatch_cmd(
        self,
        interaction: discord.Interaction,
        matchday: int,
        home: str,
        away: str,
        replay1: discord.Attachment,
        preseason: bool = False,
        replay2: discord.Attachment | None = None,
        replay3: discord.Attachment | None = None,
        replay4: discord.Attachment | None = None,
        replay5: discord.Attachment | None = None,
        replay6: discord.Attachment | None = None,
        replay7: discord.Attachment | None = None,
        replay8: discord.Attachment | None = None,
    ):
        guild = interaction.guild
        member = interaction.user
        if not (guild and isinstance(member, discord.Member)):
            return

        argv = locals()
        replays: list[discord.Attachment] = []

        log.debug(f"Locals: {argv}")
        for k, v in argv.items():
            if v and k.startswith("replay"):
                replays.append(v)
        log.debug(f"Replay Count: {len(replays)}")

        await interaction.response.defer(ephemeral=True)

        # Get match data
        log.debug(f"Searching for match: {home} vs {away}")
        matches: list[Match] = await self.find_match(
            guild,
            day=matchday,
            teams=f"{home}, {away}",
            preseason=int(preseason),
            limit=1,
        )
        log.debug("Done searching")
        # No match found
        if not matches:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"No matches found for **{home}** vs **{away}** on match day **{matchday}**."
                ),
                ephemeral=True,
            )
            return

        match = None
        for m in matches:
            if home in (m.home_team.name, m.away_team.name) and away in (
                m.home_team.name,
                m.away_team.name,
            ):
                match = m

        if not match:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"No matches found for **{home}** vs **{away}** on match day **{matchday}**."
                ),
                ephemeral=True,
            )
            return

        log.debug("Match found in RSC API.")

        # Check if match is already complete
        if await self.match_already_complete(match):
            bc_view = discord.ui.View()
            if match.results.ballchasing_group:
                bc_view.add_item(
                    LinkButton(
                        label="Ballchasing Link",
                        url=await self.bc_group_full_url(
                            match.results.ballchasing_group
                        ),
                    )
                )
            await interaction.followup.send(
                embed=ErrorEmbed(
                    title="Match Completed",
                    description="This match has already been completed and recorded.",
                ),
                view=bc_view,
                ephemeral=True,
            )
            return

        # Check valid number of replays
        min_games = await self.minimum_games_required(match)
        if len(replays) < min_games:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    title="Not Enough Replays",
                    description=(
                        f"You only provided **{len(replays)}** replay file,"
                        f" expected at least **{match.num_games}**.\n\n"
                        "If you don't all the replays, please coordinate with the other team captain."
                    ),
                ),
                ephemeral=True,
            )
            return

        log.debug("Checking if attachments are replay files.")
        for r in replays:
            if not await self.is_replay_file(r):
                await interaction.followup.send(
                    embed=ErrorEmbed(
                        title="Invalid Replay File",
                        description=f"**{r.filename}** is not a valid Rocket League replay.",
                    ),
                    ephemeral=True,
                )

        log.debug("Checking for duplicate replays")
        if await self.duplicate_replay_files(replays):
            await interaction.followup.send(
                embed=ErrorEmbed(
                    title="Duplicate Replays Found",
                    description="Found duplicate replay files in the data submitted.",
                ),
                ephemeral=True,
            )
            return

        log.debug(f"Match ID: {match.id}")

        # Send "working" message
        await interaction.followup.send(
            embed=YellowEmbed(
                title="Processing Match",
                description=f"Processing replays for match **{home}** vs **{away}** on **match day {matchday}**",
            ),
            ephemeral=True,
        )

        bcresult = BallchasingResult(
            valid=True,
            away_wins=0,
            home_wins=0,
            match=m,
            replays=set(),
            execution_time=0,
            link=None,
        )

        # Upload

    # Functions

    @staticmethod
    async def is_replay_file(replay: discord.Attachment) -> bool:
        """Check if file provided is a replay file"""
        if replay.filename.endswith(".replay"):
            return True
        return False

    @staticmethod
    async def duplicate_replay_files(replays: list[discord.Attachment]) -> bool:
        hashes = []
        for r in replays:
            data = await r.read()
            h = md5(data).hexdigest()
            log.debug(f"Replay Hash: {h}")
            if h in hashes:
                return True
            else:
                hashes.append(h)
        return False

    async def group_replay_collisions(
        self, guild: discord.Guild, group: str, result: BallchasingResult
    ) -> BallchasingCollisions:
        collisions = set()
        unknown = set()
        total_replays = 0
        bapi = self._ballchasing_api.get(guild.id)

        if not bapi:
            raise RuntimeError("Ballchasing API is not configured.")

        async for replay in bapi.get_group_replays(
            group_id=group, deep=True, recurse=False
        ):
            total_replays += 1
            if replay in result["replays"]:
                collisions.add(replay)
            else:
                unknown.add(replay)

        return BallchasingCollisions(
            total_replays=total_replays,
            unknown=unknown,
            collisions=collisions,
        )

    async def upload_replays(
        self, guild: discord.Guild, group: str, result: BallchasingResult
    ) -> list[str]:
        bapi = self._ballchasing_api.get(guild.id)
        if not bapi:
            raise RuntimeError("Ballchasing API is not configured.")

        if not result["replays"]:
            return []

        match = result["match"]

        collisions = await self.group_replay_collisions(guild, group, result)
        if not collisions:
            return []

        total_collisions = len(collisions["collisions"])
        total_unknown = len(collisions["unknown"])
        total_replays = collisions["total_replays"]

        log.debug(
            f"Collision Report. Total={total_replays} Unknown={total_unknown} Collisions={total_collisions}"
        )
        min_games = await self.minimum_games_required(match)

        if total_collisions == min_games:
            # Match already uploaded
            log.debug("Match already uploaded. Skipping...")
            return [r.id for r in result["replays"]]
        elif total_unknown > 0:
            # To save on complexity, purge the group if an unknown match_guid is found
            log.warning("Unknown group replay found. Purging group...")
            await self.purge_ballchasing_group(guild, group)
        elif total_collisions > 0:
            # Remove collisions from upload list
            for replay in collisions["collisions"]:
                log.debug(f"Removing replay collision: {replay.id}")
                result["replays"].remove(replay)

        replay_content = []
        for replay in result["replays"]:
            data = await bapi.download_replay_content(replay.id)
            if data:
                replay_content.append(data)

        replay_ids = []
        for rbytes in replay_content:
            rname = f"{''.join(random.choices(string.ascii_letters + string.digits, k=64))}.replay"
            try:
                resp = await bapi.upload_replay_from_bytes(
                    name=rname,
                    replay_data=rbytes,
                    visibility=ballchasing.Visibility.PUBLIC,
                    group=group,
                )
                if resp:
                    replay_ids.append(resp.id)
            except ValueError as exc:
                log.debug(exc)
                err = exc.args[0]
                if err.status == 409:
                    # duplicate replay. patch it under the BC group
                    err_info = await err.json()
                    log.debug(f"Error uploading replay. {err.status} -- {err_info}")
                    r_id = err_info.get("id")
                    if r_id:
                        log.debug("Patching replay under correct group")
                        await bapi.patch_replay(r_id, group=group)
                        replay_ids.append(r_id)
        return replay_ids

    async def purge_ballchasing_group(self, guild: discord.Guild, group: str):
        bapi = self._ballchasing_api.get(guild.id)
        if not bapi:
            raise RuntimeError("Ballchasing API is not configured.")
        try:
            async with asyncio.TaskGroup() as tg:
                async for replay in bapi.get_group_replays(
                    group_id=group, deep=False, recurse=False
                ):
                    tg.create_task(bapi.delete_replay(replay.id))
        except ExceptionGroup as eg:
            for err in eg.exceptions:
                raise err

    async def season_bc_group(self, guild: discord.Guild, match: Match) -> str | None:
        tlg = await self._get_top_level_group(guild)
        if not tlg:
            return None

        bapi = self._ballchasing_api.get(guild.id)
        if not bapi:
            return None

        sname = f"Season {match.home_team.latest_season}"

        season_group = None

        # Find relevant season group
        async for g in bapi.get_groups(group=tlg):
            if g.name.lower() == sname.lower():
                log.debug(f"Found existing ballchasing season group: {g.id}")
                season_group = g.id
                break

        # Create group if not found
        if not season_group:
            log.debug(f"Creating ballchasing season group: {sname}")
            result = await bapi.create_group(
                name=sname,
                parent=tlg,
                player_identification=ballchasing.PlayerIdentificationBy.ID,
                team_identification=ballchasing.TeamIdentificationBy.CLUSTERS,
            )
            season_group = result.id
        return season_group

    async def tier_bc_group(self, guild: discord.Guild, match: Match) -> str | None:
        tlg = await self._get_top_level_group(guild)
        if not tlg:
            return None

        bapi = self._ballchasing_api.get(guild.id)
        if not bapi:
            return None

        season_group = await self.season_bc_group(guild, match)
        if not season_group:
            return None

        tname = match.home_team.tier
        tier_group = None

        # Find relevant server group
        async for g in bapi.get_groups(group=season_group):
            if g.name.lower() == tname.lower():
                log.debug(f"Found existing ballchasing tier group: {g.id}")
                tier_group = g.id
                break

        # Create group if not found
        if not tier_group:
            log.debug(f"Creating ballchasing tier group: {tname}")
            result = await bapi.create_group(
                name=tname,
                parent=season_group,
                player_identification=ballchasing.PlayerIdentificationBy.ID,
                team_identification=ballchasing.TeamIdentificationBy.CLUSTERS,
            )
            tier_group = result.id
        return tier_group

    async def match_day_bc_group(
        self, guild: discord.Guild, match: Match
    ) -> str | None:
        tlg = await self._get_top_level_group(guild)
        if not tlg:
            return None

        bapi = self._ballchasing_api.get(guild.id)
        if not bapi:
            return None

        tier_group = await self.tier_bc_group(guild, match)
        if not tier_group:
            return None

        mdname = f"Match Day {match.day:02d}"
        md_group = None

        # Find relevant server group
        async for g in bapi.get_groups(group=tier_group):
            if g.name.lower() == mdname.lower():
                log.debug(f"Found existing ballchasing match day group: {g.id}")
                md_group = g.id
                break

        # Create group if not found
        if not md_group:
            log.debug(f"Creating match day ballchasing group: {mdname}")
            result = await bapi.create_group(
                name=mdname,
                parent=tier_group,
                player_identification=ballchasing.PlayerIdentificationBy.ID,
                team_identification=ballchasing.TeamIdentificationBy.CLUSTERS,
            )
            md_group = result.id
        return md_group

    async def rsc_match_bc_group(
        self, guild: discord.Guild, match: Match
    ) -> str | None:
        tlg = await self._get_top_level_group(guild)
        if not tlg:
            return None

        bapi = self._ballchasing_api.get(guild.id)
        if not bapi:
            return None

        md_group = await self.match_day_bc_group(guild, match)
        if not md_group:
            return None

        mname = f"{match.home_team.name} vs {match.away_team.name}"
        match_group = None

        # Find relevant server group
        async for g in bapi.get_groups(group=md_group):
            if g.name.lower() == mname.lower():
                log.debug(f"Found existing ballchasing match group: {g.id}")
                match_group = g.id
                break

        # Create group if not found
        if not match_group:
            log.debug(f"Creating match ballchasing group: {mname}")
            result = await bapi.create_group(
                name=mname,
                parent=md_group,
                player_identification=ballchasing.PlayerIdentificationBy.ID,
                team_identification=ballchasing.TeamIdentificationBy.CLUSTERS,
            )
            match_group = result.id
        return match_group

    async def build_match_result_embed(
        self,
        guild: discord.Guild,
        result: BallchasingResult,
        link: str | None = None,
    ) -> discord.Embed:
        match = result["match"]
        tier_color = await utils.tier_color_by_name(guild, match.home_team.tier)

        embed = discord.Embed(
            title=f"MD {match.day}: {match.home_team.name} vs {match.away_team.name}",
            description=(
                "Match Summary:\n"
                f"**{match.home_team.name}** {result['home_wins']} - {result['away_wins']} **{match.away_team.name}**"
            ),
            color=tier_color,
            url=link,
        )

        if result["home_wins"] > result["away_wins"]:
            winning_franchise = match.home_team.franchise
        else:
            winning_franchise = match.away_team.franchise

        flogo = None
        fsearch = await self.franchises(guild, name=winning_franchise)
        if fsearch:
            f = fsearch.pop()
            if f.id:
                flogo = await self.franchise_logo(guild=guild, id=f.id)
            if flogo:
                embed.set_thumbnail(url=flogo)

        return embed

    async def announce_to_stats_committee(
        self,
        guild: discord.Guild,
        embed: discord.Embed,
        content: str | None = None,
        files: list[discord.File] | None = None,
    ) -> discord.Message | None:
        if files is None:
            files = []
        log_channel = await self._get_bc_log_channel(guild)
        if not log_channel:
            return None

        return await log_channel.send(content=content, embed=embed, files=files)

    async def announce_to_score_reporting(
        self,
        guild: discord.Guild,
        tier: str,
        embed: discord.Embed,
        content: str | None = None,
        files: list[discord.File] | None = None,
    ) -> discord.Message | None:
        if files is None:
            files = []

        category = await self._get_score_reporting_category(guild)
        if not category:
            log.warning(
                f"[{guild.name}] Ballchasing score report category is not configured"
            )
            return None

        cname = f"{tier.lower()}-score-reporting"

        score_channel = discord.utils.get(category.channels, name=cname)
        if not score_channel:
            log.warning(
                f"[{guild.name}] Unable to find tier score report channel: {cname}"
            )
            return None

        if not isinstance(score_channel, discord.TextChannel):
            return None

        return await score_channel.send(content=content, embed=embed, files=files)

    async def create_and_upload_replays(
        self, guild: discord.Guild, result: BallchasingResult
    ) -> str:
        match = result["match"]
        mgroup = await self.rsc_match_bc_group(guild, match)
        if not mgroup:
            raise RuntimeError("Failed to create ballchasing group")

        await self.upload_replays(guild, mgroup, result)
        return mgroup

    async def process_match(
        self, guild: discord.Guild, match: Match
    ) -> BallchasingResult:
        log.debug(
            f"Searching ballchasing for {match.home_team.name} vs {match.away_team.name}"
        )

        st = time.time()

        result = BallchasingResult(
            valid=False,
            match=match,
            home_wins=0,
            away_wins=0,
            replays=set(),
            execution_time=0,
            link=None,
        )

        # Get trackers
        log.debug("Fetching trackers")
        trackers = await self.get_all_trackers(guild, match)
        log.debug(f"Found {len(trackers)} trackers")

        replays = set()
        steam_trackers = [t for t in trackers if t.platform == "STEAM"]
        other_trackers = [t for t in trackers if t.platform != "STEAM"]

        min_games = await self.minimum_games_required(match)
        log.debug(f"Minimum match games required for upload: {min_games}")

        # Check steam first, provides better results by uploader search.
        log.debug("Finding games from STEAM trackers")
        for acc in steam_trackers:
            found = await self.find_match_replays(guild, match, acc)
            replays.update(found)
            if len(replays) >= min_games:
                break

        # Search other trackers if set not found
        if not replays or len(replays) < 4:
            log.debug("Valid replay set not found. Checking other trackers.")
            for acc in other_trackers:
                found = await self.find_match_replays(guild, match, acc)
                replays.update(found)
                if len(replays) >= min_games:
                    break

        # Second chance check for valid replay set
        if len(replays) != min_games:
            log.warning(
                f"[{match.home_team.name} vs {match.away_team.name}] Found {len(replays)} replays but expected {min_games}"
            )
        else:
            log.debug(f"Found valid set of {len(replays)} replays")
            result["valid"] = True

        et = time.time()
        exc_time = et - st

        hwins, awins = await self.team_win_count(match, replays)

        result["execution_time"] = exc_time
        result["home_wins"] = hwins
        result["away_wins"] = awins
        result["replays"] = replays
        return result

    async def find_match_replays(
        self, guild: discord.Guild, match: Match, tracker: TrackerLink
    ) -> set[ballchasing.models.Replay]:
        after, before = await self.get_bc_date_range(match)
        log.debug(f"Ballchasing Date Range. After: {after} Before: {before}")
        bapi = self._ballchasing_api[guild.id]

        replays: set[ballchasing.models.Replay] = set()
        min_games = await self.minimum_games_required(match)

        if tracker.platform == "STEAM":
            log.debug(f"Searching tracker: {tracker.platform_id}")
            async for r in bapi.get_replays(
                playlist=ballchasing.Playlist.PRIVATE,
                sort_by=ballchasing.ReplaySortBy.REPLAY_DATE,
                sort_dir=ballchasing.SortDir.ASCENDING,
                replay_after=after,
                replay_before=before,
                uploader=tracker.platform_id,
                deep=True,
            ):
                if await self.valid_replay(match, r):
                    log.debug(f"Found Match: {r.id}")
                    replays.add(r)

                if len(replays) == min_games:
                    break
        else:
            if not tracker.name:
                return replays

            log.debug(f"Searching {tracker.platform} tracker: {tracker.name}")
            async for r in bapi.get_replays(
                playlist=ballchasing.Playlist.PRIVATE,
                sort_by=ballchasing.ReplaySortBy.REPLAY_DATE,
                sort_dir=ballchasing.SortDir.ASCENDING,
                replay_after=after,
                replay_before=before,
                player_name=tracker.name,
                deep=True,
            ):
                if await self.valid_replay(match, r):
                    log.debug(f"Found Match: {r.id}")
                    # Avoid duplicate match_guids
                    if r in replays:
                        log.debug("Duplicate replay")
                    else:
                        replays.add(r)

                if len(replays) == min_games:
                    break
        return replays

    async def get_all_trackers(
        self, guild: discord.Guild, match: Match
    ) -> list[TrackerLink]:
        if not (match.home_team.players or match.away_team.players):
            return []

        tasks = []
        trackers: list[TrackerLink] = []

        if not (match.home_team.players and match.away_team.players):
            return []

        async with asyncio.TaskGroup() as tg:
            for p in match.home_team.players:
                log.debug(f"Fetching trackers for {p.name}")
                tasks.append(
                    tg.create_task(self.trackers(guild=guild, player=p.discord_id))
                )

            for p in match.away_team.players:
                log.debug(f"Fetching trackers for {p.name}")
                tasks.append(
                    tg.create_task(self.trackers(guild=guild, player=p.discord_id))
                )

        for task in tasks:
            trackers.extend(
                [r for r in task.result() if r.status != TrackerLinksStatus.FAILED]
            )
        return trackers

    async def get_bc_date_range(self, match: Match) -> tuple[datetime, datetime]:
        """Return ballchasing match time search range"""
        if not match.var_date:
            raise ValueError("Match has no date attribute.")
        match_date = match.var_date
        log.debug(f"BC Match Date: {match_date}")
        after = match_date.replace(hour=21, minute=55, second=0).astimezone(
            tz=timezone.utc
        )
        before = match_date.replace(hour=23, minute=59, second=0).astimezone(
            tz=timezone.utc
        )
        return after, before

    async def valid_replay(
        self, match: Match, replay: ballchasing.models.Replay
    ) -> bool:
        # Both team names are present
        if not await self.validate_team_names(match, replay):
            return False
        # Duration >= 300 seconds (5 minute game)
        if replay.duration < 280:
            log.debug(f"Bad replay duration: {replay.duration}")
            return False
        # Deep relay search should return stats
        if not (replay.blue.stats and replay.orange.stats):
            log.debug("Stats not found in replay")
            return False
        # You can't win a game without a goal
        log.debug(
            f"Blue Goals: {replay.blue.stats.core.goals} Orange Goals: {replay.orange.stats.core.goals}"
        )
        total_goals = replay.blue.stats.core.goals + replay.orange.stats.core.goals
        if total_goals <= 0:
            return False
        return True

    async def validate_team_names(
        self, match: Match, replay: ballchasing.models.Replay
    ) -> bool:
        home = match.home_team.name
        away = match.away_team.name

        if not (home and away):
            return False

        valid = (home.lower(), away.lower())

        if not (replay.blue and replay.orange):
            return False

        if not (replay.blue.name and replay.orange.name):
            return False

        log.debug(f"Blue: {replay.blue.name} Orange: {replay.orange.name}")

        if replay.blue.name.lower() in valid and replay.orange.name.lower() in valid:
            log.debug("Valid team names")
            return True

        # Similarity check (Levenshtein ratio)
        # Check both team names since people do dumb things
        home_lev1 = difflib.SequenceMatcher(
            None, valid[0], replay.blue.name.lower()
        ).ratio()
        home_lev2 = difflib.SequenceMatcher(
            None, valid[0], replay.orange.name.lower()
        ).ratio()

        away_lev1 = difflib.SequenceMatcher(
            None, valid[1], replay.blue.name.lower()
        ).ratio()
        away_lev2 = difflib.SequenceMatcher(
            None, valid[1], replay.orange.name.lower()
        ).ratio()

        log.debug(
            f"Levehstein Ratios. Home: {home_lev1:.3f} {home_lev2:.3f} Away: {away_lev1:.3f} {away_lev2:.3f}"
        )
        lev_threshold = 0.9
        if (home_lev1 > lev_threshold or home_lev2 > lev_threshold) and (
            away_lev1 > lev_threshold or away_lev2 > lev_threshold
        ):
            log.debug("Team names are close enough to threshold.")
            return True

        return False

    async def team_win_count(
        self, match: Match, replays: set[ballchasing.models.Replay]
    ) -> tuple[int, int]:
        home_wins = 0
        away_wins = 0

        if not (match.home_team.name and match.away_team.name):
            raise ValueError("Match is missing team name for one or both of the teams")

        home_name = match.home_team.name.lower()
        away_name = match.away_team.name.lower()
        for r in replays:
            if r.blue.stats.core.goals > r.orange.stats.core.goals:
                if home_name == r.blue.name.lower():
                    home_wins += 1
                else:
                    away_wins += 1
            else:
                if away_name == r.orange.name.lower():
                    away_wins += 1
                else:
                    home_wins += 1
        return (home_wins, away_wins)

    async def minimum_games_required(self, match: Match) -> int:
        match match.match_format:
            case MatchFormat.GAME_SERIES:
                return match.num_games  # type: ignore
            case MatchFormat.BEST_OF_THREE:
                return 2
            case MatchFormat.BEST_OF_FIVE:
                return 3
            case MatchFormat.BEST_OF_SEVEN:
                return 4
            case _:
                raise ValueError(f"Unknown Match Format: {match.match_format}")

    async def get_match_date_range(self, date: datetime) -> tuple[datetime, datetime]:
        """Return a tuple of datetime objects that has a search range for specified date"""
        date_gt = date - timedelta(minutes=1)
        date_lt = date.replace(hour=23, minute=59, second=59)
        return (date_gt, date_lt)

    async def match_already_complete(self, match: Match) -> bool:
        """Check if `Match` has been completed and recorded"""
        if not match.results:
            return False

        if not (
            hasattr(match.results, "home_wins") and hasattr(match.results, "away_wins")
        ):
            return False

        if not (match.results.home_wins and match.results.away_wins):
            return False

        if (match.results.home_wins + match.results.away_wins) != match.num_games:
            return False
        return True

    async def check_team_type_match(self, home: str, away: str, match: Match) -> bool:
        """Check if home and away team are correct"""
        if not (match.home_team.name and match.away_team.name):
            return False

        if home.lower() != match.home_team.name.lower():
            return False

        if away.lower() != match.away_team.name.lower():
            return False
        return True

    async def has_bc_permissions(self, member: discord.Member) -> bool:
        """Determine if member is able to manage guild or part of manager role"""
        # Guild Manager
        if member.guild_permissions.manage_guild:
            return True

        # BC Manager Role
        manager_role = await self._get_bc_manager_role(member.guild)
        if manager_role in member.roles:
            return True
        return False

    @staticmethod
    async def bc_group_full_url(group: str) -> str:
        return urljoin(BALLCHASING_URL, f"/group/{group}")

    @staticmethod
    async def bc_replay_full_url(replay: str) -> str:
        return urljoin(BALLCHASING_URL, f"/replay/{replay}")

    async def close_ballchasing_sessions(self):
        log.info("Closing ballchasing sessions")
        for bapi in self._ballchasing_api.values():
            await bapi.close()

    # Config

    async def _get_bc_auth_token(self, guild: discord.Guild) -> str:
        return await self.config.custom("Ballchasing", guild.id).AuthToken()

    async def _save_bc_auth_token(self, guild: discord.Guild, key: str):
        await self.config.custom("Ballchasing", guild.id).AuthToken.set(key)

    async def _save_top_level_group(self, guild: discord.Guild, group_id):
        await self.config.custom("Ballchasing", guild.id).TopLevelGroup.set(group_id)

    async def _get_top_level_group(self, guild: discord.Guild) -> str | None:
        return await self.config.custom("Ballchasing", guild.id).TopLevelGroup()

    async def _get_bc_log_channel(
        self, guild: discord.Guild
    ) -> discord.TextChannel | None:
        id = await self.config.custom("Ballchasing", guild.id).LogChannel()
        if not id:
            return None
        c = guild.get_channel(id)
        if not isinstance(c, discord.TextChannel):
            return None
        return c

    async def _save_bc_log_channel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ):
        await self.config.custom("Ballchasing", guild.id).LogChannel.set(channel.id)

    async def _get_bc_manager_role(self, guild: discord.Guild) -> discord.Role | None:
        r = await self.config.custom("Ballchasing", guild.id).ManagerRole()
        if not r:
            return None
        return guild.get_role(r)

    async def _save_bc_manager_role(self, guild: discord.Guild, role: discord.Role):
        await self.config.custom("Ballchasing", guild.id).ManagerRole.set(role.id)

    async def _save_score_reporting_category(
        self, guild, category: discord.CategoryChannel
    ):
        await self.config.custom("Ballchasing", guild.id).ReportCategory.set(
            category.id
        )

    async def _get_score_reporting_category(
        self, guild
    ) -> discord.CategoryChannel | None:
        c = await self.config.custom("Ballchasing", guild.id).ReportCategory()
        if not c:
            return None
        return guild.get_channel(c)
