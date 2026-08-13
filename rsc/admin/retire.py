import logging
from datetime import time

import discord
from discord.ext import tasks
from redbot.core import app_commands

from rsc.admin import AdminMixIn
from rsc.admin.models import DepartedReport
from rsc.admin.views import ConfirmRetireView
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    BlueEmbed,
    ErrorEmbed,
    ExceptionErrorEmbed,
    OrangeEmbed,
    SuccessEmbed,
    YellowEmbed,
)
from rsc.enums import Status
from rsc.exceptions import RscException
from rsc.logs import GuildLogAdapter
from rsc.utils import utils

logger = logging.getLogger("red.rsc.admin.retire")
log = GuildLogAdapter(logger)


# Offset from SYNC_LOOP_TIME (07:00) and SUB_LOOP_TIME (17:00) so the three
# league-wide loops do not contend for the API at once.
RETIRE_AUDIT_TIME = time(hour=9)

# Every status a player can hold while still expected to be in the server.
# `admin/sync.py` uses the same "not DROPPED/FORMER" test when warning about
# league players missing from the guild; BANNED is added because a ban removes
# them from the server by definition.
AUDIT_ACTIVE_STATUSES = frozenset(set(Status) - {Status.FORMER, Status.DROPPED, Status.BANNED})

# Guardrails. The failure mode this whole feature has to avoid is mass retiring
# real players because Discord handed us a bad member cache, so every one of
# these aborts the run rather than degrading it.
#
# A run that finds more than this fraction of the league missing is not
# believable -- the cache is far more likely to be wrong than the league.
AUDIT_ABORT_RATIO = 0.05
# ...but a small league legitimately crosses that ratio with a couple of leavers,
# so the ratio only bites once there are enough candidates for it to mean anything.
AUDIT_ABORT_FLOOR = 10
# Fraction of `guild.member_count` that must actually be in the cache after
# chunking before any `get_member` result can be trusted.
AUDIT_MIN_CACHE_RATIO = 0.9
# Every genuine departure is necessarily a cache miss, so the sweep needs a far
# higher HTTP fallback cap than the DM-batch default of 25.
AUDIT_MEMBER_FETCH_LIMIT = 250


class AdminRetireMixIn(AdminMixIn):
    """Reconciles league players against actual server membership.

    `on_raw_member_remove` retires players who leave, but Discord never replays
    gateway events: anyone who leaves while the bot is restarting, deploying, or
    resuming a dropped shard is missed permanently. This finds them after the
    fact.

    Deliberately split in two. The daily loop only ever *reports*; retiring is a
    manual, confirmed command. An automated sweep with write access is one bad
    member cache away from retiring the entire league.
    """

    def __init__(self):
        log.debug("Initializing AdminMixIn:Retire")
        super().__init__()

        if not self.retire_audit_loop.is_running():
            self.retire_audit_loop.start()

    # Tasks

    @tasks.loop(time=RETIRE_AUDIT_TIME)
    async def retire_audit_loop(self):
        """Report league players who are no longer in the server. Never writes."""
        log.info("Departed player audit loop is running.")
        for guild in list(self.bot.guilds):
            try:
                await self.run_retire_audit(guild)
            except Exception as exc:
                log.exception("Error auditing departed players.", guild=guild, exc_info=exc)
        log.info("Finished departed player audit loop.")

    @retire_audit_loop.before_loop
    async def before_retire_audit_loop(self):
        await self.bot.wait_until_ready()

    @retire_audit_loop.error
    async def retire_audit_loop_error(self, exc: BaseException):
        """Backstop. A loop that raises out of `_loop` never restarts on its own."""
        logger.error("Departed player audit loop crashed. Restarting.", exc_info=exc)
        self.retire_audit_loop.restart()

    async def run_retire_audit(self, guild: discord.Guild) -> DepartedReport | None:
        """Audit one guild and post the report to its league events channel."""
        if not await self._get_retire_audit_enabled(guild):
            return None

        if not (self._api_conf.get(guild.id) and self._league.get(guild.id)):
            log.debug("Guild is not prepared. Skipping departed player audit.", guild=guild)
            return None

        # The report has nowhere to go otherwise, and the audit is not cheap.
        if not await self._get_event_channel(guild):
            log.debug("No league event channel configured. Skipping departed player audit.", guild=guild)
            return None

        report = await self.find_departed_players(guild)
        await self._try_post_embeds(guild, [self.build_departed_embed(guild, report)])
        return report

    # Audit

    async def find_departed_players(self, guild: discord.Guild) -> DepartedReport:
        """Find league players who are active in the API but gone from the server.

        Read-only. Returns a report; acting on it is the caller's decision.
        """
        report = DepartedReport()

        # G0 - gateway health. A sweep during an outage is worse than no sweep.
        if self.bot.is_closed() or guild.unavailable or guild.member_count is None:
            report.aborted = "The bot is not fully connected to Discord. Member data cannot be trusted right now."
            log.warning("Aborting departed player audit: gateway is not healthy.", guild=guild)
            return report

        # G1 - chunking is mandatory here, not best effort. `_resolve_members_by_id`
        # degrades gracefully on a chunk failure, but for a league wide sweep that
        # produces a useless run instead of a wrong one. Better to say so.
        if not await self._ensure_chunked(guild):
            report.aborted = "Could not load the server member list from Discord. No players were evaluated."
            log.warning("Aborting departed player audit: chunking failed.", guild=guild)
            return report

        cached = len(guild.members)
        if cached < guild.member_count * AUDIT_MIN_CACHE_RATIO:
            report.aborted = (
                f"The member cache holds {cached} of {guild.member_count} members, "
                f"below the {AUDIT_MIN_CACHE_RATIO:.0%} required to trust it."
            )
            log.warning(f"Aborting departed player audit: thin member cache ({cached}/{guild.member_count}).", guild=guild)
            return report

        active: dict[int, str] = {}
        async for player in self.paged_players(guild=guild):
            discord_id = player.player.discord_id if player.player else None
            if not discord_id:
                continue
            if player.status not in AUDIT_ACTIVE_STATUSES:
                continue
            active[discord_id] = self._describe_player(player)

        report.total_active = len(active)
        if not active:
            log.info("No active league players to audit.", guild=guild)
            return report

        # G2 - only positively confirmed departures count. `left_guild` holds IDs
        # where `guild.fetch_member` raised NotFound, i.e. Discord itself said they
        # are gone. `lookup_failed` is "could not tell" and is never actionable, and
        # a bare `get_member` cache miss never reaches either bucket.
        _found, left_guild, lookup_failed = await self._resolve_members_by_id(
            guild,
            list(active.keys()),
            fetch_limit=AUDIT_MEMBER_FETCH_LIMIT,
        )

        report.lookup_failed = lookup_failed
        report.labels = {pid: active[pid] for pid in left_guild + lookup_failed if pid in active}

        # G3 - a believability threshold on the result itself, in case a partially
        # populated cache slipped past G1.
        ratio = len(left_guild) / max(report.total_active, 1)
        if len(left_guild) >= AUDIT_ABORT_FLOOR and ratio > AUDIT_ABORT_RATIO:
            report.aborted = (
                f"{len(left_guild)} of {report.total_active} active players ({ratio:.1%}) appear to have left, "
                f"above the {AUDIT_ABORT_RATIO:.0%} sanity limit. This is far more likely to be a Discord "
                "problem than a league one, so no players are listed as actionable."
            )
            log.error(
                f"Aborting departed player audit: {len(left_guild)}/{report.total_active} players appear departed.",
                guild=guild,
            )
            return report

        report.departed = left_guild
        log.info(
            f"Departed player audit: {len(left_guild)} departed, {len(lookup_failed)} unverified, {report.total_active} active.",
            guild=guild,
        )
        return report

    @staticmethod
    def _describe_player(player) -> str:  # noqa: ANN001 - rscapi LeaguePlayer
        """One line of context per player for the report."""
        status = getattr(player.status, "full_name", None) or str(player.status)
        team = getattr(player.team, "name", None)
        franchise = getattr(getattr(player.team, "franchise", None), "name", None)
        if team and franchise:
            return f"{status} - {team} ({franchise})"
        return str(status)

    def build_departed_embed(self, guild: discord.Guild, report: DepartedReport) -> discord.Embed:
        if report.aborted:
            embed = ErrorEmbed(
                title="Departed Player Audit Aborted",
                description=f"{report.aborted}\n\nNo action was taken.",
            )
            return embed

        if not report.departed and not report.lookup_failed:
            return SuccessEmbed(
                title="Departed Player Audit",
                description=f"All **{report.total_active}** active league players are still in the server.",
            )

        embed_cls = OrangeEmbed if report.departed else YellowEmbed
        embed = embed_cls(
            title="Departed Player Audit",
            description=(
                f"**{len(report.departed)}** active league player(s) are no longer in the server "
                f"out of **{report.total_active}** checked.\n\n"
                "These were missed by the automatic retirement on leave, usually because the bot "
                "was offline when they left. Run `/admin retire departed` to review and retire them."
            ),
        )

        if report.departed:
            embed.add_field(
                name="Departed",
                value=self._format_truncated_list([f"<@{pid}> `{pid}` - {report.labels.get(pid, 'Unknown')}" for pid in report.departed]),
                inline=False,
            )
        if report.lookup_failed:
            embed.add_field(
                name="Could Not Verify",
                value=self._format_truncated_list([f"`{pid}`" for pid in report.lookup_failed]),
                inline=False,
            )

        embed.set_footer(text=f"{guild.name} - departed player audit")
        return embed

    # Group

    _retire = app_commands.Group(
        name="retire",
        description="Retire league players who are no longer in the server",
        parent=AdminMixIn._admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @_retire.command(
        name="departed",
        description="Review and retire league players who are no longer in the server",
    )
    @app_commands.describe(apply="Actually retire the listed players. Defaults to a dry run that only shows them.")
    async def _admin_retire_departed_cmd(self, interaction: discord.Interaction, apply: bool = False):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        await utils.safe_defer(interaction, ephemeral=True)

        try:
            report = await self.find_departed_players(guild)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        if report.aborted:
            return await interaction.followup.send(embed=self.build_departed_embed(guild, report), ephemeral=True)

        if not report.departed:
            return await interaction.followup.send(embed=self.build_departed_embed(guild, report), ephemeral=True)

        preview = self.build_departed_embed(guild, report)

        if not apply:
            preview.set_footer(text="Dry run. Re-run with apply: True to retire these players.")
            return await interaction.followup.send(embed=preview, ephemeral=True)

        confirm = ConfirmRetireView(interaction, count=len(report.departed))
        await confirm.prompt(embed=preview)
        await confirm.wait()
        if not confirm.result:
            return None

        try:
            result = await self.bulk_retire_players(
                guild,
                executor=interaction.user,
                discord_ids=report.departed,
                notes="Reconciliation: player is no longer in the discord server",
            )
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
        except RuntimeError as exc:
            return await interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(exc)), ephemeral=True)

        embed = self.build_bulk_retire_embed(result, title="Departed Player Retirement Complete")
        embed.set_footer(text=f"Run by {interaction.user.display_name}")

        # Mirror to the events channel so there is a durable audit trail of who
        # ran this and what it changed.
        await self._try_post_embeds(guild, [embed])
        return await interaction.followup.send(embed=embed, ephemeral=True)

    @_retire.command(
        name="audit",
        description="Toggle the daily departed player audit report on or off",
    )
    async def _admin_retire_audit_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        status = not await self._get_retire_audit_enabled(guild)
        await self._set_retire_audit_enabled(guild, status)

        channel = await self._get_event_channel(guild)
        embed = BlueEmbed(
            title="Departed Player Audit",
            description=f"Daily departed player audit is now **{'enabled' if status else 'disabled'}**.",
        )
        if status and not channel:
            embed.add_field(
                name="Warning",
                value="No league event channel is configured, so the report has nowhere to post.",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # Config

    async def _get_retire_audit_enabled(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Admin", str(guild.id)).RetireAuditEnabled()

    async def _set_retire_audit_enabled(self, guild: discord.Guild, enabled: bool):
        await self.config.custom("Admin", str(guild.id)).RetireAuditEnabled.set(enabled)
