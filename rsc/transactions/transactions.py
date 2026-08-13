import asyncio
import itertools
import logging
import re
from collections.abc import AsyncIterator
from datetime import datetime, time, timedelta
from pathlib import Path
from pprint import pformat

import discord
from discord.ext import tasks
from redbot.core import app_commands, commands
from rscapi import LeaguePlayersApi, TransactionsApi
from rscapi.exceptions import ApiException
from rscapi.models.draft_input import DraftInput
from rscapi.models.draft_pick_trade import DraftPickTrade
from rscapi.models.franchise_futures_validation import FranchiseFuturesValidation
from rscapi.models.franchise_futures_validation_response import FranchiseFuturesValidationResponse
from rscapi.models.ir_input import IRInput
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.player_input import PlayerInput
from rscapi.models.player_team_input import PlayerTeamInput
from rscapi.models.player_transaction_updates import PlayerTransactionUpdates
from rscapi.models.sub_input import SubInput
from rscapi.models.trade_franchise import TradeFranchise
from rscapi.models.trade_item import TradeItem
from rscapi.models.trade_object import TradeObject
from rscapi.models.trade_player import TradePlayer
from rscapi.models.trade_transaction import TradeTransaction
from rscapi.models.transaction_franchise import TransactionFranchise
from rscapi.models.transaction_response import TransactionResponse

from rsc.abc import RSCMixIn
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    BlueEmbed,
    ErrorEmbed,
    ExceptionErrorEmbed,
    SuccessEmbed,
    YellowEmbed,
)
from rsc.enums import INACTIVE_STATUS_VALUES, Status, TransactionType, is_inactive_status
from rsc.exceptions import (
    BadGateway,
    InternalServerError,
    MalformedTransactionResponse,
    MemberDoesNotExist,
    NotLeaguePlayer,
    RscException,
    TradeParserException,
    translate_api_error,
)
from rsc.franchises import FranchiseMixIn
from rsc.logs import GuildLogAdapter
from rsc.teams import TeamMixIn
from rsc.transactions.modals import CutMsgModal, TransactionAnnouncementModal
from rsc.transactions.trade_announce import announce_trade, apply_trade_role_updates
from rsc.transactions.roles import (
    update_cut_player_discord,
    update_nonplaying_discord,
    update_signed_player_discord,
    update_team_captain_discord,
)
from rsc.transactions.views import TradeAnnouncementModal
from rsc.types import Substitute, TransactionSettings
from rsc.utils import utils

logger = logging.getLogger("red.rsc.transactions")
log = GuildLogAdapter(logger)

PICK_TRADE_REGEX = re.compile(
    r"^(?P<gm>.+?)?(?:'s\s+)?(?P<round>\d)(?:st|nd|rd|th)\s+Round\s+(?P<tier>\w+)\s+\((?P<pick>\d{1,3})\)$",
    re.IGNORECASE,
)
FUTURE_TRADE_REGEX = re.compile(
    r"^(?P<gm>.+?)'s\s+S(?P<season>\d+)\s+(?P<round>\d)(?:st|nd|rd|th)\s+Round\s+(?P<tier>\w+)$",
    re.IGNORECASE,
)
GM_TRADE_REGEX = re.compile(r"^(?P<gm>.+?) receives:$", re.IGNORECASE)
PLAYER_TRADE_REGEX = re.compile(r"^@(?P<player>.+?)(?:\sto\s(?P<team>[a-z0-9\x20\x2d]+))?$", re.IGNORECASE)

defaults = TransactionSettings(
    TransChannel=None,
    TransDMs=False,
    TransLogChannel=None,
    TransNotifications=False,
    TransGMNotifications=False,
    TransRole=None,
    CutMessage=None,
    ContractExpirationMessage=None,
    Substitutes=[],
    TradeAnnouncements=True,
    TradeRoleUpdates=True,
    AnnouncedTrades=[],
)


# Noon - Eastern (-5) - Not DST aware
# Have to use UTC for loop. TZ aware object causes issues with clock drift calculations
SUB_LOOP_TIME = time(hour=17)


# Auto retire on leave.
#
# `rscapi.rest.ALLOW_RETRY_METHODS` excludes POST, so the aiohttp retry layer
# configured in `core.prepare_api` never replays a retire. This loop is the only
# retry that exists for it.
RETIRE_MAX_ATTEMPTS = 3
RETIRE_BACKOFF = (2.0, 5.0)  # Seconds to sleep before attempt 2 and 3.
RETRYABLE_RETIRE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

# Single prefix on every outcome of the leave handler so the whole flow can be
# grepped out of the bot logs with one string.
RETIRE_LOG_PREFIX = "auto-retire:"


def gm_discord_id(franchise: TransactionFranchise | None) -> int | None:
    """Discord ID of a franchise's GM, or `None` if it has neither.

    GMs are `FranchiseStaff` rows now and a franchise between GMs simply has
    none, so every read of `franchise.gm` has to tolerate a null.
    """
    if not (franchise and franchise.gm):
        return None
    return franchise.gm.discord_id


class TransactionMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing TransactionMixIn")
        # Prepare configuration group
        self.config.init_custom("Transactions", 1)
        self.config.register_custom("Transactions", **defaults)
        super().__init__()

        # Start sub expire loop
        if not self.expire_sub_contract_loop.is_running():
            self.expire_sub_contract_loop.start()

    # Tasks
    @tasks.loop(time=SUB_LOOP_TIME)
    async def expire_sub_contract_loop(self):
        """Send contract expiration message to Transaction Channel"""
        log.info("Expire sub contracts loop started")
        guilds: list[discord.Guild] = list(self.bot.guilds)
        for guild in guilds:
            log.info("Expire sub contract loop is running", guild=guild)
            subs: list[Substitute] = await self._get_substitutes(guild)
            if not subs:
                log.debug("No substitutes to expire", guild=guild)
                continue

            tchan = await self._trans_channel(guild)
            if not tchan or not hasattr(tchan, "send"):
                # Still need to remove player from sub list after.
                log.warning("Substitutes found but transaction channel not set", guild=guild)

            subbed_out_role = await utils.get_subbed_out_role(guild)

            guild_tz = await self.timezone(guild)
            yesterday = datetime.now(tz=guild_tz) - timedelta(1)

            # Get ContractExpired image
            img_path = Path(__file__).parent.parent / "resources/transactions/ContractExpired.png"

            # Loop through checkins.
            log.debug(f"Total substitute count: {len(subs)}", guild=guild)
            for s in subs:
                sub_date = datetime.fromisoformat(s["date"])
                dFiles = [discord.File(img_path)]
                if sub_date.date() <= yesterday.date():
                    # Get FA img resource
                    fa_icon = await utils.fa_img_from_tier(s["tier"], tiny=True)

                    # Tier color
                    tier_color = await utils.tier_color_by_name(guild, s["tier"])

                    # Get Member
                    m_in = guild.get_member(s["player_in"])
                    m_out = guild.get_member(s["player_out"])

                    m_in_fmt = m_in.display_name if m_in else f"<@!{s['player_in']}>"
                    m_out_fmt = m_out.display_name if m_out else f"<@!{s['player_out']}>"

                    log.debug(f"Expiring Sub Contract: {s['player_in']}", guild=guild)
                    embed = discord.Embed(color=tier_color)
                    embed.set_image(url=f"attachment://{img_path.name}")
                    if fa_icon:
                        dFiles.append(fa_icon)
                        embed.set_author(
                            name=f"{m_in_fmt} has finished temporary contract for {s['team']}",
                            icon_url=f"attachment://{fa_icon.filename}",
                        )
                    else:
                        embed.set_author(name=f"{m_in_fmt} has finished temporary contract for {s['team']}")

                    embed.add_field(
                        name="Player In",
                        value=m_out_fmt,
                        inline=True,
                    )
                    embed.add_field(
                        name="Player Out",
                        value=m_in_fmt,
                        inline=True,
                    )
                    embed.add_field(name="Franchise", value=s["franchise"], inline=True)

                    # Send ping for player/GM then quickly remove it
                    if tchan and hasattr(tchan, "send"):
                        pingstr = f"<@!{s['player_in']}> <@!{s['gm']}>"
                        tmsg = await tchan.send(
                            content=pingstr,
                            embed=embed,
                            files=dFiles,
                            allowed_mentions=discord.AllowedMentions(users=True),
                        )
                        await tmsg.edit(content=None, embed=embed)

                    await self._rm_substitute(guild, s)
                    if subbed_out_role and m_out:
                        await m_out.remove_roles(subbed_out_role)
                else:
                    log.debug(
                        f"{s['player_in']} is not ready to be expired. Sub Date: {s['date']}",
                        guild=guild,
                    )
        log.info("Finished expire substitute daily loop.")

    @expire_sub_contract_loop.before_loop
    async def before_expire_sub_contract_loop(self):
        await self.bot.wait_until_ready()

    @expire_sub_contract_loop.error
    async def expire_sub_contract_loop_error(self, exc: BaseException):
        """Backstop. A loop that raises out of `_loop` never restarts on its own."""
        logger.error("Substitute contract expiry loop crashed. Restarting.", exc_info=exc)
        self.expire_sub_contract_loop.restart()

    # Listeners

    @commands.Cog.listener("on_raw_member_remove")
    async def _transactions_on_member_remove(self, event: discord.RawMemberRemoveEvent):
        """Retire a league player who left the server.

        Nothing but a catch-all wrapper. An exception escaping here would be
        swallowed by discord.py's dispatcher and logged under `discord.client`
        rather than `red.rsc.transactions`, which is exactly how a missed
        retirement becomes invisible.
        """
        try:
            await self._handle_member_remove(event)
        except Exception as exc:
            logger.error(
                f"{RETIRE_LOG_PREFIX} leave handler crashed for {event.user.id} in guild {event.guild_id}",
                exc_info=exc,
            )

    async def _handle_member_remove(self, event: discord.RawMemberRemoveEvent):
        """Check if a rostered player has left the server and report to transaction log channel. Retire player"""
        guild = self.bot.get_guild(event.guild_id)
        member = event.user

        if not guild:
            log.warning(f"{RETIRE_LOG_PREFIX} member {member.id} left unknown guild {event.guild_id}. No action taken.")
            return

        # Listeners dispatch before `on_ready` finishes `_setup_guild`, and both
        # dicts are indexed bare downstream. Without this the retire dies on a
        # KeyError inside `api_client()`.
        if not (self._api_conf.get(guild.id) and self._league.get(guild.id)):
            log.error(
                f"{RETIRE_LOG_PREFIX} guild is not prepared yet. Retirement skipped for {member.display_name} ({member.id}).",
                guild=guild,
            )
            await self._report_retire_failure(guild, member, reason="Guild API/league configuration was not ready.")
            return

        # A lookup failure must never be mistaken for "not a league player".
        try:
            players = await self.players(guild, discord_id=member.id, limit=1)
        except Exception as exc:
            log.error(
                f"{RETIRE_LOG_PREFIX} pre-retire lookup failed for {member.display_name} ({member.id}). Retirement skipped.",
                guild=guild,
                exc_info=exc,
            )
            await self._report_retire_failure(guild, member, reason=f"Player lookup failed: {exc}")
            return

        if not players:
            # Member is not a league player, do nothing
            log.info(
                f"{RETIRE_LOG_PREFIX} {member.display_name} ({member.id}) left but has no league player record. No action taken.",
                guild=guild,
            )
            return

        player_before_retire = players[0]

        verified, failure_reason = await self._attempt_retire(guild, member)
        if not verified:
            log.error(
                f"{RETIRE_LOG_PREFIX} unable to retire {member.display_name} ({member.id}) "
                f"after {RETIRE_MAX_ATTEMPTS} attempt(s). Player may still be active in API. Reason: {failure_reason}",
                guild=guild,
            )
            await self._report_retire_failure(guild, member, reason=failure_reason)
            return

        # Check if user was forcibly removed from server. `get_audit_log_reason`
        # accepts a bare ID, so this works for an uncached `discord.User` too --
        # gating it on `isinstance(member, discord.Member)` meant the "Kicked by"
        # field was never populated after a restart.
        perp = None
        reason = None
        try:
            perp, reason = await utils.get_audit_log_reason(guild, member.id, discord.AuditLogAction.kick)
        except discord.HTTPException as exc:
            log.warning(f"{RETIRE_LOG_PREFIX} unable to read audit log for {member.id}: {exc}", guild=guild)

        log.info(
            f"{RETIRE_LOG_PREFIX} {member.display_name} ({member.id}) has left the server. Retirement verified. Reason: {reason}",
            guild=guild,
        )

        # Check if notifications are enabled. These gate two different channels,
        # so they have to be evaluated independently -- an AND here meant turning
        # off GM notifications also silenced the transaction committee.
        tm_notify = await self._notifications_enabled(guild)
        gm_notify = await self._gm_notifications_enabled(guild)
        if not (tm_notify or gm_notify):
            return

        tz = await self.timezone(guild)
        now = datetime.now(tz=tz)

        if not (player_before_retire.team and player_before_retire.team.franchise):
            log.info(
                f"{member.display_name} has no team. Skipping notifications...",
                guild=guild,
            )
            return

        fname = player_before_retire.team.franchise.name or "**Unknown Franchise**"
        retire_gm = player_before_retire.team.franchise.gm
        gm_id = (retire_gm.discord_id if retire_gm else None) or 0  # Has to be a better solution

        match player_before_retire.status:
            case Status.ROSTERED | Status.IR | Status.AGMIR | Status.RENEWED:
                desc = f"Player left server while rostered on **{fname}**"
            case Status.UNSIGNED_GM:
                desc = "A general manager has left the server."
            case _:
                # We only notify for specific statuses
                log.debug(
                    f"Not sending transaction notification. Player Status: {player_before_retire.status}",
                    guild=guild,
                )
                return

        log_embed = discord.Embed(
            description=desc,
            color=discord.Color.orange(),
            timestamp=now,
        )

        log_embed.add_field(name="Member", value=member.mention, inline=True)
        log_embed.add_field(name="Member ID", value=str(member.id), inline=True)

        if perp:
            log_embed.add_field(name="Kicked", value=perp.mention, inline=True)
        if reason:
            log_embed.add_field(name="Reason", value=str(reason), inline=False)

        log_embed.set_author(
            name=f"{member} ({member.id}) has left the guild",
            url=member.display_avatar,
            icon_url=member.display_avatar,
        )
        log_embed.set_thumbnail(url=member.display_avatar)

        # Ping Transaction Committee if role is configured and send embed to log
        # channel. `announce_to_transaction_committee` already no-ops when the
        # channel or role is unset, so there is no early return here -- bailing on
        # a missing log channel also suppressed the franchise announcement below,
        # which posts to an entirely different channel.
        #
        # A Discord failure must not look like a failed retirement. The API side
        # is already done by this point.
        if tm_notify:
            try:
                await self.announce_to_transaction_committee(
                    guild=guild,
                    embed=log_embed,
                )
            except discord.HTTPException as exc:
                log.warning(f"{RETIRE_LOG_PREFIX} unable to notify transaction committee for {member.id}: {exc}", guild=guild)

        # Ping GM and AGM in franchise transaction channel.
        if not player_before_retire.team:
            # Handle GM case
            return

        if gm_notify:
            try:
                await self.announce_to_franchise_transactions(
                    guild=guild,
                    franchise=fname,
                    gm=gm_id,
                    embed=log_embed,
                )
            except discord.HTTPException as exc:
                log.warning(f"{RETIRE_LOG_PREFIX} unable to notify {fname} transactions for {member.id}: {exc}", guild=guild)

    # Group

    _transactions = app_commands.Group(
        name="transactions",
        description="Transaction commands and configuration",
        guild_only=True,
        default_permissions=discord.Permissions(manage_roles=True),
    )
    _transactions_tools = app_commands.Group(
        name="tools",
        description="Transaction maintenance and validation tools",
        parent=_transactions,
        guild_only=True,
        default_permissions=discord.Permissions(manage_roles=True),
    )

    # Settings

    @_transactions.command(name="settings", description="Display current transactions settings")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _transactions_settings(self, interaction: discord.Interaction):
        """Show transactions settings"""
        if not interaction.guild:
            return

        log_channel = await self._trans_log_channel(interaction.guild)
        trans_channel = await self._trans_channel(interaction.guild)
        trans_role = await self._trans_role(interaction.guild)
        notifications = await self._notifications_enabled(interaction.guild)
        gm_notifications = await self._gm_notifications_enabled(interaction.guild)
        dms = await self._trans_dms_enabled(interaction.guild)
        trade_announcements = await self._trade_announcements_enabled(interaction.guild)
        trade_role_updates = await self._trade_role_updates_enabled(interaction.guild)
        cut_msg = await self._get_cut_message(interaction.guild) or "None"

        settings_embed = discord.Embed(
            title="Transactions Settings",
            description="Current configuration for Transactions",
            color=discord.Color.blue(),
        )

        settings_embed.add_field(name="Notifications Enabled", value=notifications, inline=False)

        settings_embed.add_field(name="GM Notifications Enabled", value=gm_notifications, inline=False)

        settings_embed.add_field(name="Direct Messages Enabled", value=dms, inline=False)

        settings_embed.add_field(name="Website Trade Announcements", value=trade_announcements, inline=True)

        settings_embed.add_field(name="Website Trade Role Updates", value=trade_role_updates, inline=True)

        # Check channel values before mention to avoid exception
        settings_embed.add_field(
            name="Transaction Channel",
            value=trans_channel.mention if trans_channel else "None",
            inline=False,
        )

        settings_embed.add_field(
            name="Log Channel",
            value=log_channel.mention if log_channel else "None",
            inline=False,
        )

        settings_embed.add_field(
            name="Committee Role",
            value=trans_role.mention if trans_role else "None",
            inline=False,
        )

        # Discord embed field max length is 1024. Send a separate embed for cut message if greater.
        if len(cut_msg) <= 1024:
            settings_embed.add_field(name="Cut Message", value=cut_msg, inline=False)
            await interaction.response.send_message(embed=settings_embed, ephemeral=True)
        else:
            cut_embed = discord.Embed(title="Cut Message", description=cut_msg, color=discord.Color.blue())
            await interaction.response.send_message(embeds=[settings_embed, cut_embed], ephemeral=True)

    @_transactions.command(name="notifications", description="Toggle channel notifications on or off")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def transactions_notifications(self, interaction: discord.Interaction):
        """Toggle channel notifications on or off"""
        guild = interaction.guild
        if not guild:
            return
        status = await self._notifications_enabled(guild)
        log.debug(f"Current Notifications: {status}", guild=guild)
        status ^= True  # Flip boolean with xor
        log.debug(f"Transaction Notifications: {status}", guild=guild)
        await self._set_notifications(guild, status)
        result = "**enabled**" if status else "**disabled**"
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"Transaction committee and GM notifications are now {result}.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_transactions_tools.command(
        name="tradeannouncements",
        description="Toggle announcing trades performed on the RSC website",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def transactions_trade_announcements_cmd(self, interaction: discord.Interaction):
        """Toggle announcements for trades performed outside Discord."""
        guild = interaction.guild
        if not guild:
            return

        status = await self._trade_announcements_enabled(guild)
        status ^= True
        await self._set_trade_announcements(guild, status)
        result = "**enabled**" if status else "**disabled**"
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=(
                    f"Announcements for website trades are now {result}.\n\nTrades performed with `/transactions trade` are unaffected."
                )
            ),
            ephemeral=True,
        )

    @_transactions_tools.command(
        name="traderoleupdates",
        description="Toggle role and nickname updates for trades performed on the RSC website",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def transactions_trade_role_updates_cmd(self, interaction: discord.Interaction):
        """Toggle Discord role/nickname reconciliation for website trades."""
        guild = interaction.guild
        if not guild:
            return

        status = await self._trade_role_updates_enabled(guild)
        status ^= True
        await self._set_trade_role_updates(guild, status)
        result = "**enabled**" if status else "**disabled**"
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=(
                    f"Role and nickname updates for website trades are now {result}.\n\n"
                    "When disabled, traded players keep their old franchise role and prefix "
                    "until a sync is run."
                )
            ),
            ephemeral=True,
        )

    @_transactions_tools.command(
        name="processtrade",
        description="Announce a website trade by transaction ID and reapply player roles",
    )
    @app_commands.describe(
        transaction_id="Transaction ID from the RSC website",
        roles="Also reapply Discord roles and nicknames for traded players",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def transactions_announce_cmd(
        self,
        interaction: discord.Interaction,
        transaction_id: int,
        roles: bool = True,
    ):
        """Manually drive a trade through the announcement path.

        The event poller advances its cursor without running handlers in several
        cases (an oversized backlog, initial bootstrap, or a handler that raised),
        so a trade can legitimately never reach Discord. This is the recovery path.
        """
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        try:
            response = await self.transaction_history_by_id(guild, transaction_id)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        msg = await announce_trade(self, guild, response)
        if not msg:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Transaction channel is not configured."),
                ephemeral=True,
            )

        embed = SuccessEmbed(description=f"Transaction **{transaction_id}** has been announced.")
        embed.add_field(name="Announcement", value=msg.jump_url, inline=False)

        if roles:
            errors = await apply_trade_role_updates(self, guild, response)
            if errors:
                embed.add_long_field(name="Role Update Errors", value="\n".join(f"- {e}" for e in errors))

        return await interaction.followup.send(embed=embed, ephemeral=True)

    @_transactions.command(name="gmnotifications", description="Toggle GM notifications on or off")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def transactions_gm_notifications_cmd(self, interaction: discord.Interaction):
        """Toggle GM notifications on or off"""
        guild = interaction.guild
        if not guild:
            return
        status = await self._gm_notifications_enabled(guild)
        log.debug(f"Current GM Notifications: {status}", guild=guild)
        status ^= True  # Flip boolean with xor
        log.debug(f"GM Notifications: {status}", guild=guild)
        await self._set_gm_notifications(guild, status)
        result = "**enabled**" if status else "**disabled**"
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"GM member notifications are now {result}.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_transactions.command(name="toggledm", description="Toggle player direct messages on or off")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def transactions_dms_toggle(self, interaction: discord.Interaction):
        """Toggle channel notifications on or off"""
        guild = interaction.guild
        if not guild:
            return

        status = await self._trans_dms_enabled(guild)
        log.debug(f"Current DM Status: {status}", guild=guild)
        status ^= True  # Flip boolean with xor
        log.debug(f"New Transaction DMs Status: {status}", guild=guild)
        await self._set_trans_dm(guild, status)

        result = "**enabled**" if status else "**disabled**"
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"Player transaction direct messages are now {result}.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_transactions.command(
        name="transactionchannel",
        description="Configure the transaction announcement channel",
    )
    @app_commands.describe(channel="Transaction announcement discord channel (Must be a text channel)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _transactions_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set transaction channel"""
        if not interaction.guild:
            return
        await self._save_trans_channel(interaction.guild, channel.id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"Transaction channel configured to {channel.mention}",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_transactions.command(name="logchannel", description="Set the transactions committee log channel")
    @app_commands.describe(channel="Transaction committee log discord channel (Must be a text channel)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _transactions_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set transactions log channel"""
        if not interaction.guild:
            return
        await self._save_trans_log_channel(interaction.guild, channel.id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"Transaction log channel configured to {channel.mention}",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_transactions.command(name="role", description="Configure the transaction committee role")
    @app_commands.describe(role="Transaction committee discord role")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _transactions_role(self, interaction: discord.Interaction, role: discord.Role):
        if not interaction.guild:
            return
        await self._save_trans_role(interaction.guild, role.id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"Transaction committee role configured to {role.mention}",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_transactions.command(name="cutmsg", description="Configure the player cut message")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _transactions_cutmsg(self, interaction: discord.Interaction):
        """Set cut message (4096 characters max)"""
        if not interaction.guild:
            return

        cutmsg_modal = CutMsgModal()
        await interaction.response.send_modal(cutmsg_modal)
        await cutmsg_modal.wait()

        cutmsg = cutmsg_modal.cutmsg.value

        await self._save_cut_message(interaction.guild, cutmsg)
        cut_embed = discord.Embed(title="Cut Message", description=f"{cutmsg}", color=discord.Color.green())
        cut_embed.set_footer(text="Successfully configured new cut message.")
        await interaction.followup.send(embed=cut_embed, ephemeral=True)

    # Committee Commands

    @_transactions.command(name="cut", description="Release a player from their team")
    @app_commands.describe(
        player="Player to cut",
        notes="Transaction notes (Optional)",
        announce="Announce to server (Default: True)",
        override="Admin only override",
    )
    async def _transactions_cut(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        notes: str | None = None,
        announce: bool = True,
        override: bool = False,
    ):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        # if override and not interaction.user.guild_permissions.manage_guild:
        #     await interaction.response.send_message(
        #         embed=ErrorEmbed(description="Only admins can process an override.")
        #     )
        #     return

        # Defer
        await interaction.response.defer(ephemeral=True)

        try:
            result = await self.cut(
                guild,
                player=player,
                executor=interaction.user,
                notes=notes,
                override=override,
            )
            log.debug(f"Cut Result: {result}", guild=guild)
        except RscException as exc:
            log.warning(f"Transaction Exception: {exc.reason}", guild=guild)
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
            return

        ptu = await self.league_player_from_transaction(result, player=player)
        if not ptu:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=(
                        f"Cut was processed but API did not return PlayerTransactionUpdate for {player.mention}. "
                        "Announcement and discord updates have not been completed."
                    )
                ),
                ephemeral=True,
            )

        try:
            # Check should get devleague role (only add to users one time in their career)
            add_devleague_role = await self.should_get_devleague_role(interaction.user)
            log.debug(f"Add Dev League Role: {add_devleague_role}")
            await update_cut_player_discord(guild=guild, player=player, response=result, ptu=ptu, devleague=add_devleague_role)

        except discord.Forbidden as exc:
            log.warning(f"Unable to update nickname for {player.id}: {exc}", guild=guild)
            await interaction.followup.send(content=f"Unable to update nickname for {player.mention}: `{exc}")
        except AttributeError as exc:
            await interaction.followup.send(embed=ErrorEmbed(description=str(exc)))
        except ValueError as exc:
            await interaction.followup.send(embed=ErrorEmbed(description=str(exc)))

        try:
            embed, files = await self.build_transaction_embed(
                guild=guild,
                response=result,
                player_in=player,
            )
        except MalformedTransactionResponse as exc:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"Unable to announce transaction: `{exc!s}`"),
                ephemeral=True,
            )

        # Announce to transaction channel
        if result.first_franchise and announce:
            await self.announce_transaction(
                guild,
                embed=embed,
                files=files,
                player=player,
                gm=gm_discord_id(result.first_franchise),
            )
        elif not override:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description="Transaction was processed but did not contain any old franchise data. **Announcement not sent.**"
                ),
                ephemeral=True,
            )

        # Send cut message to user directly
        if announce:
            try:
                await self.send_cut_msg(guild, player=player)
            except discord.Forbidden as exc:
                await interaction.followup.send(content=f"Unable to DM user {player.mention}: {exc}")

        # Send result
        await interaction.followup.send(
            embed=SuccessEmbed(description=f"{player.mention} has been released to the Free Agent pool."),
            ephemeral=True,
        )

    @_transactions.command(name="sign", description="Sign a player to the specified team")
    @app_commands.describe(
        player="Player to sign",
        team="Team the player is being sign on",
        notes="Transaction notes (Optional)",
        override="Admin only override",
    )
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)
    async def _transactions_sign(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        team: str,
        notes: str | None = None,
        override: bool = False,
    ):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        # if override and not interaction.user.guild_permissions.manage_guild:
        #     await interaction.response.send_message(
        #         embed=ErrorEmbed(description="Only admins can process an override.")
        #     )
        #     return

        # Sign player
        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.sign(
                guild,
                player=player,
                team=team,
                executor=interaction.user,
                notes=notes,
                override=override,
            )
            log.debug(f"Sign Result: {result}]", guild=guild)
            tiers = await self.tiers(guild=guild)
        except RscException as exc:
            log.warning(f"Transaction Exception: {exc.reason}", guild=guild)
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
            return

        ptu = await self.league_player_from_transaction(result, player=player)
        if not ptu:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=(
                        f"Cut was processed but API did not return PlayerTransactionUpdate for {player.mention}."
                        " "
                        "Announcement and discord updates have not been completed."
                    )
                ),
                ephemeral=True,
            )

        # Need to get tier data to remove old roles (Ex: Promotion)

        try:
            await update_signed_player_discord(guild=guild, player=player, ptu=ptu, tiers=tiers)
        except discord.Forbidden as exc:
            log.warning(f"Unable to update nickname for {player.id}: {exc}", guild=guild)
            await interaction.followup.send(content=f"Unable to update nickname for {player.mention}: `{exc}")
        except AttributeError as exc:
            await interaction.followup.send(embed=ErrorEmbed(description=str(exc)))
        except ValueError as exc:
            await interaction.followup.send(embed=ErrorEmbed(description=str(exc)))

        try:
            embed, files = await self.build_transaction_embed(guild=guild, response=result, player_in=player)
        except MalformedTransactionResponse as exc:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"Unable to announce transaction: `{exc!s}`"),
                ephemeral=True,
            )

        if result.second_franchise:
            await self.announce_transaction(
                guild=guild,
                embed=embed,
                files=files,
                player=player,
                gm=gm_discord_id(result.second_franchise),
            )
        else:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description="Transaction was processed but did not contain any new franchise data. **Announcement not sent.**"
                ),
                ephemeral=True,
            )

        # Send result
        if ptu.new_team:
            await interaction.followup.send(
                embed=SuccessEmbed(description=f"{player.mention} has been signed to **{ptu.new_team.name}**"),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                embed=YellowEmbed(description=f"{player.mention} has been signed but a team name was not returned."),
                ephemeral=True,
            )

    @_transactions.command(name="resign", description="Re-sign a player to their team.")
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)
    @app_commands.describe(
        player="RSC Discord Member",
        team="Name of team player resigning player",
        notes="Transaction notes (Optional)",
        announce="Announce to server (Default: True)",
        override="Admin only override",
    )
    async def _transactions_resign(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        team: str,
        notes: str | None = None,
        announce: bool = True,
        override: bool = False,
    ):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        # if override and not interaction.user.guild_permissions.manage_guild:
        #     await interaction.response.send_message(
        #         embed=ErrorEmbed(description="Only admins can process an override.")
        #     )
        #     return

        await interaction.response.defer(ephemeral=True)
        # Process sign
        try:
            result = await self.resign(
                guild,
                player=player,
                team=team,
                executor=interaction.user,
                notes=notes,
                override=override,
            )
            log.debug(f"Re-sign Result: {result}]", guild=guild)
            tiers = await self.tiers(guild=guild)
        except RscException as exc:
            log.warning(f"Transaction Exception: {exc.reason}", guild=guild)
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
            return

        ptu = await self.league_player_from_transaction(result, player=player)
        if not ptu:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=(
                        f"Cut was processed but API did not return PlayerTransactionUpdate for {player.mention}. "
                        "Announcement and discord updates have not been completed."
                    )
                ),
                ephemeral=True,
            )

        try:
            await update_signed_player_discord(guild=guild, player=player, ptu=ptu, tiers=tiers)
        except discord.Forbidden as exc:
            log.warning(f"Unable to update nickname for {player.id}: {exc}", guild=guild)
            await interaction.followup.send(content=f"Unable to update nickname for {player.mention}: `{exc}`")
        except AttributeError as exc:
            await interaction.followup.send(embed=ErrorEmbed(description=str(exc)))
        except ValueError as exc:
            await interaction.followup.send(embed=ErrorEmbed(description=str(exc)))

        try:
            embed, files = await self.build_transaction_embed(guild=guild, response=result, player_in=player)
        except MalformedTransactionResponse as exc:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"Unable to announce transaction: `{exc!s}`"),
                ephemeral=True,
            )

        if announce:
            await self.announce_transaction(guild=guild, embed=embed, files=files, player=player)

        # Send result
        if ptu.new_team:
            await interaction.followup.send(
                embed=SuccessEmbed(description=f"{player.mention} has been re-signed to **{ptu.new_team.name}**"),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                embed=YellowEmbed(description=f"{player.mention} has been re-signed but a team name was not returned."),
                ephemeral=True,
            )

    @_transactions.command(name="sub", description="Substitute a player on a team")
    @app_commands.describe(
        player_in="Player being subbed in on the team",
        player_out="Player being subbed out on the team",
        notes="Substitation notes (Optional)",
        override="Admin only override",
    )
    async def _transactions_substitute(
        self,
        interaction: discord.Interaction,
        player_in: discord.Member,
        player_out: discord.Member,
        notes: str | None = None,
        override: bool = False,
    ):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)

        # if override and not interaction.user.guild_permissions.manage_guild:
        #     await interaction.followup.send(
        #         embed=ErrorEmbed(description="Only admins can process an override.")
        #     )
        #     return

        try:
            result = await self.substitution(
                guild,
                player_in=player_in,
                player_out=player_out,
                executor=interaction.user,
                notes=notes,
                override=override,
            )
            log.debug(f"Sub Result: {result}", guild=guild)
        except RscException as exc:
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
            return

        ptu_in = await self.league_player_from_transaction(result, player_in)
        if not ptu_in:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=(
                        f"Cut was processed but API did not return PlayerTransactionUpdate for {player_in.mention}. "
                        "Announcement and discord updates have not been completed."
                    )
                ),
                ephemeral=True,
            )

        # Subbed out role
        subbed_out_role = await utils.get_subbed_out_role(guild)
        await player_out.add_roles(subbed_out_role)

        try:
            embed, files = await self.build_transaction_embed(
                guild=guild,
                response=result,
                player_in=player_in,
                player_out=player_out,
            )
        except MalformedTransactionResponse as exc:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"Unable to announce transaction: `{exc!s}`"),
                ephemeral=True,
            )

        # Validate response
        if not result.second_franchise:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="Substitution was processed but no second franchise data was returned. **Announcement was not sent.**"
                )
            )

        sub_gm_id = gm_discord_id(result.second_franchise)
        if not sub_gm_id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="Substitution was processed but no second franchise data has no GM. **Announcement was not sent.**"
                )
            )

        if not (ptu_in.new_team and ptu_in.new_team.name):
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Substitution was processed but no team name was returned. **Announcement was not sent.**")
            )

        if not (ptu_in.new_team and ptu_in.new_team.tier):
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Substitution was processed but no team tier was returned. **Announcement was not sent.**")
            )

        await self.announce_transaction(
            guild=guild,
            embed=embed,
            files=files,
            player=player_in,
            gm=sub_gm_id,
        )

        # Save sub for expiration later
        tz = await self.timezone(guild)
        sub_obj = Substitute(
            date=str(datetime.now(tz)),
            player_in=player_in.id,
            player_out=player_out.id,
            team=ptu_in.new_team.name,
            gm=sub_gm_id,
            tier=ptu_in.new_team.tier,
            franchise=result.second_franchise.name,
        )
        await self._add_substitute(guild, sub_obj)

        # Update visibility in FA availability
        await self.update_freeagent_visibility(guild=guild, player=player_in, visibility=False)

        embed = SuccessEmbed(description=f"{player_out.mention} has been subbed out for {player_in.mention}")
        if result.var_date:
            embed.add_field(name="Date", value=result.var_date.strftime("%Y-%m-%d"), inline=True)

        embed.add_field(name="Match Day", value=str(result.match_day), inline=True)

        if result.notes:
            # embed.add_field(name="", value="", inline=False)
            embed.add_field(name="Notes", value=result.notes, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @_transactions.command(
        name="announce",
        description="Perform a generic announcement to the transactions channel.",
    )
    async def _transactions_announce(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        trans_channel = await self._trans_channel(interaction.guild)
        if not trans_channel:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Transaction channel is not configured."),
                ephemeral=True,
            )
            return

        announce_modal = TransactionAnnouncementModal()
        await interaction.response.send_modal(announce_modal)
        await announce_modal.wait()

        if not announce_modal.message.value:
            await interaction.followup.send(content="No announcement content provided... Try again.", ephemeral=True)
            return

        announcement = announce_modal.message.value.strip()
        if not announcement:
            await interaction.followup.send(content="No announcement content provided... Try again.", ephemeral=True)
            return

        msg = await trans_channel.send(
            announcement,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        await interaction.followup.send(content=f"Done: {msg.jump_url}", ephemeral=True)

    @_transactions.command(
        name="announcetrade",
        description="Announce a trade between two franchises to the transaction chanenl",
    )
    async def _transactions_announcetrade(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        trans_channel = await self._trans_channel(guild)
        if not trans_channel:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Transaction channel is not configured."),
                ephemeral=True,
            )
            return

        trade_modal = TradeAnnouncementModal()
        await interaction.response.send_modal(trade_modal)
        await trade_modal.wait()

        if not trade_modal.trade.value:
            await interaction.followup.send(content="No trade information provided... Try again.", ephemeral=True)
            return

        log.debug(f"Trade Announcement: {trade_modal.trade.value}", guild=guild)
        trade_msg = await trans_channel.send(
            content=trade_modal.trade.value,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

        embed = SuccessEmbed(description=f"Trade announcement has been posted: {trade_msg.jump_url}")
        embed.add_field(name="Content", value=trade_modal.trade.value)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @_transactions.command(
        name="trade",
        description="Process a trade between franchises",
    )
    @app_commands.describe(override="Admin only override")
    async def _transactions_trade_cmd(
        self,
        interaction: discord.Interaction,
        notes: str | None = None,
        override: bool = False,
        announce: bool = True,
    ):
        guild = interaction.guild
        if not guild:
            return

        if not isinstance(interaction.user, discord.Member):
            return

        # if override and not interaction.user.guild_permissions.manage_guild:
        #     await interaction.followup.send(
        #         embed=ErrorEmbed(description="Only admins can process an override.")
        #     )
        #     return

        trans_channel = await self._trans_channel(guild)
        if not trans_channel:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Transaction channel is not configured."),
                ephemeral=True,
            )
            return

        trade_modal = TradeAnnouncementModal()
        await interaction.response.send_modal(trade_modal)
        await trade_modal.wait()

        if not trade_modal.trade:
            await interaction.followup.send(content="No trade information provided... Try again.", ephemeral=True)
            return

        # Parse trade
        try:
            trade_items = await self.parse_trade_text(guild=guild, data=trade_modal.trade.value)
            log.debug(pformat(trade_items))
        except TradeParserException as exc:
            await interaction.followup.send(
                embed=ExceptionErrorEmbed(title="Trade Parsing Error", exc_message=exc.message),
                ephemeral=True,
            )
            return

        try:
            result = await self.trade(
                guild=guild,
                trades=trade_items,
                executor=interaction.user,
                notes=notes or trade_modal.trade.value,
                override=override,
            )
            log.debug(f"Transaction History Result: {result}", guild=guild)
            tiers = await self.tiers(guild=guild)
        except RscException as exc:
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
            return

        # Process role changes for traded players
        if result.player_updates:
            for r in result.player_updates:
                if r is None:
                    continue
                if not r.player.player:
                    await interaction.followup.send(
                        content=f"**{r.player.id}** has no player data. Unable to process roles and name change."
                    )
                    continue
                if not r.player.player.discord_id:
                    await interaction.followup.send(
                        content=f"**{r.player.id}** has no discord_id. Unable to process roles and name change."
                    )
                    continue

                m = guild.get_member(r.player.player.discord_id)
                if not m:
                    await interaction.followup.send(
                        content=f"<@{r.player.player.discord_id}> not found in the server. Unable to process roles and name change."
                    )
                    continue

                try:
                    await update_signed_player_discord(guild=guild, player=m, ptu=r, tiers=tiers)
                except discord.Forbidden as exc:
                    log.warning(f"Unable to update nickname for {m.id}: {exc}", guild=guild)
                    await interaction.followup.send(content=f"Unable to update nickname for {m.mention}: `{exc}")
                except AttributeError as exc:
                    await interaction.followup.send(embed=ErrorEmbed(description=str(exc)))
                except ValueError as exc:
                    await interaction.followup.send(embed=ErrorEmbed(description=str(exc)))

        msg = None
        if announce:
            gms, embed = await self.build_trade_embed(guild, trade_items)
            gm_mention = " ".join([f"<@!{g}>" for g in gms])
            msg = await trans_channel.send(
                content=gm_mention,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=True),
            )
            await msg.edit(content=None, embed=embed)

        embed = SuccessEmbed(description="Trade has been processed.")
        if msg:
            embed.add_field(name="Announcement", value=msg.jump_url, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @_transactions.command(
        name="captain",
        description="Promote player(s) to captain of their team",
    )
    @app_commands.describe(player="RSC Discord Member")
    async def _transactions_captain(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        player1: discord.Member | None = None,
        player2: discord.Member | None = None,
        player3: discord.Member | None = None,
        player4: discord.Member | None = None,
        player5: discord.Member | None = None,
        player6: discord.Member | None = None,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        argv = locals()
        captains: list[discord.Member] = []

        # Aggregate captains into list
        log.debug(f"Locals: {argv}", guild=guild)
        for k, v in argv.items():
            if v and k.startswith("player"):
                captains.append(v)
        log.debug(f"Captain Count: {len(captains)}", guild=guild)

        results: list[discord.Member] = []
        for captain in captains:
            # Get team of player being made captain
            plist = await self.players(guild, discord_id=captain.id, limit=1)

            if not plist:
                await interaction.followup.send(
                    content=f"{player.mention} is not a league player. Skipping...",
                    ephemeral=True,
                )
                continue

            player_data = plist.pop()

            if player_data.status not in (Status.ROSTERED, Status.RENEWED):
                await interaction.followup.send(
                    content=f"{captain.mention} is not currently rostered. Skipping...",
                    ephemeral=True,
                )
                continue

            if not player_data.id:
                await interaction.followup.send(content=f"{captain.mention} has no player ID.", ephemeral=True)
                continue

            if not (player_data.team and player_data.team.id and player_data.team.name):
                await interaction.followup.send(
                    content=f"{captain.mention} has no team data or team ID. Skipping...",
                    ephemeral=True,
                )
                continue

            if not player_data.tier:
                await interaction.followup.send(
                    content=f"{captain.mention} has no tier data. Skipping...",
                    ephemeral=True,
                )
                continue

            if not player_data.team.franchise:
                await interaction.followup.send(
                    content=f"{captain.mention} has no franchise data. Skipping...",
                    ephemeral=True,
                )
                continue

            try:
                # Promote new player to captain or flip captain flag off.
                await self.set_captain(guild, player_data.id)

                # Get team data
                team_players = await self.team_players(guild, player_data.team.id)

                # Update roles in discord
                await update_team_captain_discord(guild=guild, players=team_players)
            except RscException as exc:
                await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
                continue
            except ValueError as exc:
                await interaction.followup.send(embed=ErrorEmbed(description=str(exc)))

            results.append(captain)

        # Send Result
        embed = SuccessEmbed(
            title="Captains Updated",
            description="Updated captain roles for the following player(s).",
        )
        embed.add_field(name="Players", value="\n".join([m.mention for m in results]), inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @_transactions.command(
        name="expire",
        description="Manually expire a temporary FA contract",
    )
    @app_commands.describe(player="RSC Discord Member")
    async def _transactions_expire(self, interaction: discord.Interaction, player: discord.Member):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.expire_sub(
                guild,
                player=player,
                executor=interaction.user,
            )
            log.debug(f"Expire Sub Result: {result}", guild=guild)
        except RscException as exc:
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
            return

        # Get sub object and remove it from saved list
        sub_obj = await self.get_sub(player)
        if sub_obj:
            stier = sub_obj["tier"]
            p_in = sub_obj["player_in"]
            p_out = sub_obj["player_out"]
            gm_id = sub_obj["gm"]
            steam = sub_obj["team"]
            fname = sub_obj["franchise"]

            # Remove subbed out role from subbed player
            subbed_out_role = await utils.get_subbed_out_role(guild)
            m_out = guild.get_member(p_out)
            if subbed_out_role and m_out:
                await m_out.remove_roles(subbed_out_role)

            # Get FA img resource
            fa_icon = await utils.fa_img_from_tier(stier, tiny=True)
            img_path = Path(__file__).parent.parent / "resources/transactions/ContractExpired.png"

            dFiles = [discord.File(img_path)]
            if fa_icon:
                dFiles.append(fa_icon)

            # Tier color
            tier_color = await utils.tier_color_by_name(guild, stier)

            # Post to transactions
            tchan = await self._trans_channel(guild)
            if tchan:
                embed = discord.Embed(color=tier_color)
                embed.set_image(url="attachment://ContractExpired.png")
                embed.set_author(
                    name=f"{player.display_name} has finished temporary contract for {steam}",
                    icon_url=f"attachment://{fa_icon.filename}" if fa_icon else None,
                )
                embed.add_field(name="Player In", value=f"<@!{p_out}>", inline=True)
                embed.add_field(name="Player Out", value=f"<@!{p_in}>", inline=True)
                embed.add_field(name="Franchise", value=f"{fname}", inline=True)

                pingstr = f"{player.mention} <@!{gm_id}>"

                tmsg = await tchan.send(
                    content=pingstr,
                    embed=embed,
                    files=dFiles,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
                await tmsg.edit(content=None, embed=embed)
            await self._rm_substitute(guild, sub_obj)

        await interaction.followup.send(
            embed=SuccessEmbed(description=f"The temporary FA contract for {player.mention} has been expired."),
            ephemeral=True,
        )

    @_transactions.command(
        name="sublist",
        description="Fetch a list of all players with a temporary FA contract",
    )
    async def _transactions_sublist(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        subs = await self._get_substitutes(interaction.guild)
        embed = BlueEmbed(
            title="Temporary FA Contracts",
            description="List of all players with a temporary FA contract",
        )
        sub_fmt = [(x["player_in"], x["player_out"], x["team"]) for x in subs]
        embed.add_field(name="In", value="\n".join([f"<@!{x[0]}>" for x in sub_fmt]), inline=True)
        embed.add_field(name="Out", value="\n".join([f"<@!{x[1]}>" for x in sub_fmt]), inline=True)
        embed.add_field(name="Team", value="\n".join([x[2] for x in sub_fmt]), inline=True)
        await interaction.response.send_message(embed=embed)

    @_transactions.command(
        name="redshirt",
        description="Move an AGM to redshirt status",
    )
    @app_commands.describe(
        player="RSC Discord Member",
        notes="Transaction notes (Optional)",
        override="Admin only override",
    )
    async def _transactions_redshirt_cmd(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        notes: str | None = None,
        override: bool = False,
    ):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        # if override and not interaction.user.guild_permissions.manage_guild:
        #     await interaction.response.send_message(
        #         embed=ErrorEmbed(description="Only admins can process an override.")
        #     )
        #     return

        log.debug(f"Moving AGM to Redshirt: {player.display_name} ({player.id})", guild=guild)
        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.inactive_reserve(
                guild,
                player=player,
                executor=interaction.user,
                notes=notes,
                override=override,
                redshirt=True,
            )
            log.debug(f"Redshirt Result: {result}", guild=guild)
        except RscException as exc:
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
            return

        # Remove tier roles since redshirt is not a player.
        tiers = await self.tiers(guild)
        if tiers:
            log.debug(f"Removing tier roles from AGM Redshirt: {player.id}", guild=guild)
            roles_to_remove: list[discord.Role] = []
            for r in player.roles:
                for tier in tiers:
                    if r.name.replace("FA", "").lower() == tier.name.lower():
                        roles_to_remove.append(r)  # noqa: PERF401
            if roles_to_remove:
                await player.remove_roles(*roles_to_remove)

        await interaction.followup.send(
            embed=SuccessEmbed(description=f"{player.mention} has been declared as Redshirt."),
            ephemeral=True,
        )

    @_transactions.command(
        name="ir",
        description="Modify inactive reserve status of a player",
    )
    @app_commands.describe(
        action="Inactive Reserve Action",
        player="RSC Discord Member",
        notes="Transaction notes (Optional)",
        announce="Announce to transactions channel (Default: True)",
        override="Admin only override",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="MOVE", value=0),
            app_commands.Choice(name="RETURN", value=1),
        ]
    )
    async def _transactions_ir(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[int],
        player: discord.Member,
        notes: str | None = None,
        announce: bool = True,
        override: bool = False,
    ):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        # if override and not interaction.user.guild_permissions.manage_guild:
        #     await interaction.response.send_message(
        #         embed=ErrorEmbed(description="Only admins can process an override.")
        #     )
        #     return
        await interaction.response.defer(ephemeral=True)

        remove = bool(action.value)
        log.debug(f"Remove from IR: {remove}", guild=guild)

        try:
            result = await self.inactive_reserve(
                guild,
                player=player,
                executor=interaction.user,
                notes=notes,
                override=override,
                redshirt=False,
                remove=remove,
            )
            log.debug(f"Expire Sub Result: {result}", guild=guild)
        except RscException as exc:
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
            return

        # IR Role
        ir_role = await utils.get_ir_role(guild)

        if ir_role:
            if remove:
                await player.remove_roles(ir_role)
            else:
                await player.add_roles(ir_role)

        try:
            embed, files = await self.build_transaction_embed(guild=guild, response=result, player_in=player)
        except MalformedTransactionResponse as exc:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"Unable to announce transaction: `{exc!s}`"),
                ephemeral=True,
            )

        if announce:
            ir_gm_id = gm_discord_id(result.first_franchise)
            if ir_gm_id:
                await self.announce_transaction(
                    guild=guild,
                    embed=embed,
                    files=files,
                    player=player,
                    gm=ir_gm_id,
                )
            else:
                await interaction.followup.send(
                    content="IR transaction response did not return first_franchise and or GM discord ID. Announcement skipped...",
                    ephemeral=True,
                )

        action_fmt = "removed from" if remove else "moved to"
        await interaction.followup.send(
            embed=SuccessEmbed(description=f"{player.mention} has been {action_fmt} Inactive Reserve."),
            ephemeral=True,
        )

    @_transactions.command(name="retire", description="Retire a player from the league")
    @app_commands.describe(
        player="RSC discord member to retire",
        notes="Transaction notes (Optional)",
        override="Admin only override (Default: False)",
        announce="Announce to transactions channel (Default: True)",
    )
    async def _transactions_retire_cmd(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        notes: str | None = None,
        override: bool = False,
        announce: bool = True,
    ):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        # if override and not interaction.user.guild_permissions.manage_guild:
        #     await interaction.response.send_message(
        #         embed=ErrorEmbed(description="Only admins can process an override.")
        #     )
        #     return

        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.retire(
                guild,
                player=player,
                executor=interaction.user,
                notes=notes,
                override=override,
            )
            log.debug(f"Retire Result: {result}", guild=guild)
            tiers = await self.tiers(guild=guild)
            # A retiring AGM keeps their staff role and franchise prefix: they
            # stopped playing, not staffing. `/admin agm remove` is what ends it.
            agm_franchise = await self.agm_franchise_of(guild, player.id)
        except RscException as exc:
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
            return

        ptu = await self.league_player_from_transaction(result, player=player)
        if not ptu:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=(
                        f"Cut was processed but API did not return PlayerTransactionUpdate for {player.mention}. "
                        "Announcement and discord updates have not been completed."
                    )
                ),
                ephemeral=True,
            )

        default_roles = await self._get_welcome_roles(guild)
        await update_nonplaying_discord(guild=guild, member=player, tiers=tiers, default_roles=default_roles, agm_franchise=agm_franchise)

        # Announce to Transaction channel
        if announce:
            try:
                embed, files = await self.build_transaction_embed(guild=guild, response=result, player_in=player)
            except MalformedTransactionResponse as exc:
                return await interaction.followup.send(
                    embed=ErrorEmbed(description=f"Unable to announce transaction: `{exc!s}`"),
                    ephemeral=True,
                )

            await self.announce_transaction(guild=guild, embed=embed, files=files, player=player)

        # Send result
        await interaction.followup.send(
            embed=SuccessEmbed(description=f"{player.mention} has been retired from the league."),
            ephemeral=True,
        )

    @_transactions_tools.command(name="clearsublist", description="Clear cached substitute list")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _transactions_clear_sub_list(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        await self._set_substitutes(interaction.guild, subs=[])
        await interaction.response.send_message("Locally cached substitute list has been cleared.", ephemeral=True)

    @_transactions.command(name="history", description="Fetch transaction history")
    @app_commands.describe(
        player="RSC Discord Member (Optional)",
        executor="Transaction Executor (Optional)",
        season='RSC Season Number. Example: "19" (Optional)',
        type="Transaction Type (Optional)",
        limit="Max number of transactions to display (Default: 10)",
    )
    async def _transactions_history_cmd(
        self,
        interaction: discord.Interaction,
        player: discord.Member | None = None,
        executor: discord.Member | None = None,
        season: int | None = None,
        type: TransactionType | None = None,
        limit: app_commands.Range[int, 1, 20] = 10,
    ):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)
        try:
            # Always use a season to avoid excessive historical data
            # Default to current season if not provided.
            if not season:
                season_obj = await self.current_season(guild)
                if season_obj:
                    season = season_obj.number
                else:
                    return await interaction.followup.send(
                        embed=ErrorEmbed(
                            description="Unable to determine current season for transaction history. Please specify season number."
                        ),
                        ephemeral=True,
                    )

            result = await self.transaction_history(
                guild,
                player=player,
                executor=executor,
                season=season,
                trans_type=type,
                limit=limit,
            )
            log.debug(f"Transaction History Result: {result}")
        except RscException as exc:
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
            return

        if not result:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Transaction History",
                    description="No results for specified criteria.",
                ),
                ephemeral=True,
            )

        fmt_list = []
        for t in result:
            date = None
            if not t.var_date:  # noqa: SIM108
                date = "None"
            else:
                date = str(t.var_date.date())

            if not t.type:
                trans_type = "Unknown"
            else:
                try:
                    trans_type = TransactionType(t.type).full_name
                except ValueError:
                    log.warning(f"Unknown transaction type from API: {t.type}", guild=guild)
                    trans_type = str(t.type)

            if t.executor.discord_id:  # noqa: SIM108
                texc = str(t.executor.discord_id)
            else:
                texc = "None"

            fmt_list.append((date, trans_type, texc))

        embed = BlueEmbed(
            title="Transaction History",
            description="List of transactions for specified criteria.",
        )

        embed.add_field(name="Date", value="\n".join([x[0] for x in fmt_list]), inline=True)
        embed.add_field(name="Type", value="\n".join([x[1] for x in fmt_list]), inline=True)
        embed.add_field(name="Executor", value="\n".join([x[2] for x in fmt_list]), inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @_transactions.command(name="leaderboard", description="Display transaction committee leaderboard")
    @app_commands.describe(
        season='RSC Season Number. Example: "23" (Default: Current Season)',
        transaction_type="Transaction Type (Optional)",
        no_draft="Exclude draft transactions (Default: False)",
    )
    async def _transactions_leaderboard_cmd(
        self,
        interaction: discord.Interaction,
        season: int | None = None,
        transaction_type: TransactionType | None = None,
        no_draft: bool = False,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer()

        # Default to current season
        # All-time leaderboard is too intensive on API
        if not season:
            season_obj = await self.current_season(guild)
            if not season_obj:
                return await interaction.followup.send(
                    embed=ErrorEmbed(description="Unable to determine current season for leaderboard."),
                    ephemeral=True,
                )
            season = season_obj.number

        leaders: dict[int, int] = {}
        try:
            t: TransactionResponse
            async for t in self.paged_transaction_history(guild, season=season, trans_type=transaction_type):
                if not t.executor.discord_id:
                    log.warning("Transaction executor has no discord ID.", guild=guild)
                    continue
                if no_draft and t.type == TransactionType.DRAFT:
                    continue
                if not leaders.get(t.executor.discord_id):
                    leaders[t.executor.discord_id] = 1
                    continue
                leaders[t.executor.discord_id] += 1
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        # Sort and trim to top 15
        leader_fmt = sorted(leaders.items(), key=lambda i: i[1], reverse=True)
        leader_fmt = leader_fmt[:15]  # Top 15

        desc = "Your transaction is my command."
        title = "Transaction Leaderboard"
        if season:
            title += f" (S{season})"

        embed = BlueEmbed(
            title=title,
            description=desc,
        )

        embed.add_field(
            name="Rank",
            value="\n".join(str(i + 1) for i in range(len(leader_fmt))),
            inline=True,
        )
        embed.add_field(name="Name", value="\n".join(f"<@!{x[0]}>" for x in leader_fmt), inline=True)
        embed.add_field(name="Total", value="\n".join(str(x[1]) for x in leader_fmt), inline=True)
        await interaction.followup.send(embed=embed)

    @_transactions.command(name="draft", description="Process a draft pick and announce it")
    @app_commands.describe(
        player="RSC discord member being drafted",
        team="Team name",
        round="Round player was drafted in",
        pick="Pick number",
        override="Admin only override (Default: False)",
    )
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)
    async def _transactions_draft_cmd(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        team: str,
        round: int,
        pick: int,
        override: bool = False,
    ):
        guild = interaction.guild
        if not guild:
            return

        if not isinstance(interaction.user, discord.Member):
            return

        # if override and not interaction.user.guild_permissions.manage_guild:
        #     await interaction.response.send_message(
        #         embed=ErrorEmbed(description="Only admins can process an override.")
        #     )
        #     return

        await interaction.response.defer()
        try:
            result = await self.draft(
                guild=guild,
                player=player,
                executor=interaction.user,
                team=team,
                round=round,
                pick=pick,
                override=override,
            )
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        ptu = await self.league_player_from_transaction(result, player=player)
        if not ptu:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=(
                        f"Cut was processed but API did not return PlayerTransactionUpdate for {player.mention}. "
                        "Announcement and discord updates have not been completed."
                    )
                ),
                ephemeral=True,
            )

        # Update player roles and name
        try:
            await update_signed_player_discord(guild=guild, player=player, ptu=ptu)
        except discord.Forbidden as exc:
            log.warning(f"Unable to update nickname for {player.id}: {exc}", guild=guild)
            await interaction.followup.send(content=f"Unable to update nickname for {player.mention}: `{exc}")
        except AttributeError as exc:
            await interaction.followup.send(embed=ErrorEmbed(description=str(exc)))
        except ValueError as exc:
            await interaction.followup.send(embed=ErrorEmbed(description=str(exc)))

        # Get gm discord id and tier
        gm_id = None
        if ptu.player.team and ptu.player.team.franchise and ptu.player.team.franchise.gm and ptu.player.team.franchise.gm.discord_id:
            gm_id = ptu.player.team.franchise.gm.discord_id

        tier = None
        if ptu.player.tier:
            tier = ptu.player.tier.name

        # Announce
        trans_channel = await self._trans_channel(guild)
        if trans_channel:
            # Determine if kept or drafted
            if player.display_name.startswith("FA |") or player.display_name.startswith("DE |"):  # noqa: SIM108
                action_fmt = "drafted"
            else:
                action_fmt = "kept"

            # Handle edge case where tier/gm id are `None`
            if gm_id and tier:
                draft_fmt = f"Round {round} Pick {pick}: {player.mention} was {action_fmt} by {team} (<@{gm_id}> - {tier})"
            elif gm_id:
                draft_fmt = f"Round {round} Pick {pick}: {player.mention} was {action_fmt} by {team} (<@{gm_id}>)"
            elif tier:
                draft_fmt = f"Round {round} Pick {pick}: {player.mention} was {action_fmt} by {team} ({tier})"
            else:
                draft_fmt = f"Round {round} Pick {pick}: {player.mention} was {action_fmt} by {team}"

            await trans_channel.send(content=draft_fmt, allowed_mentions=discord.AllowedMentions(users=True))

        # Report result
        await interaction.followup.send(content=f"Done. Round: {round} Pick: {pick}")

    @_transactions_tools.command(name="validatefutures", description="Validate a franchise future board")
    @app_commands.autocomplete(franchise=FranchiseMixIn.franchise_autocomplete)
    @app_commands.describe(franchise="Franchise to validate")
    async def _transactions_validate_futures_cmd(
        self,
        interaction: discord.Interaction,
        franchise: str,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        try:
            response = await self.validate_franchise_futures(guild=guild, franchise_name=franchise)
            embed = self.build_futures_validation_embed(response)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except RscException as exc:
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
        except Exception as exc:
            log.exception(f"Error validating futures for {franchise}: {exc}", guild=guild)
            await interaction.followup.send(embed=ExceptionErrorEmbed(str(exc)), ephemeral=True)

    @_transactions_tools.command(name="validatefuturesall", description="Validate all franchise future boards")
    @app_commands.describe(ping="Ping violating GMs in their franchise transaction channels")
    async def _transactions_validate_futures_all_cmd(
        self,
        interaction: discord.Interaction,
        ping: bool = False,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        try:
            franchises = await self.franchises(guild)
        except RscException as exc:
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
            return
        except Exception as exc:
            log.exception(f"Error fetching franchises for futures validation: {exc}", guild=guild)
            await interaction.followup.send(embed=ExceptionErrorEmbed(str(exc)), ephemeral=True)
            return

        validation_results: list[FranchiseFuturesValidationResponse] = []
        validation_failures: list[str] = []
        pinged_franchises: list[str] = []
        ping_failures: list[str] = []

        for franchise in franchises:
            if not franchise.name:
                continue

            try:
                result = await self.validate_franchise_futures(guild=guild, franchise_name=franchise.name)
                validation_results.append(result)

                if not ping or result.is_valid:
                    continue

                if not franchise.gm or not franchise.gm.discord_id:
                    ping_failures.append(f"{result.franchise_name}: missing GM discord ID")
                    continue

                message = self.build_futures_validation_channel_message(result)
                sent_message = await self.announce_to_franchise_transactions(
                    guild=guild,
                    franchise=result.franchise_name,
                    gm=franchise.gm.discord_id,
                    embed=YellowEmbed(
                        title=f"{result.franchise_name} Futures Validation",
                        description=message,
                    ),
                )

                if sent_message:
                    pinged_franchises.append(result.franchise_name)
                else:
                    ping_failures.append(f"{result.franchise_name}: missing transaction channel")
            except RscException as exc:
                validation_failures.append(f"{franchise.name}: validation failed ({exc})")
            except Exception as exc:
                log.exception(f"Error validating futures for {franchise.name}: {exc}", guild=guild)
                validation_failures.append(f"{franchise.name}: unexpected error")

        embed = self.build_futures_validation_summary_embed(
            validation_results=validation_results,
            validation_failures=validation_failures,
            ping=ping,
            pinged_franchises=pinged_franchises,
            ping_failures=ping_failures,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # Functions

    def build_futures_validation_channel_message(self, response: FranchiseFuturesValidationResponse) -> str:
        season = f"Season {response.future_season}" if response.future_season is not None else "Future board"
        if response.is_valid:
            return f"{season} is valid."

        violations = "\n".join(f"- {violation}" for violation in response.violations) or "- Unknown violation"
        return (
            f"{season} has the following violations:\n{violations}\n\n"
            "You must reconcile these issues in order to trade futures within the current season."
        )

    def build_futures_validation_embed(self, response: FranchiseFuturesValidationResponse) -> discord.Embed:
        season = f"Season {response.future_season}" if response.future_season is not None else "Future board"
        if response.is_valid:
            return SuccessEmbed(
                title=f"{response.franchise_name} Futures Validation",
                description=f"{season} is valid.",
            )

        embed = YellowEmbed(
            title=f"{response.franchise_name} Futures Validation",
            description=f"{season} has {len(response.violations)} violation(s).",
        )
        embed.add_field(
            name="Violations",
            value="\n".join(f"- {violation}" for violation in response.violations)[:1024] or "None",
            inline=False,
        )
        return embed

    def build_futures_validation_summary_embed(
        self,
        validation_results: list[FranchiseFuturesValidationResponse],
        validation_failures: list[str],
        ping: bool,
        pinged_franchises: list[str],
        ping_failures: list[str],
    ) -> discord.Embed:
        invalid_results = [result for result in validation_results if not result.is_valid]
        valid_results = [result for result in validation_results if result.is_valid]

        embed: discord.Embed
        if invalid_results:
            embed = YellowEmbed(
                title="Futures Validation Summary",
                description=f"Validated {len(validation_results)} franchise future boards.",
            )
        else:
            embed = SuccessEmbed(
                title="Futures Validation Summary",
                description=f"Validated {len(validation_results)} franchise future boards with no violations.",
            )

        embed.add_field(name="Valid", value=str(len(valid_results)), inline=True)
        embed.add_field(name="Violations", value=str(len(invalid_results)), inline=True)
        embed.add_field(name="Errors", value=str(len(validation_failures)), inline=True)

        if invalid_results:
            invalid_lines = [f"{result.franchise_name} ({len(result.violations)}): {result.violations[0]}" for result in invalid_results]
            embed.add_field(name="Violating Franchises", value="\n".join(invalid_lines)[:1024], inline=False)

        if validation_failures:
            embed.add_field(name="Validation Failures", value="\n".join(validation_failures)[:1024], inline=False)

        if ping:
            embed.add_field(name="Ping GMs", value="Yes", inline=True)
            embed.add_field(name="Pinged", value="\n".join(pinged_franchises)[:1024] or "None", inline=False)
            embed.add_field(name="Ping Failures", value="\n".join(ping_failures)[:1024] or "None", inline=False)

        return embed

    async def announce_transaction(
        self,
        guild: discord.Guild,
        embed: discord.Embed,
        files: list[discord.File] | None = None,
        player: discord.Member | int | None = None,
        gm: discord.Member | int | None = None,
    ) -> discord.Message | None:
        if files is None:
            files = []
        tchan = await self._trans_channel(guild)
        if not tchan:
            return None

        ping_fmt = None
        member_fmt = []

        if isinstance(player, discord.Member):
            member_fmt.append(player.mention)
        elif isinstance(player, int):
            member_fmt.append(f"<@!{player}>")

        if isinstance(gm, discord.Member):
            member_fmt.append(gm.mention)
        elif isinstance(gm, int):
            member_fmt.append(f"<@!{gm}>")

        ping_fmt = " ".join(member_fmt)
        tmsg = await tchan.send(
            content=ping_fmt,
            embed=embed,
            files=files,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        await tmsg.edit(content=None, embed=embed)
        return tmsg

    async def build_transaction_embed(
        self,
        guild: discord.Guild,
        response: TransactionResponse,
        player_in: discord.Member,
        player_out: discord.Member | None = None,
    ) -> tuple[discord.Embed, list[discord.File]]:
        if not response.type:
            raise MalformedTransactionResponse("Transaction response type not returned by API.")

        try:
            action = TransactionType(response.type)
        except ValueError as exc:
            raise MalformedTransactionResponse(f"Unknown transaction response type from API: {response.type}") from exc

        log.debug(f"Building transactions embed for type {action.name}", guild=guild)

        # LeaguePlayer Objects
        ptu_in = await self.league_player_from_transaction(response, player_in)
        if not ptu_in:
            raise MalformedTransactionResponse(
                f"Cut was processed but API did not return PlayerTransactionUpdate for {player_in.mention}. "
                "Announcement and discord updates have not been completed."
            )

        # Locals
        author_fmt = "Generic Transaction"
        author_icon: discord.File | str | None = None
        embed = discord.Embed()
        files: list[discord.File] = []
        franchise = None
        gm_id = None
        icon_url = None
        img = None
        tier = None

        # Image resource
        img = await utils.transaction_image_from_type(action)
        embed.set_image(url=f"attachment://{img.filename}")
        files.append(img)

        match action:
            case TransactionType.CUT:
                if not (ptu_in.old_team and ptu_in.old_team.tier and response.first_franchise):
                    raise MalformedTransactionResponse("Old team, tier, or first_franchise was not returned by API.")
                author_icon = await utils.fa_img_from_tier(ptu_in.old_team.tier, tiny=True)
                if author_icon:
                    files.append(author_icon)

                tier = ptu_in.old_team.tier

                author_fmt = f"{ptu_in.player.player.name} has been released by {ptu_in.old_team.name} ({tier})"

                franchise = response.first_franchise.name
                gm_id = gm_discord_id(response.first_franchise)

                embed.set_footer(text=f"Discord ID: {player_in.id}")
            case TransactionType.PICKUP:
                if not (ptu_in.new_team and response.second_franchise and response.second_franchise.id):
                    raise MalformedTransactionResponse("New team, second franchise, or second franchise ID was not returned by API.")
                author_icon = await self.franchise_logo(guild, response.second_franchise.id)

                tier = ptu_in.new_team.tier

                author_fmt = f"{ptu_in.player.player.name} has been signed by {ptu_in.new_team.name} ({tier})"

                franchise = response.second_franchise.name
                gm_id = gm_discord_id(response.second_franchise)
                embed.set_footer(text=f"Discord ID: {player_in.id}")
            case TransactionType.RESIGN:
                if not (ptu_in.new_team and response.second_franchise and response.second_franchise.id):
                    raise MalformedTransactionResponse("New team, second franchise, or second franchise ID was not returned by API.")
                author_icon = await self.franchise_logo(guild, response.second_franchise.id)

                tier = ptu_in.new_team.tier

                author_fmt = f"{ptu_in.player.player.name} has been re-signed by {ptu_in.new_team.name} ({tier})"

                franchise = response.second_franchise.name
                gm_id = gm_discord_id(response.second_franchise)
                embed.set_footer(text=f"Discord ID: {player_in.id}")
            case TransactionType.TEMP_FA | TransactionType.SUBSTITUTION:
                if not (ptu_in.new_team and response.second_franchise and response.second_franchise.id):
                    raise MalformedTransactionResponse("New team, second franchise, or second franchise ID was not returned by API.")
                author_icon = await self.franchise_logo(guild, response.second_franchise.id)

                tier = ptu_in.new_team.tier
                pname = ptu_in.player.player.name
                pteam = ptu_in.new_team.name

                author_fmt = f"{pname} has been signed to a temporary contract by {pteam} ({tier})"

                franchise = response.second_franchise.name

            case TransactionType.RETIRE:
                if guild.icon:
                    author_icon = guild.icon.url

                author_fmt = f"{ptu_in.player.player.name} has retired from the league"

                if response.first_franchise:
                    franchise = response.first_franchise.name
                    gm_id = gm_discord_id(response.first_franchise)

            case TransactionType.INACTIVE_RESERVE:
                if not (ptu_in.old_team and response.first_franchise and response.first_franchise.id):
                    raise MalformedTransactionResponse("Old team, first franchise, or first franchise ID was not returned by API.")
                author_icon = await self.franchise_logo(guild, response.first_franchise.id)

                tier = ptu_in.old_team.tier
                pname = ptu_in.player.player.name
                pteam = ptu_in.old_team.name

                author_fmt = f"{pname} has been moved to Inactive Reserve by {pteam} ({tier})"

                franchise = response.first_franchise.name
                gm_id = gm_discord_id(response.first_franchise)
                embed.set_footer(text=f"Discord ID: {player_in.id}")
            case TransactionType.IR_RETURN:
                if not (ptu_in.old_team and response.first_franchise and response.first_franchise.id):
                    raise MalformedTransactionResponse("Old team, first franchise, or first franchise ID was not returned by API.")
                author_icon = await self.franchise_logo(guild, response.first_franchise.id)

                tier = ptu_in.old_team.tier
                pname = ptu_in.player.player.name
                pteam = ptu_in.old_team.name

                author_fmt = f"{pname} has been removed from Inactive Reserve by {pteam} ({tier})"

                franchise = response.first_franchise.name
                gm_id = gm_discord_id(response.first_franchise)
                embed.set_footer(text=f"Discord ID: {player_in.id}")
            case _:
                raise NotImplementedError

        # Player Fields
        if player_out:
            embed.add_field(name="Player In", value=player_in.mention, inline=True)
            embed.add_field(name="Player Out", value=player_out.mention, inline=True)
        else:
            embed.add_field(name="Player", value=player_in.mention, inline=True)

        # Franchise Field
        if franchise:
            embed.add_field(name="Franchise", value=franchise, inline=True)

        # GM Field
        if gm_id:
            embed.add_field(
                name="GM",
                value=f"<@!{gm_id}>",
                inline=True,
            )

        if isinstance(author_icon, discord.File):
            icon_url = f"attachment://{author_icon.filename}"
        elif isinstance(author_icon, str):
            icon_url = author_icon

        embed.set_author(name=author_fmt, icon_url=icon_url or None)

        if tier:
            color = await utils.tier_color_by_name(guild, tier)
        else:
            color = discord.Color.blue()

        embed.colour = color
        return embed, files

    async def send_cut_msg(self, guild: discord.Guild, player: discord.Member) -> discord.Message | None:
        dm_status = await self._trans_dms_enabled(guild)

        if not dm_status:
            return None

        cutmsg = await self._get_cut_message(guild)
        if not cutmsg:
            return None

        embed = BlueEmbed(title=f"Message from {guild.name}", description=cutmsg)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        return await player.send(embed=embed)

    async def league_player_from_transaction(
        self, transaction: TransactionResponse, player: discord.Member | discord.User
    ) -> PlayerTransactionUpdates | None:
        if not transaction.player_updates:
            raise ValueError("Transaction response contains no Player Updates.")

        for x in transaction.player_updates:
            if not x:
                continue
            if x.player.player.discord_id == player.id:
                return x
        return None

    async def _retire_response_error(self, transaction: TransactionResponse, player: discord.Member | discord.User) -> str | None:
        transaction_id = getattr(transaction, "id", None)
        try:
            player_update = await self.league_player_from_transaction(transaction, player=player)
        except (AttributeError, ValueError) as exc:
            return f"transaction_id={transaction_id} validation_error={exc}"

        if not player_update:
            return f"transaction_id={transaction_id} validation_error=missing player update for discord_id={player.id}"

        # A retire can land the player in any of the non-playing statuses -- the API
        # returns DR (Dropped) as readily as FR (Former), and both mean the player is
        # out of the league. Demanding FR alone reported successful retirements as
        # failures and re-POSTed them, creating duplicate transactions.
        returned_status = getattr(player_update.player, "status", None)
        if not is_inactive_status(returned_status):
            expected = "/".join(sorted(INACTIVE_STATUS_VALUES))
            return f"transaction_id={transaction_id} returned_status={returned_status!r} expected_status=one of {expected}"

        return None

    # Auto retire on leave

    @staticmethod
    def _retire_is_retryable(exc: RscException) -> bool:
        """Whether a failed retire is worth trying again.

        Fails open on a status of `None`, which is what a transport error or an
        unparsable body produces. `RETIRE_MAX_ATTEMPTS` bounds the damage, and
        giving up on a network blip is the failure mode we are trying to remove.
        """
        if isinstance(exc, InternalServerError | BadGateway):
            return True
        if exc.status is None:
            return True
        return exc.status in RETRYABLE_RETIRE_STATUS

    async def _retire_error(self, exc: RscException) -> RscException:
        """Refine a bare `RscException` from `retire()` into a specific subclass.

        `retire()` raises `RscException(response=exc)` directly, so the API's
        `detail` string is never mapped to the types in `rsc.exceptions`. Running
        it through `translate_api_error` is what lets "not currently playing this
        season" be recognised as success rather than an error.
        """
        if isinstance(exc.response, ApiException):
            try:
                return await translate_api_error(exc.response)
            except Exception:  # Classification must never mask the original error.
                return exc
        return exc

    async def _player_is_retired(self, guild: discord.Guild, discord_id: int) -> bool:
        """Read back whether the API already considers this player retired."""
        try:
            players = await self.players(guild, discord_id=discord_id, limit=1)
        except Exception as exc:  # A failed read is simply "unknown", not "not retired".
            log.warning(f"{RETIRE_LOG_PREFIX} unable to re-read status for {discord_id}: {exc}", guild=guild)
            return False

        if not players:
            # No record for the current season means there is nothing to retire.
            return True

        return is_inactive_status(getattr(players[0], "status", None))

    async def _attempt_retire(self, guild: discord.Guild, member: discord.Member | discord.User) -> tuple[bool, str | None]:
        """Retire a member, retrying transient API failures. Returns (verified, failure_reason)."""
        last_reason: str | None = None

        for attempt in range(1, RETIRE_MAX_ATTEMPTS + 1):
            try:
                result = await self.retire(
                    guild,
                    player=member,
                    executor=guild.me,
                    notes="Player left the RSC discord server",
                    override=True,
                )
            except RscException as exc:
                translated = await self._retire_error(exc)

                # Not playing is the desired end state, so this is a success.
                if isinstance(translated, NotLeaguePlayer | MemberDoesNotExist):
                    log.info(
                        f"{RETIRE_LOG_PREFIX} {member.id} is already not playing this season. Nothing to retire.",
                        guild=guild,
                    )
                    return True, None

                last_reason = str(translated)
                if not self._retire_is_retryable(translated):
                    log.error(
                        f"{RETIRE_LOG_PREFIX} retire rejected for {member.id} and will not be retried: {last_reason}",
                        guild=guild,
                        exc_info=exc,
                    )
                    return False, last_reason

                log.warning(
                    f"{RETIRE_LOG_PREFIX} retire attempt {attempt}/{RETIRE_MAX_ATTEMPTS} failed for {member.id}: {last_reason}",
                    guild=guild,
                    exc_info=exc,
                )
            else:
                verification_error = await self._retire_response_error(result, player=member)
                if verification_error is None:
                    return True, None

                # The POST returned 200. Re-read before issuing another one --
                # blindly re-POSTing would create a duplicate transaction.
                if await self._player_is_retired(guild, member.id):
                    log.warning(
                        f"{RETIRE_LOG_PREFIX} retire response for {member.id} did not verify but the API "
                        f"reports the player as retired. Accepting. {verification_error}",
                        guild=guild,
                    )
                    return True, None

                last_reason = verification_error
                log.error(
                    f"{RETIRE_LOG_PREFIX} retire response did not verify for {member.id} "
                    f"on attempt {attempt}/{RETIRE_MAX_ATTEMPTS}: {verification_error}",
                    guild=guild,
                )

            if attempt < RETIRE_MAX_ATTEMPTS:
                await asyncio.sleep(RETIRE_BACKOFF[attempt - 1])

        return False, last_reason

    async def _report_retire_failure(
        self,
        guild: discord.Guild,
        member: discord.Member | discord.User,
        reason: str | None,
    ) -> None:
        """Surface a failed auto retirement to the league events channel.

        A log line alone is not a report -- nobody reads them until something has
        already gone wrong. `_try_post_embeds` no-ops without a configured channel
        and clears a dead one, so this is safe to call unconditionally.
        """
        embed = ErrorEmbed(
            title="Automatic Retirement Failed",
            description=(
                f"**{member.display_name}** left the server but could not be retired in the API.\n\n"
                "They are still active in the league. Run `/admin retire departed` to retire them."
            ),
        )
        embed.add_field(name="Member", value=f"<@{member.id}>", inline=True)
        embed.add_field(name="Member ID", value=str(member.id), inline=True)
        embed.add_field(name="Reason", value=str(reason or "Unknown"), inline=False)

        try:
            await self._try_post_embeds(guild, [embed])
        except Exception as exc:  # Reporting must never mask the original failure.
            log.warning(f"{RETIRE_LOG_PREFIX} unable to post failure report for {member.id}: {exc}", guild=guild)

    async def get_sub(self, member: discord.Member) -> Substitute | None:
        """Get sub from saved substitute list"""
        subs = await self._get_substitutes(member.guild)
        s = next((x for x in subs if x["player_in"] == member.id), None)
        return s

    async def announce_to_transaction_committee(self, guild: discord.Guild, **kwargs) -> discord.Message | None:
        channel = await self._trans_log_channel(guild)
        if not channel or not hasattr(channel, "send"):
            return None

        trole = await self._trans_role(guild)
        if not trole:
            return None

        log.debug(f"Announcing to {channel.name}")
        content = kwargs.pop("content", trole.mention)
        return await channel.send(
            content=content,
            allowed_mentions=discord.AllowedMentions(users=True, roles=True),
            **kwargs,
        )

    async def announce_to_franchise_transactions(
        self, guild: discord.Guild, franchise: str, gm: discord.Member | int, **kwargs
    ) -> discord.Message | None:
        channel_name = f"{franchise.lower().replace(' ', '-')}-transactions"

        # Some filters that discord won't allow
        channel_name = channel_name.replace("\x27", "")

        channel = discord.utils.get(guild.text_channels, name=channel_name)
        if not channel:
            logchan = await self._trans_log_channel(guild)
            if logchan and hasattr(logchan, "send"):
                await logchan.send(embed=ErrorEmbed(description=f"Unable to find franchise transaction channel: **{channel_name}**"))
            return None

        content = None
        if isinstance(gm, discord.Member):
            content = gm.mention

        if isinstance(gm, int):
            content = f"<@!{gm}>"

        log.debug(f"Announcing to {channel.name}", guild=guild)
        return await channel.send(
            content=content,
            allowed_mentions=discord.AllowedMentions(users=True, roles=True),
            **kwargs,
        )

    async def parse_trade_text(self, guild: discord.Guild, data: str) -> list[TradeObject]:
        if not data:
            raise TradeParserException(message="No trade data provided...")

        try:
            league_role = await utils.get_league_role(guild=guild)
            gm_role = await utils.get_gm_role(guild=guild)
        except ValueError as exc:
            raise TradeParserException(message=str(exc))

        # Iterate once to get all franchises involved
        log.debug("Finding all franchises in trade.", guild=guild)
        franchises: list[TradeFranchise] = []
        for line in data.splitlines():
            line = line.strip()
            log.debug(f"Line: {line}", guild=guild)

            if match := GM_TRADE_REGEX.search(line):
                if not match.group("gm"):
                    raise TradeParserException(message=f"Unable to parse GM name from: `{line}`")

                gm_str = match.group("gm").strip()
                log.debug(f"GM str: {gm_str}", guild=guild)

                # Find name in GM role members
                log.debug("Finding GM in role.")
                gm: discord.Member | None = None
                for m in gm_role.members:
                    tmp = await utils.remove_prefix(m)
                    if tmp.lower().startswith(gm_str.lower()):
                        gm = m
                        break

                if not gm:
                    raise TradeParserException(message=f"Unable to parse GM name from: `{line}`")
                log.debug(f"Trade GM: {gm.display_name}", guild=guild)

                # Get franchise from API
                fdata = await self.franchises(guild=guild, gm_discord_id=gm.id)
                if not fdata or len(fdata) > 1:
                    raise TradeParserException(message=f"Error finding franchise for GM: `{gm.display_name} ({gm.id})`")

                log.debug("Getting fname and fid")
                fname = fdata[0].name
                fid = fdata[0].id
                log.debug(f"Franchise ID: {fid} Name: {fname} GM: {gm.id}", guild=guild)
                f_object = TradeFranchise(gm=gm.id, name=fname, id=fid)
                franchises.append(f_object)

        # Initial validation on franchises
        if len(franchises) < 2:
            raise TradeParserException(message="Unable to identify 2 or more franchises in trade.")

        trade_list = []
        dest_franchise = None
        log.debug("Parsing trades...", guild=guild)
        for line in data.splitlines():
            line = line.strip()
            log.debug(f"Line: {line}")

            # Skip line breaks
            if len(line) == 0:
                continue

            # New franchise data
            elif line.startswith("---"):
                log.debug("Trade line break. Resetting destination...", guild=guild)
                dest_franchise = None
                continue

            # Check for GM
            elif match := GM_TRADE_REGEX.search(line):
                if not match.group("gm"):
                    raise TradeParserException(message=f"Unable to parse GM name from: `{line}`")

                gm_str = match.group("gm").strip()
                log.debug(f"GM str: {gm_str}", guild=guild)

                # Find name in GM role members
                gm = None
                for m in gm_role.members:
                    tmp = await utils.remove_prefix(m)
                    log.debug(f"GM tmp: {tmp}", guild=guild)
                    if tmp.lower().startswith(gm_str.lower()):
                        gm = m
                        break

                if not gm:
                    raise TradeParserException(message=f"Unable to parse GM name from: `{line}`")
                log.debug(f"Trade GM: {gm.display_name}", guild=guild)

                # Get franchise from API
                dest_franchise = next((x for x in franchises if x.gm == gm.id), None)

                log.debug(f"Destination Franchise: {dest_franchise}")
                if not dest_franchise:
                    raise TradeParserException(message=f"Error finding franchise for GM: `{gm.display_name} ({gm.id})`")
                continue

            # Player trade
            elif match := PLAYER_TRADE_REGEX.search(line):
                if not dest_franchise:
                    raise TradeParserException(message="Destination franchise is `None`")

                # Parse line with regex
                if not match or not match.group("player"):
                    raise TradeParserException(message=f"Unable to parse player trade from: `{line}`")

                m_str = match.group("player").strip()
                log.debug(f"Player str: {m_str}", guild=guild)
                player = discord.utils.get(league_role.members, display_name=m_str)

                if not player:
                    raise TradeParserException(message=f"Unable to parse player from: `{m_str}`")
                log.debug(f"Trade Player: {player.display_name}", guild=guild)

                # Get source franchise
                plist = await self.players(guild=guild, discord_id=player.id)

                if not plist:
                    raise TradeParserException(message=f"Unable to find league player: {player.mention})")

                pdata = plist[0]

                if not pdata.team:
                    raise TradeParserException(message=f"Player is not a team: {player.mention})")

                if not pdata.team.franchise:
                    raise TradeParserException(message=f"API Error. No franchise id or name for player: {player.mention}")

                sf_id = pdata.team.franchise.id
                sf_name = pdata.team.franchise.name
                log.debug(f"Source. ID={sf_id} NAME={sf_name}", guild=guild)
                sfranchise = TradeFranchise(id=sf_id, name=sf_name, gm=None)

                # Get destination team name (find by current tier)
                dest_team = None
                if match.group("team"):
                    dest_team = match.group("team").strip()
                else:
                    if not pdata.tier:
                        raise TradeParserException(message=f"API Error. Player has no tier data: {player.mention}")

                    team_list = await self.teams(guild=guild, franchise=dest_franchise.name, tier=pdata.tier.name)

                    if not team_list or len(team_list) > 1:
                        raise TradeParserException(
                            message=f"Error finding destination team. Franchise: `{dest_franchise.id}` Tier: `{pdata.tier.name}`"
                        )

                    dest_team = team_list[0].name

                log.debug(f"Destination Team Name: {dest_team}", guild=guild)

                tvalue = TradeItem(player=TradePlayer(id=player.id, team=dest_team))
                log.debug(
                    f"Player Trade. Src Franchise: {sfranchise.name} Dest Franchise: {dest_franchise.name} Player: {player.id}", guild=guild
                )

                item = TradeObject(source=sfranchise, destination=dest_franchise, value=tvalue)
                trade_list.append(item)
            elif match := FUTURE_TRADE_REGEX.match(line):
                if not match:
                    raise TradeParserException(message=f"Unable to parse future trade from: `{line}`")
                if not dest_franchise:
                    raise TradeParserException(message="Destination franchise is `None`. Parser error.")

                gm_str = match.group("gm").strip()
                tier = match.group("tier")
                round = int(match.group("round"))

                # Find name in GM role members
                source_gm = None
                for m in gm_role.members:
                    tmp = await utils.remove_prefix(m)
                    if tmp.lower().startswith(gm_str.lower()):
                        source_gm = m
                        break

                if not source_gm:
                    raise TradeParserException(message=f"Error finding discord member for future source GM: `{gm_str}`")

                sfranchise = TradeFranchise(id=None, name=None, gm=source_gm.id)

                tvalue = TradeItem(pick=DraftPickTrade(tier=tier.capitalize(), round=round, number=0, future=True))
                log.debug(
                    f"Future Trade. Src Franchise: {sfranchise.name} Dest Franchise: {dest_franchise.name}",
                    guild=guild,
                )
                if tvalue.pick:
                    log.debug(
                        f"Trade Value: Tier={tvalue.pick.tier} Round={tvalue.pick.round} "
                        f"Number={tvalue.pick.number} Future={tvalue.pick.future}",
                        guild=guild,
                    )
                else:
                    log.warning("Future trade value has no pick data.", guild=guild)

                item = TradeObject(source=sfranchise, destination=dest_franchise, value=tvalue)
                trade_list.append(item)

            elif match := PICK_TRADE_REGEX.match(line):
                if not match:
                    raise TradeParserException(message=f"Unable to parse future trade from: `{line}`")
                if not dest_franchise:
                    raise TradeParserException(message="Destination franchise is `None`. Parser error.")

                tier = match.group("tier")
                round = int(match.group("round"))
                pick = int(match.group("pick"))

                # Check if GM was provided (3+ way trade)
                gm_str = None
                source_gm = None
                sfranchise = None
                if match.group("gm"):
                    gm_str = match.group("gm").strip()

                    # Find name in GM role members
                    source_gm = None
                    for m in gm_role.members:
                        tmp = await utils.remove_prefix(m)
                        if tmp.lower().startswith(gm_str.lower()):
                            source_gm = m
                            break

                    if not source_gm:
                        raise TradeParserException(message=f"Error finding discord member for future source GM: `{gm_str}`")
                else:
                    # 2 way trade. Validate against franchise list
                    if len(franchises) > 2:
                        raise TradeParserException(
                            message="Pick trade does not contain source GM name and this trade involves more than 2 franchises."
                        )

                    # Grab franchise that isn't the destination franchise
                    for f in franchises:
                        if f.gm != dest_franchise.gm:
                            sfranchise = f

                log.debug(
                    f"Pick Trade. Source GM: {source_gm} Source Franchise: {sfranchise}",
                    guild=guild,
                )
                if not sfranchise and source_gm:
                    sfranchise = TradeFranchise(id=None, name=None, gm=source_gm.id)

                tvalue = TradeItem(pick=DraftPickTrade(tier=tier.capitalize(), round=round, number=pick, future=False))

                if not sfranchise:
                    raise TradeParserException(message="Unable to determine source franchise for pick trade.")
                item = TradeObject(source=sfranchise, destination=dest_franchise, value=tvalue)

                log.debug(
                    f"Future Trade. Src Franchise: {sfranchise.name} Dest Franchise: {dest_franchise.name}",
                    guild=guild,
                )
                if tvalue.pick:
                    log.debug(
                        f"Trade Value: Tier={tvalue.pick.tier} Round={tvalue.pick.round} "
                        f"Number={tvalue.pick.number} Future={tvalue.pick.future}",
                        guild=guild,
                    )
                else:
                    log.warning("Future trade value has no pick data.", guild=guild)
                trade_list.append(item)

            else:
                raise TradeParserException(message=f"Unknown line in trade data: `{line}`")

        return trade_list

    async def build_trade_embed(self, guild: discord.Guild, trades: list[TradeObject]) -> tuple[list[int], discord.Embed]:
        trade_groups = [list(t) for _, t in itertools.groupby(trades, lambda t: t.destination)]
        embed = BlueEmbed(title="Trade Confirmed")

        gms = []
        for group in trade_groups:
            dest: str | None = None
            trade_fmt = []
            for trade in group:
                if trade.destination.gm and trade.destination.gm not in gms:
                    gms.append(trade.destination.gm)

                # Get GM for field name
                if not dest:
                    if trade.destination.name:
                        m = None
                        if trade.destination.gm:
                            m = guild.get_member(trade.destination.gm)

                        if m:
                            gm_name = await utils.remove_prefix(m)
                            gm_name = await utils.strip_discord_accolades(gm_name)
                            log.debug(f"Embed GM Name: {gm_name}", guild=guild)
                            dest = f"{trade.destination.name} ({gm_name.strip()})"
                        else:
                            dest = trade.destination.name
                    else:
                        dest = "Error"

                # Process trade item
                if trade.value.player:
                    # Append to ping list
                    if trade.value.player.id:
                        gms.append(trade.value.player.id)
                    if trade.value.player.team:
                        trade_fmt.append(f"<@!{trade.value.player.id}> to {trade.value.player.team}")
                    else:
                        trade_fmt.append(f"<@!{trade.value.player.id}>")
                    continue

                if trade.value.pick:
                    # Format Round
                    round_fmt = None
                    match trade.value.pick.round:
                        case 1:
                            round_fmt = "1st"
                        case 2:
                            round_fmt = "2nd"
                        case 3:
                            round_fmt = "3rd"
                        case _:
                            round_fmt = f"{trade.value.pick.round}th"

                    # Determine if need source
                    src_fmt = None
                    if len(trade_groups) > 2 and trade.source.gm:
                        # Future Pick Trade
                        src_fmt = f"<@!{trade.source.gm}>"

                    if trade.value.pick.future:
                        # Future Pick Trade
                        if src_fmt:
                            trade_fmt.append(f"{src_fmt} Future {round_fmt} Round {trade.value.pick.tier}")
                        else:
                            trade_fmt.append(f"Future {round_fmt} Round {trade.value.pick.tier}")
                    elif src_fmt:
                        trade_fmt.append(f"{src_fmt} {round_fmt} Round {trade.value.pick.tier} ({trade.value.pick.number})")
                    else:
                        trade_fmt.append(f"{round_fmt} Round {trade.value.pick.tier} ({trade.value.pick.number})")

            # Build field
            embed.add_field(name=dest, value="\n".join(trade_fmt), inline=False)

        # Add thumbnail
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        return gms, embed

    async def get_franchise_transaction_channel(self, guild: discord.Guild, franchise_name: str) -> discord.TextChannel | None:
        """Find franchise transaction channel"""
        tchannel_name = await self.get_franchise_transaction_channel_name(franchise_name)
        log.debug(f"Searching for transaction channel: {tchannel_name}", guild=guild)

        tchannel = discord.utils.get(guild.channels, name=tchannel_name)
        if not tchannel:
            return None

        if not isinstance(tchannel, discord.TextChannel):
            return None
        return tchannel

    async def get_franchise_transaction_channel_name(self, franchise_name: str) -> str:
        franchise_fmt = franchise_name.lower().replace(" ", "-")
        franchise_fmt = re.sub(r"[^a-z0-9\x2d]+", "", franchise_fmt, flags=re.IGNORECASE)
        tchannel_name = f"{franchise_fmt}-transactions"
        return tchannel_name

    # API

    async def sign(
        self,
        guild: discord.Guild,
        player: discord.Member,
        team: str,
        executor: discord.Member,
        notes: str | None = None,
        override: bool = False,
    ) -> TransactionResponse:
        """Sign player to a team"""
        async with self.api_client(guild) as client:
            api = TransactionsApi(client)
            data = PlayerTeamInput(
                player=player.id,
                league=self._league[guild.id],
                team=team,
                executor=executor.id,
                notes=notes,
                admin_override=override,
            )
            log.debug(f"Sign Parameters: {data}", guild=guild)
            try:
                return await api.transactions_sign_create(data)
            except ApiException as exc:
                raise await translate_api_error(exc)

    async def cut(
        self,
        guild: discord.Guild,
        player: discord.Member,
        executor: discord.Member,
        notes: str | None = None,
        override: bool = False,
    ) -> TransactionResponse:
        """Cut a player from their team"""
        async with self.api_client(guild) as client:
            api = TransactionsApi(client)
            data = PlayerInput(
                player=player.id,
                league=self._league[guild.id],
                executor=executor.id,
                notes=notes,
                admin_override=override,
            )
            log.debug(f"Cut Parameters: {data}", guild=guild)
            try:
                return await api.transactions_cut_create(data)
            except ApiException as exc:
                raise await translate_api_error(exc)

    async def resign(
        self,
        guild: discord.Guild,
        player: discord.Member,
        team: str,
        executor: discord.Member,
        notes: str | None = None,
        override: bool = False,
    ) -> TransactionResponse:
        """Resign player to a team"""
        async with self.api_client(guild) as client:
            api = TransactionsApi(client)
            data = PlayerTeamInput(
                player=player.id,
                league=self._league[guild.id],
                team=team,
                executor=executor.id,
                notes=notes,
                admin_override=override,
            )
            log.debug(f"Resign Parameters: {data}", guild=guild)
            try:
                return await api.transactions_resign_create(data)
            except ApiException as exc:
                raise await translate_api_error(exc)

    async def set_captain(self, guild: discord.Guild, id: int) -> LeaguePlayer:
        """Set a player as captain using their discord ID"""
        async with self.api_client(guild) as client:
            api = LeaguePlayersApi(client)
            return await api.league_players_set_captain_create(id)

    async def substitution(
        self,
        guild: discord.Guild,
        player_in: discord.Member,
        player_out: discord.Member,
        executor: discord.Member,
        notes: str | None = None,
        override: bool = False,
    ) -> TransactionResponse:
        """Sub a player in for another player"""
        async with self.api_client(guild) as client:
            api = TransactionsApi(client)
            data = SubInput(
                league=self._league[guild.id],
                player_in=player_in.id,
                player_out=player_out.id,
                executor=executor.id,
                notes=notes,
                admin_override=override,
            )
            log.debug(f"Sub Data: {data}", guild=guild)
            try:
                return await api.transactions_substitution_create(data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def expire_sub(
        self,
        guild: discord.Guild,
        player: discord.Member,
        executor: discord.Member,
    ) -> LeaguePlayer:
        """Sub a player in for another player"""
        async with self.api_client(guild) as client:
            api = TransactionsApi(client)
            data = PlayerInput(league=self._league[guild.id], player=player.id, executor=executor.id)
            log.debug(f"Expire Sub Data: {data}", guild=guild)
            try:
                return await api.transactions_expire_create(data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def retire(
        self,
        guild: discord.Guild,
        player: discord.Member | discord.User,
        executor: discord.Member,
        notes: str | None = None,
        override: bool = False,
    ) -> TransactionResponse:
        """Retire a player from the league"""
        async with self.api_client(guild) as client:
            api = TransactionsApi(client)
            data = PlayerInput(
                league=self._league[guild.id],
                player=player.id,
                executor=executor.id,
                notes=notes,
                admin_override=override,
            )
            log.debug(f"Retire Data: {data}", guild=guild)
            try:
                return await api.transactions_retire_create(data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def inactive_reserve(
        self,
        guild: discord.Guild,
        player: discord.Member,
        executor: discord.Member,
        notes: str | None = None,
        override: bool = False,
        redshirt: bool = False,
        remove: bool = False,
    ) -> TransactionResponse:
        """Move a player or AGM to inactive reserve"""
        async with self.api_client(guild) as client:
            api = TransactionsApi(client)
            data = IRInput(
                league=self._league[guild.id],
                player=player.id,
                executor=executor.id,
                notes=notes,
                admin_override=override,
                redshirt=redshirt,
                remove_from_ir=remove,
            )
            log.debug(f"IR Data: {data}", guild=guild)
            try:
                return await api.transactions_inactive_reserve_create(data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def transaction_history(
        self,
        guild: discord.Guild,
        player: discord.Member | None = None,
        executor: discord.Member | None = None,
        season: int | None = None,
        trans_type: TransactionType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TransactionResponse]:
        """Fetch transaction history based on specified criteria"""
        async with self.api_client(guild) as client:
            api = TransactionsApi(client)
            player_id = player.id if player else None
            executor_id = executor.id if executor else None
            t_type = str(trans_type) if trans_type else None
            log.debug(
                f"Transaction History Query. Player: {player_id} Executor: {executor_id} Season: {season} Type: {trans_type}",
                guild=guild,
            )
            try:
                league_id = self._league[guild.id]
                trans_list = await api.transactions_history_list(
                    league=league_id,
                    player=player_id,
                    executor=executor_id,
                    transaction_type=t_type,
                    season_number=season,
                    limit=limit,
                    offset=offset,
                )
                return trans_list.results
            except ApiException as exc:
                raise RscException(response=exc)

    async def paged_transaction_history(
        self,
        guild: discord.Guild,
        player: discord.Member | None = None,
        executor: discord.Member | None = None,
        season: int | None = None,
        trans_type: TransactionType | None = None,
        per_page: int = 50,
    ) -> AsyncIterator[TransactionResponse]:
        """Fetch transaction history based on specified criteria"""
        player_id = player.id if player else None
        executor_id = executor.id if executor else None
        t_type = str(trans_type) if trans_type else None
        log.debug(
            f"Paged Transaction History Query. Player: {player_id} Executor: {executor_id} Season: {season} Type: {trans_type}",
            guild=guild,
        )

        offset = 0
        async with self.api_client(guild) as client:
            api = TransactionsApi(client)
            while True:
                log.debug(f"Offset: {offset}")
                try:
                    league_id = self._league[guild.id]
                    trans_list = await api.transactions_history_list(
                        league=league_id,
                        player=player_id,
                        executor=executor_id,
                        transaction_type=t_type,
                        season_number=season,
                        limit=per_page,
                        offset=offset,
                    )
                    results = trans_list.results
                    has_next = bool(trans_list.next)

                    if not results:
                        break

                    for transaction in results:
                        yield transaction

                    if not has_next:
                        break

                    offset += per_page
                except ApiException as exc:
                    raise RscException(response=exc)

    async def transaction_history_by_id(self, guild: discord.Guild, transaction_id: int) -> TransactionResponse:
        """Fetch transaction history based on specified criteria"""
        async with self.api_client(guild) as client:
            api = TransactionsApi(client)
            try:
                return await api.transactions_history_retrieve(id=transaction_id)
            except ApiException as exc:
                raise RscException(response=exc)

    async def trade(
        self,
        guild: discord.Guild,
        trades: list[TradeObject],
        executor: discord.Member,
        notes: str | None = None,
        override: bool = False,
    ) -> TransactionResponse:
        """Fetch transaction history based on specified criteria"""
        async with self.api_client(guild) as client:
            api = TransactionsApi(client)
            try:
                schema = TradeTransaction(
                    league=self._league[guild.id],
                    trades=trades,
                    executor=executor.id,
                    notes=notes or "",
                    admin_override=override,
                )
                log.debug(f"Schema: {pformat(schema)}", guild=guild)
                return await api.transactions_trade_create(schema)
            except ApiException as exc:
                raise RscException(response=exc)

    async def validate_franchise_futures(
        self,
        guild: discord.Guild,
        franchise_name: str,
    ) -> FranchiseFuturesValidationResponse:
        """Validate a franchise future board."""
        async with self.api_client(guild) as client:
            api = TransactionsApi(client)
            try:
                schema = FranchiseFuturesValidation(
                    league=self._league[guild.id],
                    franchise_name=franchise_name,
                )
                log.debug(f"Futures validation schema: {schema}", guild=guild)
                return await api.transactions_trade_validate_futures_create(schema)
            except ApiException as exc:
                raise RscException(response=exc)

    async def draft(
        self,
        guild: discord.Guild,
        player: discord.Member,
        executor: discord.Member,
        team: str,
        round: int,
        pick: int,
        override: bool = False,
    ) -> TransactionResponse:
        """Fetch transaction history based on specified criteria"""
        async with self.api_client(guild) as client:
            api = TransactionsApi(client)
            try:
                draft_pick = DraftInput(
                    league=self._league[guild.id],
                    player=player.id,
                    executor=executor.id,
                    team=team,
                    round=round,
                    number=pick,
                    admin_override=override,
                )
                log.debug(f"Draft Schema: {pformat(draft_pick)}", guild=guild)
                return await api.transactions_draft_create(draft_pick)
            except ApiException as exc:
                raise RscException(response=exc)

    # Config

    async def _trans_role(self, guild: discord.Guild) -> discord.Role | None:
        trans_role_id = await self.config.custom("Transactions", str(guild.id)).TransRole()
        return guild.get_role(trans_role_id)

    async def _save_trans_role(self, guild: discord.Guild, trans_role_id: int | None):
        await self.config.custom("Transactions", str(guild.id)).TransRole.set(trans_role_id)

    async def _trans_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        channel_id = await self.config.custom("Transactions", str(guild.id)).TransChannel()
        if not channel_id:
            return None
        c = guild.get_channel(channel_id)
        if not c or not isinstance(c, discord.TextChannel):
            return None
        return c

    async def _save_trans_channel(self, guild: discord.Guild, trans_channel: int | None):
        await self.config.custom("Transactions", str(guild.id)).TransChannel.set(trans_channel)

    async def _trans_log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        channel_id = await self.config.custom("Transactions", str(guild.id)).TransLogChannel()
        if not channel_id:
            return None
        c = guild.get_channel(channel_id)
        if not c or not isinstance(c, discord.TextChannel):
            return None
        return c

    async def _save_trans_log_channel(self, guild: discord.Guild, trans_log_channel: int | None):
        await self.config.custom("Transactions", str(guild.id)).TransLogChannel.set(trans_log_channel)

    async def _get_cut_message(self, guild: discord.Guild) -> str | None:
        return await self.config.custom("Transactions", str(guild.id)).CutMessage()

    async def _save_cut_message(self, guild: discord.Guild, message: str):
        await self.config.custom("Transactions", str(guild.id)).CutMessage.set(message)

    async def _notifications_enabled(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Transactions", str(guild.id)).TransNotifications()

    async def _set_notifications(self, guild: discord.Guild, enabled: bool):
        await self.config.custom("Transactions", str(guild.id)).TransNotifications.set(enabled)

    async def _gm_notifications_enabled(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Transactions", str(guild.id)).TransGMNotifications()

    async def _set_gm_notifications(self, guild: discord.Guild, enabled: bool):
        await self.config.custom("Transactions", str(guild.id)).TransGMNotifications.set(enabled)

    async def _trade_announcements_enabled(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Transactions", str(guild.id)).TradeAnnouncements()

    async def _set_trade_announcements(self, guild: discord.Guild, enabled: bool):
        await self.config.custom("Transactions", str(guild.id)).TradeAnnouncements.set(enabled)

    async def _trade_role_updates_enabled(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Transactions", str(guild.id)).TradeRoleUpdates()

    async def _set_trade_role_updates(self, guild: discord.Guild, enabled: bool):
        await self.config.custom("Transactions", str(guild.id)).TradeRoleUpdates.set(enabled)

    async def _trans_dms_enabled(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Transactions", str(guild.id)).TransDMs()

    async def _set_trans_dm(self, guild: discord.Guild, enabled: bool):
        await self.config.custom("Transactions", str(guild.id)).TransDMs.set(enabled)

    async def _get_substitutes(self, guild: discord.Guild) -> list[Substitute]:
        return await self.config.custom("Transactions", str(guild.id)).Substitutes()

    async def _set_substitutes(self, guild: discord.Guild, subs: list[Substitute]):
        await self.config.custom("Transactions", str(guild.id)).Substitutes.set(subs)

    async def _add_substitute(self, guild: discord.Guild, sub: Substitute):
        s = await self.config.custom("Transactions", str(guild.id)).Substitutes()
        s.append(sub)
        await self._set_substitutes(guild, s)

    async def _rm_substitute(self, guild: discord.Guild, sub: Substitute):
        s = await self.config.custom("Transactions", str(guild.id)).Substitutes()
        try:
            s.remove(sub)
        except ValueError:
            return
        await self._set_substitutes(guild, s)
