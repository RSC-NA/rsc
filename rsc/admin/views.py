import contextlib
import logging
import re
from enum import IntEnum
from typing import TYPE_CHECKING, Any, cast

import discord
from rscapi import ApiClient, Configuration, MembersApi
from rscapi.exceptions import ApiException
from rscapi.models.activity_request import ActivityRequest
from rscapi.models.activity_check import ActivityCheck
from rscapi.models.league_player import LeaguePlayer

from rsc.const import DEFAULT_MODMAIL_BOT_ID, DEFAULT_TIMEOUT, RSC_COG_NAME
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    GreenEmbed,
    LoadingEmbed,
    OrangeEmbed,
    RedEmbed,
    YellowEmbed,
)
from rsc.exceptions import RscException
from rsc.types import RebrandTeamDict
from rsc.views import (
    AgreeButton,
    AuthorOnlyView,
    CancelButton,
    ConfirmButton,
    DeclineButton,
)

if TYPE_CHECKING:
    from redbot.core.bot import Red

    from rsc.abc import RSCMixIn

    # Activity check config accessors live on AdminMixIn, not the ABC. Type-only
    # import: a runtime one would be circular via `rsc.admin`.
    from rsc.admin.admin import AdminMixIn

log = logging.getLogger("red.rsc.admin.views")


class CreateState(IntEnum):
    START = 1
    TEAMS = 2
    CONFIRM = 3
    FINISHED = 4
    CANCELLED = 5
    NOTIERS = 6


class InactiveCheckView(discord.ui.View):
    def __init__(
        self,
        guild: discord.Guild,
        league_id: int,
        api_conf: Configuration,
        timeout: float | None = None,
    ):
        super().__init__(timeout=timeout)
        self._guild = guild
        self._league_id = league_id
        self._api_conf = api_conf

    @discord.ui.button(
        label="I'm active",
        style=discord.ButtonStyle.green,
        custom_id="inactive_check_view:green",
    )
    async def active(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.call_api(interaction.user, returning_status=True)
            log.debug(f"Active Result: {result}")
        except RscException as exc:
            log.warning(f"[{self._guild.name}] Activity Check Error: {exc.reason}")
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        await interaction.followup.send(
            embed=GreenEmbed(
                title="Marked Active",
                description="You have declared yourself as **active** for the RSC season.",
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Withdraw",
        style=discord.ButtonStyle.red,
        custom_id="inactive_check_view:red",
    )
    async def withdraw(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.call_api(interaction.user, returning_status=False)
            log.debug(f"Active Result: {result}")
        except RscException as exc:
            log.warning(f"[{self._guild.name}] Activity Check Error: {exc.reason}")
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        await interaction.followup.send(
            embed=RedEmbed(
                title="Marked In-Active",
                description=(
                    "You have declared yourself as **inactive** for the RSC season.\n\n**You will be removed from playing this season.**"
                ),
            ),
            ephemeral=True,
        )

    async def call_api(self, player: discord.Member, returning_status: bool) -> ActivityCheck:
        async with ApiClient(self._api_conf) as client:
            api = MembersApi(client)
            data = ActivityRequest(
                league=self._league_id,
                admin_override=False,
                executor=0,
                returning_status=returning_status,
            )
            try:
                log.debug(f"[{player.id}] Activity Check: {data}")
                return await api.members_activity_check_create(player.id, data)
            except ApiException as exc:
                raise RscException(response=exc)


INTENT_DM_TEMPLATE = r"intent_dm:(?P<guild>\d+):(?P<season>\d+):(?P<returning>yes|no)"


def modmail_reference(modmail_id: int) -> str:
    """Render the ModMail bot as a mention plus a profile link.

    A bare mention can display as a raw ID in a DM when the client has not
    cached the bot user, so the link is included as a guaranteed fallback.
    """
    return f"<@{modmail_id}> (https://discord.com/users/{modmail_id})"


class IntentDMButton(discord.ui.DynamicItem[discord.ui.Button], template=INTENT_DM_TEMPLATE):
    """Declare Intent to Play directly from a DM button.

    Registered once globally with `bot.add_dynamic_items()`. The guild and season
    ride along inside the custom_id, so a click resolves without persisting
    anything per message or per season, and buttons from prior seasons keep
    matching the template instead of dying silently.

    The season in the custom_id does NOT enforce the signup deadline - it only
    identifies which prompt was clicked. `next_signup_season` is the authority
    on whether signups are still open.
    """

    def __init__(self, guild_id: int, season: int, returning: bool):
        self.guild_id = guild_id
        self.season = season
        self.returning = returning
        # Set once the API has accepted the declaration, so the catch-all can tell
        # "we never recorded it" apart from "recorded, but the reply failed".
        self.declared = False
        super().__init__(
            discord.ui.Button(
                label="Returning" if returning else "Not Returning",
                style=discord.ButtonStyle.green if returning else discord.ButtonStyle.red,
                custom_id=f"intent_dm:{guild_id}:{season}:{'yes' if returning else 'no'}",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> "IntentDMButton":
        # Parsing only. This runs inside the same 3 second budget as the callback
        # and any exception raised here is logged then swallowed, which would
        # leave the player staring at a dead button.
        return cls(
            guild_id=int(match["guild"]),
            season=int(match["season"]),
            returning=match["returning"] == "yes",
        )

    async def callback(self, interaction: discord.Interaction):
        # Acknowledge before anything else. Every branch below hits the RSC API,
        # which can easily exceed the 3 second initial response deadline.
        await interaction.response.defer()

        # discord.py swallows anything raised out of a dynamic item callback, and
        # a type 6 deferral leaves the message untouched. Without this catch-all an
        # escaping error looks to the player like a click that silently did nothing.
        try:
            await self._declare(interaction)
        except Exception:
            log.exception(f"[Intent DM] Unhandled error handling click from {interaction.user.id}")
            with contextlib.suppress(discord.HTTPException):
                await self._retry(interaction, self._late_error() if self.declared else self._player_error())

    async def _declare(self, interaction: discord.Interaction):
        bot = cast("Red", interaction.client)
        raw_cog = bot.get_cog(RSC_COG_NAME)
        guild = bot.get_guild(self.guild_id)
        if not (raw_cog and guild):
            log.warning(f"[Intent DM] Unable to resolve guild {self.guild_id} or {RSC_COG_NAME} cog")
            return await self._retry(interaction, self._player_error())

        cog = cast("RSCMixIn", raw_cog)
        # Reads config only, so it is safe before the API readiness check below
        modmail = modmail_reference(await cog._get_modmail_bot(guild))

        # The API wrappers index `_api_conf`/`_league` directly, so an unconfigured
        # guild - or one clicked before `setup()` finished after a restart - would
        # raise KeyError rather than RscException. Same guard as `rsc.decorator.apicall`.
        if not (cog._api_conf.get(guild.id) and cog._league.get(guild.id)):
            log.warning(f"[{guild.name}] [Intent DM] Guild is not configured for API access")
            return await self._retry(interaction, self._player_error(modmail))

        # Signups closed is the authoritative deadline check
        try:
            season = await cog.next_signup_season(guild)
        except RscException as exc:
            if exc.type == "SignupsClosedException":
                return await self._finish(
                    interaction,
                    OrangeEmbed(
                        title="Signups Are Closed",
                        description=(
                            f"Signups for **{guild.name}** have closed, so intent can no longer be declared here.\n\n"
                            f"If you still need to sign up, please message {modmail} to open a ticket."
                        ),
                    ),
                )
            log.warning(f"[{guild.name}] [Intent DM] Error fetching signup season: {exc.reason}")
            return await self._retry(interaction, self._player_error(modmail))

        if not (season and season.number):
            return await self._finish(
                interaction,
                OrangeEmbed(
                    title="Signups Are Closed",
                    description=(
                        f"There is no season currently open for signups in **{guild.name}**.\n\n"
                        f"If you still need to sign up, please message {modmail} to open a ticket."
                    ),
                ),
            )

        # The DM belongs to an older season than the one now open for signups
        if season.number != self.season:
            return await self._finish(
                interaction,
                YellowEmbed(
                    title="This Message Is Out Of Date",
                    description=(
                        f"This message asked about **Season {self.season}**, but signups are now open for "
                        f"**Season {season.number}**.\n\n"
                        f"Please run `/signup` in **{guild.name}** to declare your intent for the current season."
                    ),
                ),
            )

        try:
            result = await cog.declare_intent(guild=guild, member=interaction.user.id, returning=self.returning)
            self.declared = True
            log.debug(f"[{guild.name}] [Intent DM] Result for {interaction.user.id}: {result}")
        except RscException as exc:
            if exc.status == 409:
                return await self._finish(
                    interaction,
                    YellowEmbed(
                        title="Intent to Play",
                        description=exc.reason or "You have already declared your intent for this season.",
                    ),
                )
            log.warning(f"[{guild.name}] [Intent DM] Error declaring intent: {exc.reason}")
            return await self._retry(interaction, self._player_error(modmail))

        if self.returning:
            embed = GreenEmbed(
                title="Intent to Play Declared",
                description=f"You are marked as **RETURNING** for Season {season.number} of **{guild.name}**.",
            )
        else:
            embed = RedEmbed(
                title="Intent to Play Declared",
                description=f"You are marked as **NOT RETURNING** for Season {season.number} of **{guild.name}**.",
            )
        await self._finish(interaction, embed)

    @staticmethod
    def _late_error() -> discord.Embed:
        """The declaration landed but the reply did not.

        Must not tell the player to try again - the intent is already recorded and
        a retry would only earn them a 409.
        """
        return YellowEmbed(
            title="Intent Recorded",
            description=(
                "Your intent was recorded, but we could not update this message.\n\n"
                "No further action is needed. Use `/intent status` in the server to confirm."
            ),
        )

    @staticmethod
    def _player_error(modmail: str | None = None) -> discord.Embed:
        """Player facing error. The technical detail goes to the log, not the DM.

        `modmail` is optional so the catch-all in `callback` can still produce a
        useful message when the failure happened before the guild's configured
        ModMail bot could be resolved.
        """
        return RedEmbed(
            title="Something Went Wrong",
            description=(
                "We could not record your intent right now. Please try the buttons again in a few minutes.\n\n"
                f"If it keeps failing, message {modmail or modmail_reference(DEFAULT_MODMAIL_BOT_ID)} to open a ticket."
            ),
        )

    async def _finish(self, interaction: discord.Interaction, embed: discord.Embed):
        """Terminal outcome. Replace the DM body and strip the buttons.

        Never call `self.stop()` or mutate the buttons here - a dynamic item is
        reconstructed per click, but the underlying view belongs to the message.
        """
        await interaction.edit_original_response(embed=embed, view=None)

    async def _retry(self, interaction: discord.Interaction, embed: discord.Embed):
        """Transient failure. Leave the buttons in place so the player can retry."""
        await interaction.followup.send(embed=embed, ephemeral=True)


def build_intent_dm_view(guild_id: int, season: int) -> discord.ui.View:
    """Build the button pair sent in an Intent to Play DM.

    Deliberately not registered with `add_view()`. Dispatch happens through the
    `IntentDMButton` template registered once via `add_dynamic_items()`.
    """
    view = discord.ui.View(timeout=None)
    view.add_item(IntentDMButton(guild_id=guild_id, season=season, returning=True))
    view.add_item(IntentDMButton(guild_id=guild_id, season=season, returning=False))
    return view


ACTIVITY_DM_TEMPLATE = r"activity_dm:(?P<guild>\d+):(?P<season>\d+):(?P<active>yes|no)"


class ActivityCheckDMButton(discord.ui.DynamicItem[discord.ui.Button], template=ACTIVITY_DM_TEMPLATE):
    """Complete the activity check directly from a DM button.

    The same question `InactiveCheckView` asks in the channel, but that view
    cannot be reused here: it is registered per message id via `add_view()`,
    and DM message ids are never recorded. It also guards on
    `isinstance(interaction.user, discord.Member)`, which is False in a DM, so
    both of its handlers would silently no-op.

    Registered once globally with `bot.add_dynamic_items()`. The guild and
    season ride inside the custom_id, so a click resolves without persisting
    anything per message, and buttons survive a restart.

    The season in the custom_id does NOT decide whether the check is still
    running - it only identifies which prompt was clicked. `ActivityCheckMsgId`
    is the authority on that.
    """

    def __init__(self, guild_id: int, season: int, active: bool):
        self.guild_id = guild_id
        self.season = season
        self.active = active
        # Set once the API has accepted the submission, so the catch-all can tell
        # "we never recorded it" apart from "recorded, but the reply failed".
        self.submitted = False
        super().__init__(
            discord.ui.Button(
                label="I'm active" if active else "Withdraw",
                style=discord.ButtonStyle.green if active else discord.ButtonStyle.red,
                custom_id=f"activity_dm:{guild_id}:{season}:{'yes' if active else 'no'}",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> "ActivityCheckDMButton":
        # Parsing only. This runs inside the same 3 second budget as the callback
        # and any exception raised here is logged then swallowed, which would
        # leave the player staring at a dead button.
        return cls(
            guild_id=int(match["guild"]),
            season=int(match["season"]),
            active=match["active"] == "yes",
        )

    async def callback(self, interaction: discord.Interaction):
        # Acknowledge before anything else. Every branch below hits the RSC API,
        # which can easily exceed the 3 second initial response deadline.
        await interaction.response.defer()

        # discord.py swallows anything raised out of a dynamic item callback, and
        # a type 6 deferral leaves the message untouched. Without this catch-all an
        # escaping error looks to the player like a click that silently did nothing.
        try:
            await self._submit(interaction)
        except Exception:
            log.exception(f"[Activity DM] Unhandled error handling click from {interaction.user.id}")
            with contextlib.suppress(discord.HTTPException):
                await self._retry(interaction, self._late_error() if self.submitted else self._player_error())

    async def _submit(self, interaction: discord.Interaction):
        bot = cast("Red", interaction.client)
        raw_cog = bot.get_cog(RSC_COG_NAME)
        guild = bot.get_guild(self.guild_id)
        if not (raw_cog and guild):
            log.warning(f"[Activity DM] Unable to resolve guild {self.guild_id} or {RSC_COG_NAME} cog")
            return await self._retry(interaction, self._player_error())

        cog = cast("AdminMixIn", raw_cog)
        # Reads config only, so it is safe before the API readiness check below
        modmail = modmail_reference(await cog._get_modmail_bot(guild))

        # The API wrappers index `_api_conf`/`_league` directly, so an unconfigured
        # guild - or one clicked before `setup()` finished after a restart - would
        # raise KeyError rather than RscException. Same guard as `rsc.decorator.apicall`.
        if not (cog._api_conf.get(guild.id) and cog._league.get(guild.id)):
            log.warning(f"[{guild.name}] [Activity DM] Guild is not configured for API access")
            return await self._retry(interaction, self._player_error(modmail))

        # An ended check clears the stored message id. That, not the season in the
        # custom_id, is what says whether submissions are still accepted.
        if not await cog._get_activity_check_msg_id(guild):
            return await self._finish(
                interaction,
                OrangeEmbed(
                    title="Activity Check Has Ended",
                    description=(
                        f"The activity check for **{guild.name}** has ended, so it can no longer be completed here.\n\n"
                        f"If you still need to respond, please message {modmail} to open a ticket."
                    ),
                ),
            )

        try:
            season = await cog.current_season(guild)
        except RscException as exc:
            log.warning(f"[{guild.name}] [Activity DM] Error fetching current season: {exc.reason}")
            return await self._retry(interaction, self._player_error(modmail))

        if not (season and season.id and season.number):
            return await self._retry(interaction, self._player_error(modmail))

        # The DM belongs to an older season than the one now running
        if season.number != self.season:
            return await self._finish(
                interaction,
                YellowEmbed(
                    title="This Message Is Out Of Date",
                    description=(
                        f"This message asked about **Season {self.season}**, but the activity check is now running for "
                        f"**Season {season.number}**.\n\n"
                        f"Please complete the current activity check in **{guild.name}**."
                    ),
                ),
            )

        try:
            result = await cog.activity_check(guild, interaction.user.id, returning_status=self.active)
            self.submitted = True
            log.debug(f"[{guild.name}] [Activity DM] Result for {interaction.user.id}: {result}")
        except RscException as exc:
            # This endpoint has no 409, so a duplicate submission cannot be told
            # apart from a real failure by status code. Ask the API who is still
            # missing instead of guessing: an empty result means they are already
            # recorded and there is nothing to retry.
            if not await self._still_missing(cog, guild, season.id, interaction.user.id):
                return await self._finish(
                    interaction,
                    YellowEmbed(
                        title="Activity Check",
                        description="You have already completed your activity check for this season.",
                    ),
                )
            log.warning(f"[{guild.name}] [Activity DM] Error submitting activity check: {exc.reason}")
            return await self._retry(interaction, self._player_error(modmail))

        if self.active:
            embed = GreenEmbed(
                title="Marked Active",
                description=f"You are marked as **active** for Season {season.number} of **{guild.name}**.",
            )
        else:
            embed = RedEmbed(
                title="Marked In-Active",
                description=(
                    f"You are marked as **inactive** for Season {season.number} of **{guild.name}**.\n\n"
                    "**You will be removed from playing this season.**"
                ),
            )
        await self._finish(interaction, embed)

    @staticmethod
    async def _still_missing(cog: "AdminMixIn", guild: discord.Guild, season_id: int, player_id: int) -> bool:
        """Whether the player still owes a check. Fails open, so a lookup error
        is reported as a retryable failure rather than a false "already done"."""
        try:
            checks = await cog.season_activity_checks(
                guild,
                season_id=season_id,
                discord_id=player_id,
                completed=False,
                missing=True,
            )
        except RscException:
            return True
        return any(not c.completed for c in checks)

    @staticmethod
    def _late_error() -> discord.Embed:
        """The submission landed but the reply did not.

        Must not tell the player to try again - the check is already recorded.
        """
        return YellowEmbed(
            title="Activity Check Recorded",
            description=("Your activity check was recorded, but we could not update this message.\n\nNo further action is needed."),
        )

    @staticmethod
    def _player_error(modmail: str | None = None) -> discord.Embed:
        """Player facing error. The technical detail goes to the log, not the DM.

        `modmail` is optional so the catch-all in `callback` can still produce a
        useful message when the failure happened before the guild's configured
        ModMail bot could be resolved.
        """
        return RedEmbed(
            title="Something Went Wrong",
            description=(
                "We could not record your activity check right now. Please try the buttons again in a few minutes.\n\n"
                f"If it keeps failing, message {modmail or modmail_reference(DEFAULT_MODMAIL_BOT_ID)} to open a ticket."
            ),
        )

    async def _finish(self, interaction: discord.Interaction, embed: discord.Embed):
        """Terminal outcome. Replace the DM body and strip the buttons.

        Never call `self.stop()` or mutate the buttons here - a dynamic item is
        reconstructed per click, but the underlying view belongs to the message.
        """
        await interaction.edit_original_response(embed=embed, view=None)

    async def _retry(self, interaction: discord.Interaction, embed: discord.Embed):
        """Transient failure. Leave the buttons in place so the player can retry."""
        await interaction.followup.send(embed=embed, ephemeral=True)


def build_activity_check_dm_view(guild_id: int, season: int) -> discord.ui.View:
    """Build the button pair sent in an activity check DM.

    Deliberately not registered with `add_view()`. Dispatch happens through the
    `ActivityCheckDMButton` template registered once via `add_dynamic_items()`.
    """
    view = discord.ui.View(timeout=None)
    view.add_item(ActivityCheckDMButton(guild_id=guild_id, season=season, active=True))
    view.add_item(ActivityCheckDMButton(guild_id=guild_id, season=season, active=False))
    return view


class DMConfirmView(AuthorOnlyView):
    """Confirmation gate shown before mass DMing players.

    Assumes the invoking interaction was already deferred, so the prompt edits
    the original response rather than sending a followup. That keeps the
    confirm/decline edits pointed at the same message.

    `result` stays False unless Confirm is pressed, so a decline or a timeout
    both mean "queue nothing".
    """

    def __init__(
        self,
        interaction: discord.Interaction,
        prompt_embed: discord.Embed,
        loading_title: str = "Queueing DMs",
        timeout: float = DEFAULT_TIMEOUT,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.prompt_embed = prompt_embed
        self.loading_title = loading_title
        self.result = False
        self.add_item(ConfirmButton())
        self.add_item(CancelButton())

    async def prompt(self):
        await self.interaction.edit_original_response(embed=self.prompt_embed, view=self)

    async def confirm(self, interaction: discord.Interaction):
        self.result = True
        await interaction.response.defer(ephemeral=True)
        await self.interaction.edit_original_response(
            embed=LoadingEmbed(title=self.loading_title),
            view=None,
        )
        self.stop()

    async def decline(self, interaction: discord.Interaction):
        self.result = False
        await interaction.response.defer(ephemeral=True)
        await self.interaction.edit_original_response(
            embed=RedEmbed(
                title="Cancelled",
                description="No DMs were sent.",
            ),
            view=None,
        )
        self.stop()


class ConfirmSyncView(AuthorOnlyView):
    def __init__(
        self,
        interaction: discord.Interaction,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.add_item(ConfirmButton())
        self.add_item(DeclineButton())
        self.result = False

    async def prompt(self):
        """Note: The prompt does not all wait()"""
        prompt = OrangeEmbed(
            title="API Sync",
            description=(
                "You are about to sync data from the API directly into the discord server.\n\n**Are you sure you want to do this?**"
            ),
        )
        await self.interaction.response.send_message(embed=prompt, view=self, ephemeral=True)

    async def confirm(self, interaction: discord.Interaction):
        self.result = True
        await interaction.response.defer(ephemeral=True)
        await self.interaction.edit_original_response(
            embed=LoadingEmbed(title="Processing Sync"),
            view=None,
        )
        self.stop()

    async def decline(self, interaction: discord.Interaction):
        self.result = False
        await self.interaction.edit_original_response(
            embed=RedEmbed(
                title="Sync Canelled",
                description="You have cancelled syncing from the API.",
            ),
            view=None,
        )
        self.stop()


class ConfirmRetireView(AuthorOnlyView):
    """Confirmation gate for retiring a batch of departed players.

    The interaction is already deferred by the caller (the audit takes long
    enough to need it), so this follows up rather than responding.
    """

    def __init__(
        self,
        interaction: discord.Interaction,
        count: int,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.add_item(ConfirmButton())
        self.add_item(DeclineButton())
        self.count = count
        self.result = False

    async def prompt(self, embed: discord.Embed | None = None):
        """Note: The prompt does not call wait()"""
        prompt = OrangeEmbed(
            title="Retire Departed Players",
            description=(
                f"You are about to retire **{self.count}** player(s) in the API because they are no "
                "longer in this server. Each will be announced in the transaction channel.\n\n"
                "**Are you sure you want to do this?**"
            ),
        )
        embeds = [embed, prompt] if embed else [prompt]
        await self.interaction.followup.send(embeds=embeds, view=self, ephemeral=True)

    async def confirm(self, interaction: discord.Interaction):
        self.result = True
        await interaction.response.edit_message(
            embeds=[LoadingEmbed(title=f"Retiring {self.count} Player(s)")],
            view=None,
        )
        self.stop()

    async def decline(self, interaction: discord.Interaction):
        self.result = False
        await interaction.response.edit_message(
            embeds=[RedEmbed(title="Retirement Cancelled", description="No players were retired.")],
            view=None,
        )
        self.stop()


class RebrandFranchiseView(AuthorOnlyView):
    def __init__(
        self,
        interaction: discord.Interaction,
        old_name: str,
        name: str,
        prefix: str,
        teams: list[RebrandTeamDict],
        timeout: float = 30.0,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.old_name = old_name
        self.name = name
        self.prefix = prefix
        self.teams = teams
        self.result = False
        self.add_item(ConfirmButton())
        self.add_item(CancelButton())

    async def prompt(self):
        """Confirm franchise deletion"""
        embed = OrangeEmbed(
            title="Rebrand Franchise",
            description=(
                f"Are you sure you want to rebrand **{self.old_name}** to the following?\n\n"
                f"**Name**: {self.name}\n"
                f"**Prefix**: {self.prefix}"
            ),
        )
        embed.add_field(name="Tier", value="\n".join([t["tier"] for t in self.teams]), inline=True)
        embed.add_field(name="Teams", value="\n".join(t["name"] for t in self.teams), inline=True)
        await self.interaction.response.send_message(
            embed=embed,
            view=self,
            ephemeral=True,
        )

    async def confirm(self, interaction: discord.Interaction):
        log.debug("User confirmed franchise deletion")
        await interaction.response.defer(ephemeral=True)
        self.result = True
        self.stop()

    async def decline(self, interaction: discord.Interaction):
        log.debug("Franchise deletion cancelled by user...")
        self.result = False
        await self.interaction.edit_original_response(
            embed=RedEmbed(
                title="Cancelled",
                description="You have cancelled deleting this franchise.",
            ),
            view=None,
        )
        self.stop()


class DeleteFranchiseView(AuthorOnlyView):
    def __init__(
        self,
        interaction: discord.Interaction,
        name: str,
        timeout: float = 30.0,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.name = name
        self.result = False
        self.add_item(ConfirmButton())
        self.add_item(CancelButton())

    async def prompt(self):
        """Confirm franchise deletion"""
        embed = OrangeEmbed(
            title="Delete Franchise",
            description="Are you sure you want to delete the following franchise?",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Name", value=self.name, inline=True)
        await self.interaction.followup.send(
            embed=embed,
            view=self,
            ephemeral=True,
        )

    async def confirm(self, interaction: discord.Interaction):
        log.debug("User confirmed franchise deletion")
        self.result = True
        self.stop()

    async def decline(self, interaction: discord.Interaction):
        log.debug("Franchise deletion cancelled by user...")
        self.result = False
        await self.interaction.edit_original_response(
            embed=RedEmbed(
                title="Cancelled",
                description="You have cancelled deleting this franchise.",
            ),
            view=None,
        )
        self.stop()


class CreateFranchiseView(AuthorOnlyView):
    def __init__(
        self,
        interaction: discord.Interaction,
        name: str,
        gm: discord.Member,
        timeout: float = 30.0,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.gm = gm
        self.name = name
        self.result = False
        self.add_item(ConfirmButton())
        self.add_item(CancelButton())

    async def prompt(self):
        """Confirm franchise name and GM"""
        embed = OrangeEmbed(
            title="Create Franchise",
            description="Are you sure you want to create the following franchise?",
        )
        embed.add_field(name="Name", value=self.name, inline=True)
        embed.add_field(name="GM", value=self.gm.mention, inline=True)
        await self.interaction.response.send_message(
            embed=embed,
            view=self,
            ephemeral=True,
        )

    async def confirm(self, interaction: discord.Interaction):
        log.debug("User confirmed franchise creation")
        self.result = True
        self.stop()

    async def decline(self, interaction: discord.Interaction):
        log.debug("Franchise creation cancelled by user...")
        self.result = False
        await self.interaction.edit_original_response(
            embed=RedEmbed(
                title="Cancelled",
                description="You have cancelled creating a new franchise.",
            ),
            view=None,
        )
        self.stop()


class TransferFranchiseView(AuthorOnlyView):
    def __init__(
        self,
        interaction: discord.Interaction,
        franchise: str,
        gm: discord.Member,
        timeout: float = 30.0,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.gm = gm
        self.franchise = franchise
        self.result = False
        self.add_item(ConfirmButton())
        self.add_item(CancelButton())

    async def prompt(self):
        """Confirm transfer franchise"""
        embed = OrangeEmbed(
            title="Transfer Franchise",
            description="Are you sure you want to transfer the following franchise?",
        )
        embed.add_field(name="Franchise", value=self.franchise, inline=True)
        embed.add_field(name="New GM", value=self.gm.mention, inline=True)
        await self.interaction.response.send_message(
            embed=embed,
            view=self,
            ephemeral=True,
        )

    async def confirm(self, interaction: discord.Interaction):
        log.debug("User confirmed franchise transfer")
        self.result = True
        await interaction.response.defer(ephemeral=True)
        self.stop()

    async def decline(self, interaction: discord.Interaction):
        log.debug("Franchise transfer cancelled by user...")
        self.result = False
        await self.interaction.edit_original_response(
            embed=RedEmbed(
                title="Cancelled",
                description="You have cancelled transferring franchise.",
            ),
            view=None,
        )
        self.stop()


class PermFAConsentView(discord.ui.View):
    def __init__(
        self,
        guild: discord.Guild,
        member: discord.Member,
        league_player: LeaguePlayer,
        timeout: float | None = None,
    ):
        super().__init__(timeout=timeout)

        self.guild = guild
        self.member = member
        self.league_player = league_player
        self.result = False

        self.add_item(AgreeButton())
        self.add_item(DeclineButton())

    async def confirm(self, interaction: discord.Interaction):
        log.debug("Player agreed to PermFA")
        self.result = True
        # await self.interaction.edit_original_response(
        #     embed=LoadingEmbed(title="Processing Sync"),
        #     view=None,
        # )
        # self.stop()

    async def decline(self, interaction: discord.Interaction):
        log.debug("Player declined to PermFA")
        self.result = False
        # await self.interaction.edit_original_response(
        #     embed=RedEmbed(
        #         title="Sync Canelled",
        #         description="You have cancelled syncing from the API.",
        #     ),
        #     view=None,
        # )
        # self.stop()
