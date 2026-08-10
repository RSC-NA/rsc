import asyncio
import logging
import math
import random
import string
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urljoin

import aiohttp
import ballchasing
import discord
from ballchasing.exceptions import BackoffLimitExceeded, BallchasingFault, DuplicateReplay, UserFault
from redbot.core import app_commands
from rscapi.models.match import Match
from rscapi.models.match_results import MatchResults

from rsc.abc import RSCMixIn
from rsc.ballchasing import groups, process, validation
from rsc.ballchasing.modals import ReportMatchModal
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    ErrorEmbed,
    ExceptionErrorEmbed,
    SuccessEmbed,
    YellowEmbed,
)
from rsc.enums import MatchFormat, MatchType, PostSeasonType
from rsc.exceptions import RscException
from rsc.logs import GuildLogAdapter
from rsc.teams import TeamMixIn
from rsc.utils import utils
from rsc.views import LinkButton

logger = logging.getLogger("red.rsc.ballchasing")
log = GuildLogAdapter(logger)

defaults_guild = {
    "AuthToken": None,
    "TopLevelGroup": None,
    "LogChannel": None,
    "ManagerRole": None,
    "ReportCategory": None,
}

BALLCHASING_URL = "https://ballchasing.com"

# Upper bound on one match report. Ballchasing backs off cubically on 429 and can
# stall for minutes; without a ceiling a wedged report holds the match lock until
# the Discord interaction token expires.
BC_REPORT_TIMEOUT = 300

# How long we remember which games we pushed into a ballchasing group. Only
# needs to outlive ballchasing's processing queue, since after that the group
# listing carries the stats we fingerprint from.
BC_LEDGER_TTL = 3600.0
BC_LEDGER_MAX_GROUPS = 512


@dataclass(slots=True)
class _LockEntry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    refs: int = 0


def normalize_scores(home: str, home_wins: int, away_wins: int, match: Match) -> tuple[int, int]:
    """Orient the reported scores to the API's home/away, not the reporter's.

    `get_match_from_list` accepts the teams in either order, so a reporter who
    names the away team first would otherwise have the result recorded backwards.
    """
    away_name = (match.away_team.name or "").casefold()
    if away_name and home.strip().casefold() == away_name:
        return away_wins, home_wins
    return home_wins, away_wins


def upload_summary(upload: process.ReplayUploadResult) -> str:
    parts = [f"Uploaded **{upload.uploaded}**"]
    if upload.skipped:
        parts.append(f"skipped **{upload.skipped}** duplicate(s)")
    if upload.failed:
        parts.append(f"failed **{upload.failed}**")
    return " · ".join(parts)


class BallchasingMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing BallchasingMixIn")

        self.config.init_custom("Ballchasing", 1)
        self.config.register_custom("Ballchasing", **defaults_guild)
        self._ballchasing_api: dict[int, ballchasing.Api] = {}

        # Serializes the whole read-dedup-upload-report sequence per match, and
        # group creation per guild. Match guard is always the outer lock.
        self._bc_match_locks: dict[tuple[int, int], _LockEntry] = {}
        self._bc_group_locks: dict[int, asyncio.Lock] = {}

        # guild id -> resolved ballchasing group ids. Group ids are immutable, so
        # this is only cleared when the API client is rebuilt.
        self._bc_group_cache: dict[int, groups.GroupCache] = {}

        # (guild id, group id) -> {game fingerprint: (replay id, monotonic timestamp)}
        self._bc_upload_ledger: dict[tuple[int, str], dict[str, tuple[str, float]]] = {}
        super().__init__()

    # Setup

    async def prepare_ballchasing(self, guild: discord.Guild):
        token = await self._get_bc_auth_token(guild)
        log.debug("Preparing ballchasing API for guild", guild=guild)
        if not token:
            return
        token = token.strip()

        # setup() re-runs on every on_ready(). Rebuilding unconditionally would
        # close the ClientSession out from under an in-flight /reportmatch, so
        # only do it when the token actually changed.
        existing = self._ballchasing_api.get(guild.id)
        if existing is not None and existing.auth_key == token:
            log.debug("Ballchasing API already configured", guild=guild)
            return

        self._ballchasing_api[guild.id] = await ballchasing.Api.create(auth_key=token)
        self._bc_group_cache.pop(guild.id, None)

        if existing is not None:
            try:
                await existing.close()
            except Exception as exc:
                log.warning(f"Error closing stale ballchasing session: {exc}", guild=guild)

    # Concurrency

    @asynccontextmanager
    async def bc_match_guard(self, guild: discord.Guild, match_id: int) -> AsyncIterator[_LockEntry]:
        """Serialize match reporting so two reporters cannot duplicate each other's work."""
        key = (guild.id, match_id)
        entry = self._bc_match_locks.setdefault(key, _LockEntry())
        # Refcount rather than checking lock.locked() on the way out: release()
        # clears the flag before the woken waiter re-acquires, so a locked()
        # check would drop the entry and hand the next caller a fresh lock.
        entry.refs += 1
        try:
            async with entry.lock:
                yield entry
        finally:
            entry.refs -= 1
            if entry.refs == 0 and self._bc_match_locks.get(key) is entry:
                del self._bc_match_locks[key]

    # Upload ledger

    def _ledger_record(self, guild: discord.Guild, group: str, fingerprint: str, replay_id: str) -> None:
        bucket = self._bc_upload_ledger.setdefault((guild.id, group), {})
        bucket[fingerprint] = (replay_id, time.monotonic())
        if len(self._bc_upload_ledger) > BC_LEDGER_MAX_GROUPS:
            self._ledger_sweep()

    def _ledger_read(self, guild: discord.Guild, group: str) -> dict[str, str]:
        """Live fingerprint -> replay id entries for a group, pruning expired ones."""
        key = (guild.id, group)
        bucket = self._bc_upload_ledger.get(key)
        if not bucket:
            return {}

        cutoff = time.monotonic() - BC_LEDGER_TTL
        for stale in [f for f, (_, ts) in bucket.items() if ts < cutoff]:
            del bucket[stale]
        if not bucket:
            del self._bc_upload_ledger[key]
            return {}
        return {fingerprint: replay_id for fingerprint, (replay_id, _) in bucket.items()}

    def _ledger_sweep(self) -> None:
        cutoff = time.monotonic() - BC_LEDGER_TTL
        for key in list(self._bc_upload_ledger):
            bucket = self._bc_upload_ledger[key]
            for stale in [f for f, (_, ts) in bucket.items() if ts < cutoff]:
                del bucket[stale]
            if not bucket:
                del self._bc_upload_ledger[key]

    # Settings

    _ballchasing: app_commands.Group = app_commands.Group(
        name="ballchasing",
        description="Ballchasing commands and configuration",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # Sub Commands

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
        token = "Configured" if await self._get_bc_auth_token(guild) else "Not Configured"
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
        embed.add_field(name="Management Role", value=role.mention if role else "None", inline=False)
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

    @_ballchasing.command(name="key", description="Configure the Ballchasing API key for the server")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_key(self, interaction: discord.Interaction, key: str):
        if not interaction.guild:
            return
        await self._save_bc_auth_token(interaction.guild, key.strip())
        await interaction.response.send_message(
            embed=SuccessEmbed(description="Ballchasing API key have been successfully configured"),
            ephemeral=True,
        )

    @_ballchasing.command(name="ping", description="Test the Ballchasing API key connectivity")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_ping(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        bapi = self._ballchasing_api.get(guild.id)
        if not bapi:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Ballchasing API is not configured."),
                ephemeral=True,
            )
            return

        try:
            result = await bapi.ping()
        except Exception as exc:
            await interaction.response.send_message(
                embed=ExceptionErrorEmbed(exc_message=f"Ballchasing API ping failed: {exc}"),
                ephemeral=True,
            )
            return

        embed = SuccessEmbed(
            title="Ballchasing API Ping",
            description="API key is valid and ballchasing is reachable.",
        )
        embed.add_field(name="Steam Name", value=result.name, inline=True)
        embed.add_field(name="Steam ID", value=result.steam_id, inline=True)
        embed.add_field(name="Patreon Type", value=result.type.value, inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_ballchasing.command(
        name="manager",
        description="Configure the ballchasing management role (Ex: @Stats Committee)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_management_role(self, interaction: discord.Interaction, role: discord.Role):
        if not interaction.guild:
            return
        await self._save_bc_manager_role(interaction.guild, role)
        await interaction.response.send_message(
            embed=SuccessEmbed(description=f"Ballchasing management role set to {role.mention}"),
            ephemeral=True,
        )

    @_ballchasing.command(
        name="log",
        description="Configure the logging channel for Ballchasing commands (Ex: #stats-committee)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.guild:
            return
        await self._save_bc_log_channel(interaction.guild, channel)
        await interaction.response.send_message(
            embed=SuccessEmbed(description=f"Ballchasing log channel set to {channel.mention}"),
            ephemeral=True,
        )

    @_ballchasing.command(
        name="category",
        description="Configure the score reporting category for the server",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_score_category(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        if not interaction.guild:
            return

        await self._save_score_reporting_category(interaction.guild, category)
        await interaction.response.send_message(
            embed=SuccessEmbed(description=f"Score reporting category set to **{category.name}**"),
            ephemeral=True,
        )

    @_ballchasing.command(
        name="toplevelgroup",
        description="Configure the top level ballchasing group for RSC",
    )
    @app_commands.describe(group='Ballchasing group string (Ex: "rsc-v4rxmuxj6o")')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_top_level_group_cmd(self, interaction: discord.Interaction, group: str):
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
    )
    @app_commands.describe(
        home="Home team name",
        away="Away team name",
        day="Match day (Optional)",
        override="Admin or stats only override",
    )
    async def _reportmatch_cmd(
        self,
        interaction: discord.Interaction,
        home: str,
        away: str,
        day: int | None = None,
        override: bool = False,
    ):
        guild = interaction.guild
        member = interaction.user
        if not (guild and isinstance(member, discord.Member)):
            return

        # Check if override is allowed
        if override and not await self.has_bc_permissions(member):
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="You do not have permission to override a match result.")
            )

        report_modal = ReportMatchModal(home_team=home, away_team=away)
        await interaction.response.send_modal(report_modal)

        modal_timed_out = await report_modal.wait()
        if modal_timed_out:
            return
        log.debug("Report match modal finished...")

        log.debug(f"Home Wins: {report_modal.home_wins}")
        log.debug(f"Away Wins: {report_modal.away_wins}")
        log.debug(f"Num Replays: {len(report_modal.replays)}")

        home_wins = report_modal.home_wins
        away_wins = report_modal.away_wins
        replay_files: list[discord.Attachment] = report_modal.replays

        if not replay_files:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="No replays provided."),
                ephemeral=True,
            )

        # Validate score input
        if home_wins + away_wins <= 0:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Invalid score provided. At least one team must have a win."),
                ephemeral=True,
            )

        # Validate replays
        for replay in replay_files:
            if not await validation.is_replay_file(replay):
                return await interaction.followup.send(
                    embed=ErrorEmbed(description=f"`{replay.filename}` is not a valid replay file."),
                    ephemeral=True,
                )
        log.debug(f"Replay Count: {len(replay_files)}")

        # Read and parse every replay once. Everything downstream works off these
        # bytes instead of re-fetching the attachment.
        try:
            candidates = await process.build_candidates(replay_files)
        except process.ReplayParseError as exc:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=str(exc)),
                ephemeral=True,
            )
        except Exception as exc:
            log.exception(f"Error reading submitted replays: {exc}", exc_info=exc, guild=guild)
            return await interaction.followup.send(
                embed=ExceptionErrorEmbed(exc_message=str(exc)),
                ephemeral=True,
            )

        # Check for duplicates within this submission
        log.debug("Checking for duplicate replays")
        repeated = process.duplicate_in_batch(candidates)
        if repeated:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    title="Duplicate Replays Found",
                    description=(
                        f"`{repeated.label}` is the same game as another replay you attached. "
                        "Please make sure you have the correct files attached."
                    ),
                ),
                ephemeral=True,
            )

        # Get match search window
        tz = await self.timezone(guild)
        today = datetime.now(tz=tz)
        start_date = today - timedelta(days=7)
        end_date = today + timedelta(days=7)

        log.debug(f"Searching for match: {home} vs {away}. Start: {start_date}, End: {end_date}")
        mlist: list[Match] = await self.find_match(
            guild,
            match_type=MatchType.ANY,
            date_gt=start_date,
            date_lt=end_date,
            teams=[home, away],
            day=day,
        )

        # No match found
        if not mlist:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"No matches found for **{home}** vs **{away}**."),
                ephemeral=True,
            )

        log.debug("Searching for valid teams in match data")
        log.debug(f"Home Team: {home}")
        log.debug(f"Away Team: {away}")

        # Check if we got a match with matching home/away team names
        match = await self.get_match_from_list(home=home, away=away, matches=mlist)

        if not match:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"No matches found for **{home}** vs **{away}**."),
                ephemeral=True,
            )

        # Make sure we have the match ID
        if not match.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"Found match for **{home}** vs **{away}** but it has no match ID in the API."),
                ephemeral=True,
            )

        # Make sure we have a tier
        if not match.home_team.tier:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"Match **{home}** vs **{away}** is missing tier information in the API."),
                ephemeral=True,
            )
        log.debug(f"Found match: {match}", match=match)

        # Check score against match format for validation
        total_wins = home_wins + away_wins
        match match.match_format:
            case MatchFormat.BEST_OF_THREE | MatchFormat.BEST_OF_FIVE | MatchFormat.BEST_OF_SEVEN:
                if match.num_games and (total_wins < math.ceil(match.num_games / 2) or total_wins > match.num_games):
                    return await interaction.followup.send(
                        embed=ErrorEmbed(
                            description=f"Invalid score for match format. Total wins must match number of games: {match.num_games}"
                        ),
                        ephemeral=True,
                    )
            case _:  # Default GMS and anything else to all games must be played
                if match.num_games and (total_wins < match.num_games or total_wins > match.num_games):
                    return await interaction.followup.send(
                        embed=ErrorEmbed(
                            description=f"Invalid score for match format. Total wins must match number of games: {match.num_games}"
                        ),
                        ephemeral=True,
                    )

        # Reporter may have swapped home and away team names
        home_wins, away_wins = normalize_scores(home, home_wins, away_wins, match)

        # Only GMs and team members can report a match by default
        try:
            is_team_member = await self.discord_member_in_match(member, match)
            is_franchise_gm = await self.is_match_franchise_gm(member=member, match=match)
            is_admin = await self.has_bc_permissions(member)
        except AttributeError as exc:
            log.error(f"Match {match.id} is missing expected attributes: {exc}", match=match)
            return await interaction.followup.send(
                embed=ExceptionErrorEmbed(exc_message=str(exc)),
                ephemeral=True,
            )

        can_report = is_team_member or is_franchise_gm
        if override and is_admin:
            # Admin can submit with override
            can_report = True
        elif override and not is_admin:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="You do not have permission to override a match result."),
                ephemeral=True,
            )
        elif not can_report:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="You are not on one of the teams in this match."),
                ephemeral=True,
            )

        # Send "working" message
        queued = self.bc_match_report_in_progress(guild, match.id)
        embed = YellowEmbed(
            title="Processing Match",
            description=(
                f"Another report for **{home}** vs **{away}** is in progress. Waiting for it to finish."
                if queued
                else f"Processing replays for match **{home}** vs **{away}**."
            ),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        # One reporter at a time per match. Two teammates reporting the same match
        # concurrently would otherwise both find an empty group and both upload.
        try:
            async with self.bc_match_guard(guild, match.id), asyncio.timeout(BC_REPORT_TIMEOUT):
                try:
                    upload = await self.process_match_replays(guild, match=match, candidates=candidates)
                except Exception as exc:
                    log.exception(f"Error processing match replays: {exc}", exc_info=exc, guild=guild, match=match)
                    return await interaction.edit_original_response(embed=ExceptionErrorEmbed(exc_message=str(exc)))

                try:
                    match_result = await self.report_match(
                        guild,
                        match_id=match.id,
                        ballchasing_group=upload.group,
                        home_score=home_wins,
                        away_score=away_wins,
                        executor=member,
                        override=override,
                    )
                    log.debug(f"Match Result: {match_result}", match=match)
                except RscException as exc:
                    await self.report_upload_failures(guild, match=match, upload=upload)
                    if hasattr(exc, "status") and exc.status == 500:
                        # Match already reported
                        return await interaction.edit_original_response(
                            embed=YellowEmbed(
                                title="Match Reported",
                                description="This match has already been reported but all additional replays have been uploaded.",
                            )
                        )
                    else:
                        return await interaction.edit_original_response(embed=ApiExceptionErrorEmbed(exc))
        except TimeoutError:
            log.error(f"Timed out reporting match {match.id}", guild=guild, match=match)
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    title="Report Timed Out",
                    description="Ballchasing did not respond in time. Please try again in a few minutes.",
                )
            )

        await self.report_upload_failures(guild, match=match, upload=upload)

        # Final embed
        result_embed, result_view = await self.build_match_result_embed(
            guild,
            match=match,
            result=match_result,
            link=await self.bc_group_full_url(upload.group),
        )

        # Try to get GMs
        gms: list[str] = []
        if match.home_team.gm and match.home_team.gm.discord_id:
            home_gm = guild.get_member(match.home_team.gm.discord_id)
            if home_gm:
                gms.append(home_gm.mention)

        if match.away_team.gm and match.away_team.gm.discord_id:
            away_gm = guild.get_member(match.away_team.gm.discord_id)
            if away_gm:
                gms.append(away_gm.mention)

        gm_fmt = None
        if gms:
            gm_fmt = " ".join(gms)

        # Announce to score reporting. The public embed stays clean, upload
        # accounting is only useful to the person who submitted the files.
        await self.announce_to_score_reporting(
            guild,
            tier=match.home_team.tier,
            embed=result_embed,
            view=result_view,
            content=gm_fmt,
        )

        reporter_embed = result_embed.copy()
        reporter_embed.add_field(name="Replays", value=upload_summary(upload), inline=False)

        # Send to user
        try:
            await interaction.edit_original_response(embed=reporter_embed, view=result_view)
        except discord.errors.NotFound:
            # Original message not found, send a new one
            if result_view:
                await interaction.followup.send(embed=reporter_embed, view=result_view, ephemeral=True)
            else:
                await interaction.followup.send(embed=reporter_embed, ephemeral=True)

    # Functions

    def bc_match_report_in_progress(self, guild: discord.Guild, match_id: int) -> bool:
        """Whether someone else is already reporting this match."""
        entry = self._bc_match_locks.get((guild.id, match_id))
        return bool(entry and entry.lock.locked())

    async def process_match_replays(
        self, guild: discord.Guild, match: Match, candidates: Sequence[process.ReplayCandidate]
    ) -> process.ReplayUploadResult:
        """Resolve the match's ballchasing group and upload whatever is missing from it.

        The caller must hold `bc_match_guard` for this match. Group resolution and
        the duplicate check are both read-then-write against ballchasing, so
        concurrent callers would duplicate each other's work.
        """
        log.debug(
            f"Processing match: {match.home_team.name} vs {match.away_team.name}",
            guild=guild,
            match=match,
        )
        # Get BC top level group
        tlg = await self._get_top_level_group(guild)
        log.debug(f"Top Level Group: {tlg}", guild=guild, match=match)
        if not tlg:
            raise ValueError("Top level ballchasing group is not configured in guild.")

        # Get ballchasing API
        bapi = self._ballchasing_api.get(guild.id)
        if not bapi:
            raise ValueError("Ballchasing API is not configured in guild.")

        # Create or find RSC match group ID
        log.debug("Finding or creating match group in ballchasing", guild=guild, match=match)
        async with self._bc_group_locks.setdefault(guild.id, asyncio.Lock()):
            match_group_id = await groups.rsc_match_bc_group(
                bapi=bapi,
                guild=guild,
                tlg=tlg,
                match=match,
                cache=self._bc_group_cache.setdefault(guild.id, {}),
            )
        log.debug(f"Match Group ID: {match_group_id}", guild=guild, match=match)

        # Get replays from group if any
        log.debug(f"Getting existing replays from {match_group_id}", guild=guild, match=match)
        bc_replays: list[ballchasing.models.Replay] = await utils.async_iter_gather(
            bapi.get_group_replays(group_id=match_group_id, deep=True)
        )
        log.debug(f"Existing Replay Count: {len(bc_replays)}", guild=guild, match=match)

        # Check for collisions in ballchasing (duplicate replays)
        collisions = await process.replay_group_collisions(
            candidates=candidates,
            bc_replays=bc_replays,
            ledger=self._ledger_read(guild, match_group_id),
        )
        log.debug(f"Duplicate replays skipped: {len(collisions.duplicates)}", guild=guild, match=match)

        result = process.ReplayUploadResult(group=match_group_id)
        for candidate, replay_id in collisions.duplicates:
            result.outcomes.append(process.UploadOutcome(candidate=candidate, replay_id=replay_id, duplicate=True))

        # Upload replays (only if we need to)
        if collisions.upload:
            await self.upload_replays(guild, group=match_group_id, candidates=collisions.upload, result=result, match=match)
        else:
            log.debug("No new replays to upload", guild=guild, match=match)

        return result

    async def upload_replays(
        self,
        guild: discord.Guild,
        group: str,
        candidates: Sequence[process.ReplayCandidate],
        result: process.ReplayUploadResult | None = None,
        match: Match | None = None,
    ) -> process.ReplayUploadResult:
        if not candidates:
            raise ValueError("No replays provided for upload to ballchasing.")

        # Get ballchasing API
        bapi = self._ballchasing_api.get(guild.id)
        if not bapi:
            raise ValueError("Ballchasing API is not configured in guild.")

        if result is None:
            result = process.ReplayUploadResult(group=group)

        log.debug(f"Uploading replays to group: {group}", guild=guild, match=match)
        pending = list(candidates)
        while pending:
            candidate = pending.pop(0)
            outcome = process.UploadOutcome(candidate=candidate)
            result.outcomes.append(outcome)

            generated_name = "".join(random.choices(string.ascii_letters + string.digits, k=64))  # noqa: S311
            try:
                resp = await bapi.upload_replay_from_bytes(
                    name=f"{generated_name}.replay",
                    replay_data=candidate.data,
                    visibility=ballchasing.Visibility.PUBLIC,
                    group=group,
                )
                outcome.replay_id = resp.id
            except DuplicateReplay as exc:
                # Ballchasing already has these exact bytes. Move it into our group.
                log.debug(f"Duplicate replay on ballchasing: {exc}", guild=guild, match=match)
                if not exc.id:
                    outcome.error = "Ballchasing reported a duplicate replay but did not say which one."
                else:
                    outcome.duplicate = True
                    outcome.replay_id = exc.id
                    try:
                        await bapi.patch_replay(exc.id, group=group)
                    except Exception as patch_exc:
                        log.warning(f"Unable to move replay {exc.id} into {group}: {patch_exc}", guild=guild, match=match)
                        outcome.error = f"Could not move the existing replay into the match group: {patch_exc}"
            except BallchasingFault as exc:
                log.warning(f"Ballchasing failed to accept {candidate.label}: {exc}", guild=guild, match=match)
                outcome.error = "Ballchasing could not process this replay."
            except UserFault as exc:
                log.warning(f"Ballchasing rejected {candidate.label}: {exc}", guild=guild, match=match)
                outcome.error = str(exc)
            except BackoffLimitExceeded as exc:
                # Continuing guarantees more 429s and burns minutes of backoff
                # while holding the match lock. Fail the rest of the batch now.
                log.warning(f"Ballchasing rate limit exhausted: {exc}", guild=guild, match=match)
                outcome.error = "Ballchasing is rate limiting us. Please try again later."
                for skipped in pending:
                    result.outcomes.append(
                        process.UploadOutcome(candidate=skipped, error="Skipped after ballchasing rate limit was exhausted.")
                    )
                pending.clear()
            except (TimeoutError, aiohttp.ClientError) as exc:
                log.warning(f"Network error uploading {candidate.label}: {exc}", guild=guild, match=match)
                outcome.error = f"Network error while uploading: {exc}"

            # Record what we put in the group so the next reporter can dedup against
            # it even while ballchasing is still processing the upload.
            if outcome.replay_id and candidate.fingerprint:
                self._ledger_record(guild, group=group, fingerprint=candidate.fingerprint, replay_id=outcome.replay_id)

        log.debug(f"Ballchasing IDs: {result.replay_ids}", guild=guild, match=match)
        return result

    async def report_upload_failures(self, guild: discord.Guild, match: Match, upload: process.ReplayUploadResult) -> None:
        """Send replay upload failures to the stats committee log channel."""
        if not upload.failed:
            return

        embed = ErrorEmbed(
            title="Replay Upload Failures",
            description=(
                f"**{match.home_team.name}** vs **{match.away_team.name}** was reported but "
                f"{upload.failed} replay(s) did not make it into the group."
            ),
        )
        embed.add_field(
            name="Failures",
            value="\n".join(f"`{o.candidate.label}` — {o.error}" for o in upload.errors)[:1024],
            inline=False,
        )
        embed.add_field(name="Group", value=await self.bc_group_full_url(upload.group), inline=False)
        await self.announce_to_stats_committee(guild, embed=embed)

    async def build_match_result_embed(
        self,
        guild: discord.Guild,
        match: Match,
        result: MatchResults,
        link: str | None = None,
    ) -> tuple[discord.Embed, discord.ui.View | None]:
        tier_color = discord.Color.default()
        if match.home_team.tier:
            tier_color = await utils.tier_color_by_name(guild, match.home_team.tier)

        embed = discord.Embed(
            description=(f"Match Summary:\n**{match.home_team.name}** {result.home_wins} - {result.away_wins} **{match.away_team.name}**"),
            color=tier_color,
        )

        # This is an `ValueError` but we still want to display the report
        if not match.day:
            match.day = 0

        # Format embed title by match type
        if match.match_type == MatchType.PRESEASON:
            embed.title = f"Pre {match.day}: {match.home_team.name} vs {match.away_team.name}"
        elif match.match_type == MatchType.POSTSEASON:
            playoff_round = PostSeasonType(match.day).name.capitalize()
            embed.title = f"{playoff_round}: {match.home_team.name} vs {match.away_team.name}"
        else:
            embed.title = f"MD {match.day}: {match.home_team.name} vs {match.away_team.name}"

        # Ballchasing group link button
        bc_view = None
        if link:
            bc_view = discord.ui.View()
            bcbutton = LinkButton(label="Ballchasing Group", url=link)
            bc_view.add_item(bcbutton)

        # Get franchise logo
        tie = False
        if result.home_wins is not None and result.away_wins is not None and result.home_wins > result.away_wins:
            winning_franchise = match.home_team.franchise
        elif result.home_wins is not None and result.away_wins is not None and result.home_wins == result.away_wins:
            tie = True
        else:
            winning_franchise = match.away_team.franchise

        flogo = None
        if not tie:
            fsearch = await self.franchises(guild, name=winning_franchise)
            if fsearch:
                f = fsearch.pop()
                if f.id:
                    flogo = await self.franchise_logo(guild=guild, id=f.id)

        if flogo:
            embed.set_thumbnail(url=flogo)
        elif guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        return embed, bc_view

    async def announce_to_stats_committee(
        self,
        guild: discord.Guild,
        embed: discord.Embed,
        view: discord.ui.View | None = None,
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
        view: discord.ui.View | None = None,
        content: str | None = None,
        files: list[discord.File] | None = None,
    ) -> discord.Message | None:
        if files is None:
            files = []

        category = await self._get_score_reporting_category(guild)
        if not category:
            log.warning(f"[{guild.name}] Ballchasing score report category is not configured")
            return None

        cname = f"{tier.lower()}-score-reporting"

        score_channel = discord.utils.get(category.channels, name=cname)
        if not score_channel:
            log.warning(f"[{guild.name}] Unable to find tier score report channel: {cname}")
            return None

        if not isinstance(score_channel, discord.TextChannel):
            return None

        if view:
            return await score_channel.send(
                content=content,
                embed=embed,
                view=view,
                files=files,
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        else:
            return await score_channel.send(
                content=content,
                embed=embed,
                files=files,
                allowed_mentions=discord.AllowedMentions(users=True),
            )

    async def has_bc_permissions(self, member: discord.Member) -> bool:
        """Determine if member is able to manage guild or part of manager role"""
        # Guild Manager
        if member.guild_permissions.manage_guild:
            return True

        # BC Manager Role
        manager_role = await self._get_bc_manager_role(member.guild)
        return manager_role in member.roles

    @staticmethod
    async def bc_group_full_url(group: str) -> str:
        return urljoin(BALLCHASING_URL, f"/group/{group}")

    @staticmethod
    async def bc_replay_full_url(replay: str) -> str:
        return urljoin(BALLCHASING_URL, f"/replay/{replay}")

    async def close_ballchasing_sessions(self):
        log.info("Closing ballchasing sessions")
        for guild_id, bapi in list(self._ballchasing_api.items()):
            del self._ballchasing_api[guild_id]
            try:
                await bapi.close()
            except Exception as exc:
                log.warning(f"Error closing ballchasing session for guild {guild_id}: {exc}")

    # Config

    async def _get_bc_auth_token(self, guild: discord.Guild) -> str:
        return await self.config.custom("Ballchasing", str(guild.id)).AuthToken()

    async def _save_bc_auth_token(self, guild: discord.Guild, key: str):
        await self.config.custom("Ballchasing", str(guild.id)).AuthToken.set(key)

    async def _save_top_level_group(self, guild: discord.Guild, group_id: str):
        await self.config.custom("Ballchasing", str(guild.id)).TopLevelGroup.set(group_id)

    async def _get_top_level_group(self, guild: discord.Guild) -> str | None:
        return await self.config.custom("Ballchasing", str(guild.id)).TopLevelGroup()

    async def _get_bc_log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        id = await self.config.custom("Ballchasing", str(guild.id)).LogChannel()
        if not id:
            return None
        c = guild.get_channel(id)
        if not isinstance(c, discord.TextChannel):
            return None
        return c

    async def _save_bc_log_channel(self, guild: discord.Guild, channel: discord.TextChannel):
        await self.config.custom("Ballchasing", str(guild.id)).LogChannel.set(channel.id)

    async def _get_bc_manager_role(self, guild: discord.Guild) -> discord.Role | None:
        r = await self.config.custom("Ballchasing", str(guild.id)).ManagerRole()
        if not r:
            return None
        return guild.get_role(r)

    async def _save_bc_manager_role(self, guild: discord.Guild, role: discord.Role):
        await self.config.custom("Ballchasing", str(guild.id)).ManagerRole.set(role.id)

    async def _save_score_reporting_category(self, guild: discord.Guild, category: discord.CategoryChannel):
        await self.config.custom("Ballchasing", str(guild.id)).ReportCategory.set(category.id)

    async def _get_score_reporting_category(self, guild: discord.Guild) -> discord.CategoryChannel | None:
        c = await self.config.custom("Ballchasing", str(guild.id)).ReportCategory()
        if not c:
            return None

        category = guild.get_channel(c)
        if not isinstance(category, discord.CategoryChannel):
            log.warning(f"[{guild.name}] Score report channel is not a category channel.")
            return None
        return category
