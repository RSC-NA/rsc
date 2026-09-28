import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import partial
from typing import Any

import discord
from redbot.core import app_commands

from rsc.admin import AdminMixIn
from rsc.admin.views import DMConfirmView, build_permfa_poll_view
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    BlueEmbed,
    EmbedLimits,
    ErrorEmbed,
    GreenEmbed,
    OrangeEmbed,
    YellowEmbed,
)
from rsc.enums import Status
from rsc.exceptions import RscException
from rsc.logs import GuildLogAdapter
from rsc.tiers import TierMixIn
from rsc.utils.dm import DMOutcome

logger = logging.getLogger("red.rsc.admin.permfa_poll")
log = GuildLogAdapter(logger)

POLL_CONFIG_GROUP = "PermFAPoll"
POLL_DURATION = timedelta(hours=72)
# Pause between DM edits while closing a poll. Edits are cheap but a large tier
# should not burst dozens of requests at Discord at once.
SWEEP_EDIT_DELAY = 1.0

# Embeds are sent one per followup, so each only has to fit its own 6000 limit.
# Leave headroom for the title and "(cont.)" field names.
RESULTS_EMBED_BUDGET = EmbedLimits.Total - 500

# Tier and poll id used by `/admin permfa dmtest` buttons. Real tier ids are
# positive and real poll ids are snowflakes, so a preview never matches a poll.
PREVIEW_POLL_ID = 0
CURRENT_ANSWER_FIELD = "Your current answer"


def _now() -> int:
    return int(datetime.now(UTC).timestamp())


class PollResponse(StrEnum):
    YES = "yes"
    NO = "no"


class PollDelivery(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PollRecipient:
    name: str
    mmr: int | None = None
    delivery: str = PollDelivery.QUEUED
    # [dm_channel_id, message_id] pairs. Only held until the poll is closed and
    # the DMs have been edited, then cleared.
    messages: list[list[int]] = field(default_factory=list)
    response: str | None = None
    responded_at: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mmr": self.mmr,
            "delivery": str(self.delivery),
            "messages": self.messages,
            "response": self.response,
            "responded_at": self.responded_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PollRecipient":
        return cls(
            name=data.get("name") or "Unknown",
            mmr=data.get("mmr"),
            delivery=data.get("delivery") or PollDelivery.QUEUED,
            messages=[list(m) for m in data.get("messages") or []],
            response=data.get("response"),
            responded_at=data.get("responded_at"),
        )


@dataclass
class PermFAPoll:
    poll_id: int
    tier_id: int
    tier_name: str
    season: int | None
    created_at: int
    expires_at: int
    created_by: int
    closed_at: int | None = None
    closed_by: int | None = None
    last_remind_at: int | None = None
    dms_cleaned: bool = False
    recipients: dict[int, PollRecipient] = field(default_factory=dict)

    def is_open(self, now: int) -> bool:
        """The single authority on whether answers are still accepted."""
        return self.closed_at is None and now < self.expires_at

    def closed_time(self) -> int:
        """When the poll closed. An expired poll the sweep has not reached yet closed at its deadline."""
        return self.closed_at if self.closed_at is not None else self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "PollId": self.poll_id,
            "TierId": self.tier_id,
            "TierName": self.tier_name,
            "Season": self.season,
            "CreatedAt": self.created_at,
            "ExpiresAt": self.expires_at,
            "CreatedBy": self.created_by,
            "ClosedAt": self.closed_at,
            "ClosedBy": self.closed_by,
            "LastRemindAt": self.last_remind_at,
            "DmsCleaned": self.dms_cleaned,
            "Recipients": {str(uid): r.to_dict() for uid, r in self.recipients.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PermFAPoll | None":
        """Parse a stored record. Tolerates missing keys, since Red does not merge
        registered defaults into partial-identifier reads."""
        poll_id = data.get("PollId")
        tier_id = data.get("TierId")
        if not (poll_id and tier_id):
            return None
        return cls(
            poll_id=int(poll_id),
            tier_id=int(tier_id),
            tier_name=data.get("TierName") or "Unknown",
            season=data.get("Season"),
            created_at=data.get("CreatedAt") or 0,
            expires_at=data.get("ExpiresAt") or 0,
            created_by=data.get("CreatedBy") or 0,
            closed_at=data.get("ClosedAt"),
            closed_by=data.get("ClosedBy"),
            last_remind_at=data.get("LastRemindAt"),
            dms_cleaned=bool(data.get("DmsCleaned")),
            recipients={int(uid): PollRecipient.from_dict(r) for uid, r in (data.get("Recipients") or {}).items()},
        )


@dataclass
class PollClickResult:
    """What a button press should do to the DM it was pressed on."""

    embed: discord.Embed
    keep_buttons: bool


defaults_poll: dict[str, Any] = {
    "PollId": None,
    "TierId": None,
    "TierName": None,
    "Season": None,
    "CreatedAt": None,
    "ExpiresAt": None,
    "CreatedBy": None,
    "ClosedAt": None,
    "ClosedBy": None,
    "LastRemindAt": None,
    "DmsCleaned": False,
    "Recipients": {},
}


class AdminPermFAPollMixIn(AdminMixIn):
    """Poll a tier's Permanent Free Agents on converting to regular Free Agents.

    One poll is stored per (guild, tier). Answers are recorded from DM buttons
    (`PermFAPollButton`) and can be changed until the poll closes, 72 hours after
    it starts or earlier through `close`. When a poll closes, every DM it sent is
    edited to remove the buttons.

    Closing is driven by one asyncio timer per poll rather than a recurring
    loop, so nothing runs while no poll is waiting to close. Timers are re-armed
    from Config on startup by `setup_permfa_poll_timers`.
    """

    def __init__(self):
        log.debug("Initializing AdminMixIn:PermFAPoll")

        self.config.init_custom(POLL_CONFIG_GROUP, 2)
        self.config.register_custom(POLL_CONFIG_GROUP, **defaults_poll)
        # Every write to a poll is a read-modify-write under its lock. Clicks,
        # delivery callbacks and the close sweep all touch the same record.
        self._permfa_poll_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._permfa_poll_timers: dict[tuple[int, int], asyncio.Task] = {}
        super().__init__()

    _permfa = app_commands.Group(
        name="permfa",
        description="Poll Permanent Free Agents about converting to Free Agents",
        parent=AdminMixIn._admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # Startup

    async def setup_permfa_poll_timers(self, guild: discord.Guild) -> None:
        """Re-arm close timers for polls that still need their DMs cleaned up.

        Runs from every `setup()`, including reconnects, so arming never
        replaces a live timer. A poll that expired while the bot was down is
        swept straight away.
        """
        now = _now()
        for poll in await self._get_permfa_polls(guild.id):
            if poll.dms_cleaned:
                continue
            delay = poll.expires_at - now if poll.is_open(now) else 0
            log.debug(f"Arming PermFA poll timer for {poll.tier_name} in {delay}s", guild=guild)
            self._arm_permfa_poll_timer(guild.id, poll.tier_id, delay)

    def cancel_permfa_poll_timers(self) -> None:
        """Cancel every pending close timer. Interrupted sweeps resume on the next load."""
        for task in self._permfa_poll_timers.values():
            task.cancel()
        self._permfa_poll_timers.clear()

    # Commands

    @_permfa.command(name="poll", description="DM a tier's PermFAs asking if they want to convert to Free Agents")
    @app_commands.describe(tier='Tier to poll (Ex: "Elite")')
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)
    async def _permfa_poll_cmd(self, interaction: discord.Interaction, tier: str):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        tier = tier.capitalize()
        if not await self.is_valid_tier(guild, tier):
            return await interaction.followup.send(embed=ErrorEmbed(description=f"**{tier}** is not a valid tier."), ephemeral=True)

        try:
            tier_id = await self.tier_id_by_name(guild, tier)
            season = await self.current_season(guild)
            players = [p async for p in self.paged_players(guild, status=Status.PERM_FA, tier_name=tier)]
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
        except ValueError as exc:
            return await interaction.followup.send(embed=ErrorEmbed(description=str(exc)), ephemeral=True)

        existing = await self._get_permfa_poll(guild.id, tier_id)
        blocked = self._permfa_poll_blocked_reason(existing)
        if blocked:
            return await interaction.followup.send(embed=ErrorEmbed(description=blocked), ephemeral=True)

        # Keyed by discord id. PermFAs with no discord id cannot be DMed at all.
        by_id = {p.player.discord_id: p for p in players if p.player.discord_id}
        no_discord_id = [p.player.name or f"League player {p.id}" for p in players if not p.player.discord_id]

        if not players:
            return await interaction.followup.send(
                embed=YellowEmbed(title="No PermFAs", description=f"There are no Permanent Free Agents in **{tier}**."),
                ephemeral=True,
            )

        to_dm, left_guild, lookup_failed = await self._resolve_members_by_id(guild, list(by_id))
        if not to_dm:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Nobody To DM",
                    description=(
                        f"All **{len(players)}** PermFA(s) in **{tier}** are unreachable. "
                        "They have left the server, could not be looked up, or have no Discord ID in the API."
                    ),
                ),
                ephemeral=True,
            )

        # Confirmation gate. Nothing is stored or queued until Confirm is pressed.
        desc = (
            f"About to DM **{len(to_dm)}** PermFA(s) in **{tier}** asking if they want to convert to a Free Agent. "
            f"The poll closes **{int(POLL_DURATION.total_seconds() // 3600)} hours** after you confirm.\n\n"
            f"Skipped (left the server): **{len(left_guild)}**\n"
            f"Skipped (lookup failed): **{len(lookup_failed)}**\n"
            f"Skipped (no Discord ID in the API): **{len(no_discord_id)}**"
        )
        if existing:
            desc += (
                f"\n\n\N{WARNING SIGN} This replaces the results of the previous **{tier}** poll started "
                f"<t:{existing.created_at}:F> by <@{existing.created_by}>."
            )

        confirm_embed = BlueEmbed(title="Confirm PermFA Conversion Poll", description=desc)
        confirm_embed.add_field(
            name="Recipients",
            value=self._format_truncated_list([m.mention for m in to_dm]),
            inline=False,
        )
        if no_discord_id:
            confirm_embed.add_field(name="No Discord ID", value=self._format_truncated_list(no_discord_id), inline=False)

        confirm_view = DMConfirmView(interaction, confirm_embed, loading_title="Queueing PermFA Poll DMs")
        await confirm_view.prompt()
        await confirm_view.wait()

        if not confirm_view.result:
            return

        now = _now()
        poll = PermFAPoll(
            # The command's interaction id is a unique snowflake, so a replaced
            # poll's buttons can never match the new one.
            poll_id=interaction.id,
            tier_id=tier_id,
            tier_name=tier,
            season=season.number if season else None,
            created_at=now,
            expires_at=now + int(POLL_DURATION.total_seconds()),
            created_by=interaction.user.id,
            recipients={m.id: PollRecipient(name=by_id[m.id].player.name or m.display_name, mmr=by_id[m.id].current_mmr) for m in to_dm},
        )

        # Re-check under the lock. The confirm prompt can sit open for a while,
        # and two admins confirming at once must not both start a poll.
        async with self._permfa_poll_lock(guild.id, tier_id):
            blocked = self._permfa_poll_blocked_reason(await self._get_permfa_poll(guild.id, tier_id))
            if not blocked:
                await self._save_permfa_poll(guild.id, poll)

        if blocked:
            return await interaction.edit_original_response(embed=ErrorEmbed(description=blocked), view=None)

        self._arm_permfa_poll_timer(guild.id, tier_id, poll.expires_at - now, replace=True)
        log.info(f"{interaction.user} started a PermFA conversion poll for {tier} with {len(to_dm)} recipient(s)", guild=guild)

        for member in to_dm:
            # A fresh view per DM. `send()` stores the view against the message id,
            # so a shared instance would have its cache key rewritten on every send.
            await self._dm_helper.enqueue(
                member,
                embed=self._permfa_poll_dm_embed(guild, poll, poll.recipients[member.id]),
                view=build_permfa_poll_view(guild.id, tier_id, poll.poll_id),
                precheck=self._permfa_poll_precheck(guild.id, tier_id, poll.poll_id),
                on_result=self._permfa_poll_on_result(guild, tier_id, poll.poll_id, member.id),
            )

        await interaction.edit_original_response(
            embed=GreenEmbed(
                title="PermFA Poll Started",
                description=(
                    f"**{len(to_dm)}** DMs queued for **{tier}**. The poll closes <t:{poll.expires_at}:F> (<t:{poll.expires_at}:R>).\n\n"
                    "Use `/admin permfa responses` to see answers and `/admin dmstatus` to track delivery."
                ),
            ),
            view=None,
        )

    @_permfa.command(name="dmtest", description="Send a preview of the PermFA conversion poll DM to a member")
    @app_commands.describe(
        member="Member to send the preview to (yourself, for example)",
        reminder="Preview the reminder version of the DM",
    )
    async def _permfa_dm_test_cmd(self, interaction: discord.Interaction, member: discord.Member, reminder: bool = False):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        # The preview uses the member's own tier, as the real poll would
        try:
            players = await self.players(guild, discord_id=member.id, limit=1)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        league_player = players[0] if players else None
        tier_name = league_player.tier.name if league_player and league_player.tier else None
        if not (league_player and tier_name):
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"{member.mention} does not have a tier in the API, so there is no tier to preview."),
                ephemeral=True,
            )

        # Only used for the "Season N" wording, so an API failure is not fatal
        try:
            season = await self.current_season(guild)
        except RscException:
            season = None

        now = _now()
        preview = PermFAPoll(
            poll_id=PREVIEW_POLL_ID,
            tier_id=PREVIEW_POLL_ID,
            tier_name=tier_name,
            season=season.number if season else None,
            created_at=now,
            expires_at=now + int(POLL_DURATION.total_seconds()),
            created_by=interaction.user.id,
        )
        embed = self._permfa_poll_dm_embed(
            guild, preview, PollRecipient(name=league_player.player.name or member.display_name), reminder=reminder
        )
        embed.set_footer(text=f"{guild.name} · Test preview, answers are not recorded")

        try:
            # Same view players receive. The preview ids route clicks to
            # `permfa_poll_preview_click`, which never touches a real poll.
            await member.send(embed=embed, view=build_permfa_poll_view(guild.id, PREVIEW_POLL_ID, PREVIEW_POLL_ID))
        except discord.Forbidden:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"Unable to DM {member.mention}. Their DMs may be closed."),
                ephemeral=True,
            )

        log.debug(f"{interaction.user} sent a PermFA poll test DM to {member}", guild=guild)
        await interaction.followup.send(
            embed=GreenEmbed(description=f"Test DM sent to {member.mention}. The buttons work, but answers are not recorded."),
            ephemeral=True,
        )

    @_permfa.command(name="responses", description="Show PermFA answers for a tier's conversion poll")
    @app_commands.describe(tier='Tier to show (Ex: "Elite")')
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)
    async def _permfa_responses_cmd(self, interaction: discord.Interaction, tier: str):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        poll = await self._find_permfa_poll(guild.id, tier)
        if not poll:
            return await interaction.followup.send(
                embed=YellowEmbed(description=f"There is no PermFA conversion poll for **{tier.capitalize()}**."),
                ephemeral=True,
            )

        # One embed per message. The 6000 character limit is per message, not per embed.
        for embed in self._permfa_poll_results_embeds(poll):
            await interaction.followup.send(embed=embed, ephemeral=True)

    @_permfa.command(name="remind", description="Re-DM PermFAs who have not answered the conversion poll")
    @app_commands.describe(tier='Tier to remind (Ex: "Elite")')
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)
    async def _permfa_remind_cmd(self, interaction: discord.Interaction, tier: str):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        poll = await self._find_permfa_poll(guild.id, tier)
        if not (poll and poll.is_open(_now())):
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"There is no open PermFA conversion poll for **{tier.capitalize()}**."),
                ephemeral=True,
            )

        unanswered = [uid for uid, r in poll.recipients.items() if r.response is None]
        if not unanswered:
            return await interaction.followup.send(
                embed=GreenEmbed(description=f"Every PermFA polled in **{poll.tier_name}** has answered."),
                ephemeral=True,
            )

        to_dm, left_guild, lookup_failed = await self._resolve_members_by_id(guild, unanswered)
        if not to_dm:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Nobody To DM",
                    description=(
                        f"All **{len(unanswered)}** PermFA(s) without an answer are unreachable. "
                        "They have left the server or could not be looked up."
                    ),
                ),
                ephemeral=True,
            )

        desc = (
            f"About to remind **{len(to_dm)}** PermFA(s) in **{poll.tier_name}** who have not answered. "
            f"The poll still closes <t:{poll.expires_at}:F>.\n\n"
            f"Skipped (left the server): **{len(left_guild)}**\n"
            f"Skipped (lookup failed): **{len(lookup_failed)}**"
        )
        if poll.last_remind_at:
            desc += f"\n\n\N{WARNING SIGN} A reminder was already sent <t:{poll.last_remind_at}:R>."

        confirm_embed = BlueEmbed(title="Confirm PermFA Poll Reminder", description=desc)
        confirm_embed.add_field(name="Recipients", value=self._format_truncated_list([m.mention for m in to_dm]), inline=False)

        confirm_view = DMConfirmView(interaction, confirm_embed, loading_title="Queueing PermFA Poll Reminders")
        await confirm_view.prompt()
        await confirm_view.wait()

        if not confirm_view.result:
            return

        async with self._permfa_poll_lock(guild.id, poll.tier_id):
            current = await self._get_permfa_poll(guild.id, poll.tier_id)
            still_open = bool(current and current.poll_id == poll.poll_id and current.is_open(_now()))
            if current and still_open:
                current.last_remind_at = _now()
                await self._save_permfa_poll(guild.id, current)
                poll = current

        if not still_open:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(description=f"The **{poll.tier_name}** poll closed before the reminder was confirmed."),
                view=None,
            )

        log.info(f"{interaction.user} queued PermFA poll reminders for {poll.tier_name} to {len(to_dm)} player(s)", guild=guild)

        for member in to_dm:
            await self._dm_helper.enqueue(
                member,
                embed=self._permfa_poll_dm_embed(guild, poll, poll.recipients[member.id], reminder=True),
                view=build_permfa_poll_view(guild.id, poll.tier_id, poll.poll_id),
                precheck=self._permfa_poll_precheck(guild.id, poll.tier_id, poll.poll_id, unanswered_by=member.id),
                on_result=self._permfa_poll_on_result(guild, poll.tier_id, poll.poll_id, member.id),
            )

        await interaction.edit_original_response(
            embed=GreenEmbed(title="PermFA Poll Reminders Queued", description=f"**{len(to_dm)}** reminder DMs queued."),
            view=None,
        )

    @_permfa.command(name="close", description="Close a tier's PermFA conversion poll early")
    @app_commands.describe(tier='Tier to close (Ex: "Elite")')
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)
    async def _permfa_close_cmd(self, interaction: discord.Interaction, tier: str):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        poll = await self._find_permfa_poll(guild.id, tier)
        closed: PermFAPoll | None = None
        if poll:
            async with self._permfa_poll_lock(guild.id, poll.tier_id):
                current = await self._get_permfa_poll(guild.id, poll.tier_id)
                if current and current.poll_id == poll.poll_id and current.is_open(_now()):
                    current.closed_at = _now()
                    current.closed_by = interaction.user.id
                    await self._save_permfa_poll(guild.id, current)
                    closed = current

        if not closed:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"There is no open PermFA conversion poll for **{tier.capitalize()}**."),
                ephemeral=True,
            )

        # Swap the sleeping deadline timer for an immediate sweep
        self._arm_permfa_poll_timer(guild.id, closed.tier_id, 0, replace=True)
        log.info(f"{interaction.user} closed the PermFA conversion poll for {closed.tier_name}", guild=guild)

        await interaction.followup.send(
            embed=GreenEmbed(
                title="PermFA Poll Closed",
                description=(
                    f"The **{closed.tier_name}** poll is closed and no longer accepts answers. "
                    "Buttons are being removed from the DMs in the background.\n\n"
                    "Use `/admin permfa responses` to see the results."
                ),
            ),
            ephemeral=True,
        )

    # Button handling

    def permfa_poll_preview_click(self, message: discord.Message | None, response: PollResponse) -> PollClickResult:
        """Answer a `dmtest` preview. Shows what a player would see and records nothing."""
        base = message.embeds[0] if message and message.embeds else BlueEmbed(title="Free Agent Conversion")
        embed = discord.Embed.from_dict(base.to_dict())
        value = f"**{response.capitalize()}** (<t:{_now()}:R>)"
        idx = next((i for i, f in enumerate(embed.fields) if f.name == CURRENT_ANSWER_FIELD), None)
        if idx is None:
            embed.add_field(name=CURRENT_ANSWER_FIELD, value=value, inline=False)
        else:
            embed.set_field_at(idx, name=CURRENT_ANSWER_FIELD, value=value, inline=False)
        return PollClickResult(embed=embed, keep_buttons=True)

    async def permfa_poll_click(
        self,
        guild: discord.Guild,
        tier_id: int,
        poll_id: int,
        user_id: int,
        response: PollResponse,
    ) -> PollClickResult:
        """Record an answer from a DM button. Config only, so it works before the API is ready."""
        async with self._permfa_poll_lock(guild.id, tier_id):
            poll = await self._get_permfa_poll(guild.id, tier_id)
            if not poll or poll.poll_id != poll_id:
                return PollClickResult(self._permfa_poll_inactive_embed(guild), keep_buttons=False)

            recipient = poll.recipients.get(user_id)
            if recipient is None:
                return PollClickResult(
                    YellowEmbed(title="Free Agent Conversion", description="This poll was not sent to you."),
                    keep_buttons=False,
                )

            now = _now()
            if not poll.is_open(now):
                return PollClickResult(self._permfa_poll_closed_embed(guild, poll, recipient), keep_buttons=False)

            # Re-pressing the same answer keeps its original time, so it does not
            # cost the player their first-come position.
            if recipient.response != response:
                recipient.response = str(response)
                recipient.responded_at = now
                await self._save_permfa_poll(guild.id, poll)
                log.debug(f"PermFA poll {poll.tier_name}: {user_id} answered {response}", guild=guild)

        return PollClickResult(self._permfa_poll_dm_embed(guild, poll, recipient), keep_buttons=True)

    # DM callbacks

    def _permfa_poll_precheck(
        self,
        guild_id: int,
        tier_id: int,
        poll_id: int,
        unanswered_by: int | None = None,
    ) -> Callable[[], Awaitable[bool]]:
        """Build a send-time check that the poll is still open.

        A batch can sit in the queue for minutes. With `unanswered_by`, a
        reminder is also dropped if that player answered in the meantime.
        """

        async def check() -> bool:
            poll = await self._get_permfa_poll(guild_id, tier_id)
            if not (poll and poll.poll_id == poll_id and poll.is_open(_now())):
                return False
            if unanswered_by is not None:
                recipient = poll.recipients.get(unanswered_by)
                return bool(recipient and recipient.response is None)
            return True

        return check

    def _permfa_poll_on_result(
        self,
        guild: discord.Guild,
        tier_id: int,
        poll_id: int,
        user_id: int,
    ) -> Callable[[DMOutcome, discord.Message | None], Awaitable[None]]:
        """Build the DMHelper callback that records delivery and keeps the message id."""

        async def on_result(outcome: DMOutcome, message: discord.Message | None) -> None:
            await self._record_permfa_poll_delivery(guild, tier_id, poll_id, user_id, outcome, message)

        return on_result

    async def _record_permfa_poll_delivery(
        self,
        guild: discord.Guild,
        tier_id: int,
        poll_id: int,
        user_id: int,
        outcome: DMOutcome,
        message: discord.Message | None,
    ) -> None:
        close_now: discord.Embed | None = None

        async with self._permfa_poll_lock(guild.id, tier_id):
            poll = await self._get_permfa_poll(guild.id, tier_id)
            recipient = poll.recipients.get(user_id) if poll and poll.poll_id == poll_id else None
            if poll and recipient:
                match outcome:
                    case DMOutcome.SENT:
                        recipient.delivery = PollDelivery.SENT
                    case DMOutcome.FAILED:
                        # A failed reminder must not hide that the original DM arrived
                        if recipient.delivery != PollDelivery.SENT:
                            recipient.delivery = PollDelivery.FAILED
                    case DMOutcome.SKIPPED:
                        if recipient.delivery == PollDelivery.QUEUED:
                            recipient.delivery = PollDelivery.SKIPPED

                if message and poll.is_open(_now()):
                    recipient.messages.append([message.channel.id, message.id])
                elif message:
                    # Sent just as the poll closed. The sweep may already have
                    # copied its refs, so close this DM here instead of storing it.
                    close_now = self._permfa_poll_closed_embed(guild, poll, recipient)
                await self._save_permfa_poll(guild.id, poll)
            elif message:
                # The poll this DM belongs to was replaced before it went out
                close_now = self._permfa_poll_inactive_embed(guild)

        if message and close_now:
            with contextlib.suppress(discord.HTTPException):
                await message.edit(embed=close_now, view=None)

    # Close timers and sweep

    def _arm_permfa_poll_timer(self, guild_id: int, tier_id: int, delay: float, *, replace: bool = False) -> None:
        """Schedule the close sweep for a poll.

        A live timer for the same poll is left alone unless `replace` is set,
        so a reconnect re-running `setup()` never interrupts a sweep.
        """
        key = (guild_id, tier_id)
        existing = self._permfa_poll_timers.get(key)
        if existing and not existing.done():
            if not replace:
                return
            existing.cancel()

        task = asyncio.create_task(
            self._permfa_poll_timer(guild_id, tier_id, delay),
            name=f"permfa-poll-close:{guild_id}:{tier_id}",
        )
        self._permfa_poll_timers[key] = task
        task.add_done_callback(partial(self._permfa_poll_timer_done, key))

    async def _permfa_poll_timer(self, guild_id: int, tier_id: int, delay: float) -> None:
        remaining: float | None = delay
        # Loops because the sleep runs on the monotonic clock while the deadline
        # is wall clock time. If they drift and we wake early, sleep the rest.
        while remaining is not None:
            await asyncio.sleep(max(0.0, remaining))
            await self.bot.wait_until_ready()
            remaining = await self._sweep_permfa_poll(guild_id, tier_id)

    def _permfa_poll_timer_done(self, key: tuple[int, int], task: asyncio.Task) -> None:
        if self._permfa_poll_timers.get(key) is task:
            del self._permfa_poll_timers[key]
        if task.cancelled():
            return
        if exc := task.exception():
            # The record stays uncleaned, so the next setup() or close re-arms it
            logger.error(f"PermFA poll close timer failed for guild {key[0]} tier {key[1]}", exc_info=exc)

    async def _sweep_permfa_poll(self, guild_id: int, tier_id: int) -> float | None:
        """Close a poll and strip the buttons from every DM it sent.

        Returns the seconds left if the poll turns out to still be open, or
        None once there is nothing more to do. Safe to re-run: message refs are
        cleared as they are edited, so an interrupted sweep picks up where it
        stopped.
        """
        guild = self.bot.get_guild(guild_id)
        lock = self._permfa_poll_lock(guild_id, tier_id)

        async with lock:
            poll = await self._get_permfa_poll(guild_id, tier_id)
            if not poll or poll.dms_cleaned:
                return None
            now = _now()
            if poll.is_open(now):
                return poll.expires_at - now
            if poll.closed_at is None:
                # Natural expiry. Closed at the deadline, not when we noticed.
                poll.closed_at = poll.expires_at
                await self._save_permfa_poll(guild_id, poll)
            refs = {uid: list(r.messages) for uid, r in poll.recipients.items() if r.messages}

        log.info(f"Closing PermFA poll for {poll.tier_name}. Editing DMs for {len(refs)} player(s).", guild=guild)

        # Discord I/O happens outside the lock, so clicks and the DM queue are
        # never stuck behind a long sweep.
        for uid, messages in refs.items():
            embed = self._permfa_poll_closed_embed(guild, poll, poll.recipients[uid])
            for channel_id, message_id in messages:
                try:
                    await self.bot.get_partial_messageable(channel_id).get_partial_message(message_id).edit(embed=embed, view=None)
                except discord.HTTPException as exc:
                    # Any failure is final for this message. Retrying forever
                    # would leave the tier unable to start a new poll.
                    log.debug(f"Unable to close PermFA poll DM {message_id} for {uid}: {exc}", guild=guild)
                await asyncio.sleep(SWEEP_EDIT_DELAY)

            async with lock:
                current = await self._get_permfa_poll(guild_id, tier_id)
                if not current or current.poll_id != poll.poll_id:
                    return None
                recipient = current.recipients.get(uid)
                if recipient:
                    recipient.messages = [m for m in recipient.messages if m not in messages]
                    await self._save_permfa_poll(guild_id, current)

        async with lock:
            current = await self._get_permfa_poll(guild_id, tier_id)
            if current and current.poll_id == poll.poll_id:
                current.dms_cleaned = True
                await self._save_permfa_poll(guild_id, current)

        return None

    # Embeds

    def _permfa_poll_dm_embed(
        self,
        guild: discord.Guild,
        poll: PermFAPoll,
        recipient: PollRecipient,
        reminder: bool = False,
    ) -> discord.Embed:
        season = f"Season {poll.season}" if poll.season else "the current season"
        title = f"Free Agent Conversion - {poll.tier_name}"
        embed = BlueEmbed(
            title=f"Reminder: {title}" if reminder else title,
            description=(
                f"Hi **{recipient.name}**, the **{poll.tier_name}** tier in **{guild.name}** is running low on Free Agents. "
                f"We're looking for Permanent Free Agents who want to **convert to a regular Free Agent** for {season}.\n\n"
                "As a regular Free Agent you'll be **eligible to be signed to a team** and would be expected to play that team's matches."
            ),
        )
        embed.add_field(
            name="\N{WARNING SIGN} Please read before answering",
            value=(
                "Only select **Yes** if you are willing to be signed to a team and play full time. "
                "If you'd prefer to keep subbing as a PermFA, **No** is completely fine and there's no penalty for choosing it. "
                "Honest answers help us match teams with players who are ready to commit."
            ),
            inline=False,
        )
        embed.add_field(
            name="How to respond",
            value=(
                f"Press **Yes** or **No** below. You can change your answer until <t:{poll.expires_at}:F> "
                f"(<t:{poll.expires_at}:R>). After that the poll closes."
            ),
            inline=False,
        )
        if recipient.response:
            answered = f" (<t:{recipient.responded_at}:R>)" if recipient.responded_at else ""
            embed.add_field(name=CURRENT_ANSWER_FIELD, value=f"**{recipient.response.capitalize()}**{answered}", inline=False)
        self._decorate_permfa_poll_embed(embed, guild)
        return embed

    def _permfa_poll_closed_embed(self, guild: discord.Guild | None, poll: PermFAPoll, recipient: PollRecipient) -> discord.Embed:
        answer = {PollResponse.YES: "**Yes**", PollResponse.NO: "**No**"}.get(recipient.response or "", "*No response*")
        embed = OrangeEmbed(
            title=f"Free Agent Conversion - {poll.tier_name} (Closed)",
            description=f"This poll closed <t:{poll.closed_time()}:F>.\n\nYour final answer: {answer}",
        )
        self._decorate_permfa_poll_embed(embed, guild)
        return embed

    def _permfa_poll_inactive_embed(self, guild: discord.Guild | None) -> discord.Embed:
        embed = YellowEmbed(
            title="Free Agent Conversion",
            description="This poll is no longer active. A newer poll may have replaced it.",
        )
        self._decorate_permfa_poll_embed(embed, guild)
        return embed

    @staticmethod
    def _decorate_permfa_poll_embed(embed: discord.Embed, guild: discord.Guild | None) -> None:
        if not guild:
            return
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.set_footer(text=guild.name)

    def _permfa_poll_results_embeds(self, poll: PermFAPoll) -> list[discord.Embed]:
        """Render a poll's answers. Yes is ordered by answer time: first come, first served."""
        now = _now()
        items = list(poll.recipients.items())
        by_time = lambda item: item[1].responded_at or 0  # noqa: E731

        yes = sorted([i for i in items if i[1].response == PollResponse.YES], key=by_time)
        no = sorted([i for i in items if i[1].response == PollResponse.NO], key=by_time)
        waiting = [i for i in items if i[1].response is None and i[1].delivery == PollDelivery.SENT]
        undelivered = [i for i in items if i[1].response is None and i[1].delivery != PollDelivery.SENT]

        def line(uid: int, r: PollRecipient, detail: str | None = None) -> str:
            text = f"<@{uid}> - {r.name}"
            if r.mmr is not None:
                text += f" · {r.mmr} MMR"
            if detail:
                text += f" · {detail}"
            return text

        sections: list[tuple[str, list[str]]] = [
            (
                f"\N{WHITE HEAVY CHECK MARK} Yes - first come, first served ({len(yes)})",
                [f"{n}. {line(uid, r, f'<t:{r.responded_at}:R>' if r.responded_at else None)}" for n, (uid, r) in enumerate(yes, 1)],
            ),
            (
                f"\N{CROSS MARK} No ({len(no)})",
                [line(uid, r, f"<t:{r.responded_at}:R>" if r.responded_at else None) for uid, r in no],
            ),
            (f"\N{HOURGLASS WITH FLOWING SAND} No Response ({len(waiting)})", [line(uid, r) for uid, r in waiting]),
            (
                f"\N{WARNING SIGN} Not Delivered ({len(undelivered)})",
                [line(uid, r, "DM failed" if r.delivery == PollDelivery.FAILED else "not sent") for uid, r in undelivered],
            ),
        ]

        if poll.is_open(now):
            status = f"**Open** - closes <t:{poll.expires_at}:F> (<t:{poll.expires_at}:R>)"
        else:
            by = f" by <@{poll.closed_by}>" if poll.closed_by else " (expired)"
            status = f"**Closed** <t:{poll.closed_time()}:F>{by}"

        desc = f"{status}\nStarted by <@{poll.created_by}> on <t:{poll.created_at}:F>"
        if poll.season:
            desc += f"\nSeason {poll.season}"
        if poll.last_remind_at:
            desc += f"\nReminder sent <t:{poll.last_remind_at}:R>"

        title = f"PermFA Conversion Poll - {poll.tier_name}"
        embeds: list[discord.Embed] = [BlueEmbed(title=title, description=desc)]
        used = len(title) + len(desc)

        for name, lines in sections:
            for idx, value in enumerate(self._pack_lines(lines or ["None"])):
                fname = name if idx == 0 else f"{name} (cont.)"
                size = len(fname) + len(value)
                if len(embeds[-1].fields) >= EmbedLimits.Fields or used + size > RESULTS_EMBED_BUDGET:
                    embeds.append(BlueEmbed(title=f"{title} (cont.)"))
                    used = len(title) + 7
                embeds[-1].add_field(name=fname, value=value, inline=False)
                used += size

        return embeds

    @staticmethod
    def _pack_lines(lines: list[str], limit: int = EmbedLimits.Field.Value) -> list[str]:
        """Join lines into chunks that each fit in one embed field, never splitting a line."""
        chunks: list[str] = []
        current = ""
        for line in lines:
            line = line[:limit]
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) > limit:
                chunks.append(current)
                current = line
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks

    # Config

    def _permfa_poll_lock(self, guild_id: int, tier_id: int) -> asyncio.Lock:
        return self._permfa_poll_locks.setdefault((guild_id, tier_id), asyncio.Lock())

    @staticmethod
    def _permfa_poll_blocked_reason(poll: PermFAPoll | None) -> str | None:
        """Why a new poll cannot start for this tier, or None if it can."""
        if not poll:
            return None
        if poll.is_open(_now()):
            return (
                f"A PermFA conversion poll for **{poll.tier_name}** is already open until <t:{poll.expires_at}:F>. "
                "Use `/admin permfa close` to end it first."
            )
        if not poll.dms_cleaned:
            return f"The previous **{poll.tier_name}** poll is still closing. Try again in a few minutes."
        return None

    async def _get_permfa_poll(self, guild_id: int, tier_id: int) -> PermFAPoll | None:
        data = await self.config.custom(POLL_CONFIG_GROUP, str(guild_id), str(tier_id)).all()
        return PermFAPoll.from_dict(data)

    async def _get_permfa_polls(self, guild_id: int) -> list[PermFAPoll]:
        data = await self.config.custom(POLL_CONFIG_GROUP, str(guild_id)).all()
        polls = [PermFAPoll.from_dict(raw) for raw in data.values()]
        return [p for p in polls if p]

    async def _find_permfa_poll(self, guild_id: int, tier_name: str) -> PermFAPoll | None:
        """Look a poll up by tier name from Config alone, without the API."""
        for poll in await self._get_permfa_polls(guild_id):
            if poll.tier_name.lower() == tier_name.lower():
                return poll
        return None

    async def _save_permfa_poll(self, guild_id: int, poll: PermFAPoll) -> None:
        # Always the whole record, so a new poll fully replaces the old one
        await self.config.custom(POLL_CONFIG_GROUP, str(guild_id), str(poll.tier_id)).set(poll.to_dict())
