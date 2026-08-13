import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord
from redbot.core import app_commands
from rscapi.models.activity_check import ActivityCheck

from rsc.admin import AdminMixIn
from rsc.admin.views import DMConfirmView, InactiveCheckView, build_activity_check_dm_view
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    BlueEmbed,
    ErrorEmbed,
    GreenEmbed,
    SuccessEmbed,
    YellowEmbed,
)
from rsc.enums import ActivityCheckStatus
from rsc.exceptions import RscException
from rsc.logs import GuildLogAdapter
from rsc.utils import utils

if TYPE_CHECKING:
    from collections.abc import MutableMapping

logger = logging.getLogger("red.rsc.admin.inactivity")
log = GuildLogAdapter(logger)


class AdminInactivityMixIn(AdminMixIn):
    def __init__(self):
        log.debug("Initializing AdminMixIn:Inactivity")
        super().__init__()

    # Groups

    _inactive = app_commands.Group(
        name="inactivecheck",
        description="Begin or end an activity check for players.",
        parent=AdminMixIn._admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # Startup

    async def setup_persistent_activity_check(self, guild: discord.Guild) -> None:
        # Check if inactivity check is present
        msg_id = await self._get_activity_check_msg_id(guild)
        log.debug(f"Inactive Message ID: {msg_id}")
        if not msg_id:
            return

        # Get API configuration since view is independent of RscMixIn
        conf = self._api_conf.get(guild.id)
        if not conf:
            log.error(f"{guild.name} has an inactivity check but no API configuration")
            return

        league_id = self._league.get(guild.id)
        if not league_id:
            log.error(f"{guild.name} has an inactivity check but no league ID")
            return

        inactive_channel = discord.utils.get(guild.channels, name="inactivity-check")
        if not inactive_channel:
            log.warning("Inactive check channel does not exist but is turned on. Resetting...")
            await self._set_actvity_check_msg_id(guild, None)
            return

        log.debug(f"[{guild.name}] Making activity check persistent: {msg_id}")
        # Create and attach view to persistent message ID
        inactive_view = InactiveCheckView(guild=guild, league_id=league_id, api_conf=conf)
        self.bot.add_view(inactive_view, message_id=msg_id)

    # Commands

    @_inactive.command(
        name="start",
        description="Create a channel and ping for inactive check. (DE players only)",
    )
    async def _admin_inactive_check_start_cmd(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        guild = interaction.guild
        if not guild:
            return

        de_role = await utils.get_draft_eligible_role(guild)
        gm_role = await utils.get_gm_role(guild)
        agm_role = await utils.get_agm_role(guild)

        if not (de_role and gm_role and agm_role):
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Draft Eligible, General Manager, or Assistant GM role does not exist in guild."),
                ephemeral=True,
            )

        conf = self._api_conf[guild.id]
        league_id = self._league[guild.id]

        if not (conf and league_id):
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="This guild does has not configured the API or set a league.",
                ),
                ephemeral=True,
            )

        inactive_channel = discord.utils.get(category.channels, name="inactivity-check")
        if inactive_channel:
            # Already started
            return await interaction.response.send_message(
                embed=YellowEmbed(
                    title="Activity Check",
                    description=f"Activity check has already been started in {inactive_channel.mention}",
                ),
                ephemeral=True,
            )

        # Lock down channel. Only show to DE/FA
        view_perms = discord.PermissionOverwrite(
            view_channel=True,
            read_messages=True,
            send_messages=False,
            add_reactions=False,
            send_messages_in_threads=False,
            create_private_threads=False,
            create_public_threads=False,
        )

        activity_overwrites: MutableMapping[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
                send_messages=False,
                add_reactions=False,
            ),
            de_role: view_perms,
            gm_role: view_perms,
            agm_role: view_perms,
        }

        # Create channel
        inactive_channel = await category.create_text_channel(
            name="inactivity-check",
            overwrites=activity_overwrites,
            reason="Starting an activity check",
        )

        # Send persistent embed
        ping_fmt = f"{de_role.mention}"
        embed = BlueEmbed(
            title="Activity Check",
            description=(
                "This is an activity check for all draft eligible players. **This MUST be completed to continue playing in RSC.**\n\n"
                "**Declare your activity with the buttons below.**"
            ),
        )

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        inactive_view = InactiveCheckView(guild=guild, league_id=league_id, api_conf=conf)

        msg = await inactive_channel.send(
            content=ping_fmt,
            embed=embed,
            view=inactive_view,
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
        log.debug(f"Saving inactive check message ID: {msg.id}")

        # Store message
        await self._set_actvity_check_msg_id(guild, msg_id=msg.id)

        # Make persistent
        self.bot.add_view(inactive_view, message_id=msg.id)

        await interaction.response.send_message(
            embed=GreenEmbed(
                title="Activity Check Started",
                description=f"An activity check has been started: {msg.jump_url}",
            ),
            ephemeral=True,
        )

    @_inactive.command(name="stop", description="End inactivity check and delete channel.")
    async def _admin_inactive_check_stop_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        msg_id = await self._get_activity_check_msg_id(guild)
        if not msg_id:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="The activity check has not been started."),
                ephemeral=True,
            )

        # Remove channel
        inactive_channel = discord.utils.get(guild.channels, name="inactivity-check")
        if inactive_channel:
            await inactive_channel.delete(reason="Activity check ended")

        # Reset message ID
        await self._set_actvity_check_msg_id(guild, None)

        await interaction.response.send_message(
            embed=GreenEmbed(
                title="Activity Check Ended",
                description="The activity check has ended and the channel was deleted",
            ),
            ephemeral=True,
        )

    @_inactive.command(name="manual", description="Manually change a players activity check status")
    @app_commands.describe(player="RSC discord member", status="Active or Not Active")
    async def _admin_inactive_check_manual_cmd(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        status: ActivityCheckStatus,
        override: bool = False,
    ):
        guild = interaction.guild
        if not guild:
            return

        if not isinstance(interaction.user, discord.Member):
            return

        if override and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=ErrorEmbed(description="Only admins can process an override."))
            return

        returning = bool(status)
        log.debug(f"Manual Activity Status: {returning}")

        await interaction.response.defer()
        try:
            result = await self.activity_check(
                guild,
                player,
                returning_status=returning,
                executor=interaction.user,
                override=override,
            )
            log.debug(f"Active Result: {result}")
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        if result.missing:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Player activity check was completed but the API returned **missing**")
            )

        if not result.completed:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Player activity check was completed but the API returned **not completed**")
            )

        if result.returning_status != returning:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=(
                        f"Player activity check was completed but API returning status does not match submitted status.\n\n"
                        f"Submitted: {returning}\n"
                        f"Received: {result.returning_status}"
                    )
                )
            )

        status_fmt = "**returning**" if result.returning_status else "**not returning**"

        await interaction.followup.send(
            embed=GreenEmbed(
                title="Active Status Updated",
                description=f"{player.mention} has been marked as {status_fmt}",
            )
        )

    @_inactive.command(name="role", description="Set the role to assign to players missing their activity check")
    @app_commands.describe(role="Role to assign to players who have not completed the activity check")
    async def _admin_inactive_check_role_cmd(self, interaction: discord.Interaction, role: discord.Role):
        guild = interaction.guild
        if not guild:
            return

        await self._set_activity_check_missing_role(guild, role.id)
        await interaction.response.send_message(
            embed=SuccessEmbed(description=f"Activity check missing role set to {role.mention}"),
            ephemeral=True,
        )

    async def _fetch_missing_activity_checks(self, guild: discord.Guild, season_id: int) -> list[ActivityCheck]:
        """Fetch the players who still owe an activity check this season.

        `missing=True` alone is not the outstanding set. The API auto-creates an
        ActivityCheck record for every active league player in the current
        season, and that record keeps `missing=True` after the player completes
        it - it only gains `completed=True`. Filtering on `missing` by itself
        therefore matches the whole active roster. `completed=False` is what
        narrows it to who has actually not responded.

        Every caller must go through here so `populate`, `ping`, and `dm` cannot
        drift apart again.
        """
        checks = await self.season_activity_checks(
            guild,
            season_id=season_id,
            completed=False,
            missing=True,
            limit=10000,
        )
        # Belt and braces. Records carry both flags, so a regression in the
        # server side filter cannot silently re-widen the set.
        return [c for c in checks if not c.completed]

    async def _populate_activity_check_role(
        self, guild: discord.Guild, missing_role: discord.Role
    ) -> tuple[list[discord.Member], list[discord.Member], int]:
        """Sync the missing role to match players who haven't completed the activity check.

        Only adds/removes where needed to minimize API calls.
        Returns a tuple of (assigned, failed, total_missing).
        """
        # Get current season
        season = await self.current_season(guild)
        if not (season and season.id):
            return [], [], 0

        # Fetch all missing activity checks for the current season
        missing_checks = await self._fetch_missing_activity_checks(guild, season.id)
        log.debug("Found %d missing activity checks for season %s", len(missing_checks), season.number)

        # Build set of discord IDs that should have the role
        should_have: set[int] = set()
        for check in missing_checks:
            if check.discord_id:
                should_have.add(check.discord_id)

        # Members who currently have the role but shouldn't
        currently_have = {m.id for m in missing_role.members}
        to_remove = currently_have - should_have
        for member_id in to_remove:
            member = guild.get_member(member_id)
            if member:
                try:
                    await member.remove_roles(missing_role, reason="Completed activity check")
                except discord.HTTPException:
                    pass

        # Members who should have the role but don't
        to_add = should_have - currently_have
        assigned: list[discord.Member] = []
        failed: list[discord.Member] = []
        for member_id in to_add:
            member = guild.get_member(member_id)
            if not member:
                continue
            try:
                await member.add_roles(missing_role, reason="Missing activity check")
                assigned.append(member)
            except discord.HTTPException:
                failed.append(member)

        # Total with role = already had + newly assigned
        log.debug(
            f"Activity check role sync: +{len(assigned)} added, -{len(to_remove)} removed, {len(failed)} failed",
            guild=guild,
        )
        return assigned, failed, len(missing_checks)

    @_inactive.command(name="populate", description="Populate the missing activity check role on players who haven't completed it")
    async def _admin_inactive_check_populate_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        # Verify activity check is running
        msg_id = await self._get_activity_check_msg_id(guild)
        if not msg_id:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="The activity check has not been started."),
                ephemeral=True,
            )

        # Get configured role
        missing_role = await self._get_activity_check_missing_role(guild)
        if not missing_role:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="No activity check missing role configured. Use `/admin inactivecheck role` to set one."),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        try:
            assigned, failed, total_missing = await self._populate_activity_check_role(guild, missing_role)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        if total_missing == 0:
            return await interaction.followup.send(
                embed=GreenEmbed(
                    title="Activity Check",
                    description="All players have completed the activity check!",
                ),
                ephemeral=True,
            )

        desc = f"**{len(assigned)}** players assigned {missing_role.mention}, **{total_missing}** total missing."
        if failed:
            desc += f"\n**{len(failed)}** players could not be assigned the role."

        await interaction.followup.send(
            embed=GreenEmbed(title="Activity Check Populated", description=desc),
            ephemeral=True,
        )

    @_inactive.command(name="ping", description="Ping players who have not completed the activity check")
    async def _admin_inactive_check_ping_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        # Verify activity check is running
        msg_id = await self._get_activity_check_msg_id(guild)
        if not msg_id:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="The activity check has not been started."),
                ephemeral=True,
            )

        # Verify channel exists
        inactive_channel = discord.utils.get(guild.channels, name="inactivity-check")
        if not inactive_channel or not isinstance(inactive_channel, discord.TextChannel):
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="The inactivity-check channel does not exist."),
                ephemeral=True,
            )

        # Get configured role
        missing_role = await self._get_activity_check_missing_role(guild)
        if not missing_role:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="No activity check missing role configured. Use `/admin inactivecheck role` to set one."),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        try:
            assigned, failed, total_missing = await self._populate_activity_check_role(guild, missing_role)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        if total_missing == 0:
            return await interaction.followup.send(
                embed=GreenEmbed(
                    title="Activity Check",
                    description="All players have completed the activity check!",
                ),
                ephemeral=True,
            )

        # Ping in the inactive check channel
        await inactive_channel.send(
            content=f"{missing_role.mention} - You have **not** completed your activity check. Please do so as soon as possible.",
            allowed_mentions=discord.AllowedMentions(roles=True),
        )

        desc = (
            f"Pinged {missing_role.mention} in {inactive_channel.mention}.\n\n"
            f"**{len(assigned)}** players tagged with role, **{total_missing}** total missing."
        )
        if failed:
            desc += f"\n**{len(failed)}** players could not be assigned the role."

        await interaction.followup.send(
            embed=GreenEmbed(title="Activity Check Ping", description=desc),
            ephemeral=True,
        )

    async def _build_activity_check_dm_embed(self, guild: discord.Guild, msg_id: int) -> discord.Embed:
        """Build the DM embed for the activity check reminder.

        The buttons are the way to respond. The channel link is only a fallback
        for clients that fail to render the components, so it is demoted to
        subtext rather than presented as the call to action.
        """
        inactive_channel = discord.utils.get(guild.channels, name="inactivity-check")
        jump_url = None
        if inactive_channel:
            jump_url = f"https://discord.com/channels/{guild.id}/{inactive_channel.id}/{msg_id}"

        body = (
            f"You have **not** completed your activity check for **{guild.name}**.\n\n"
            "**Use the buttons below** to tell us whether you still want to play in the upcoming "
            "season. You will be **unable to play** until you respond.\n\n"
            "**I'm active** \N{EM DASH} I want to play this season\n"
            "**Withdraw** \N{EM DASH} I do not want to play this season"
        )

        if jump_url:
            body += f"\n\n-# Buttons not working? [Respond in the server instead]({jump_url})"

        modmail_id = await self._get_modmail_bot(guild)
        body += f"\n-# Need help? Message <@{modmail_id}> to open a ticket."

        embed = YellowEmbed(
            title="Activity Check Reminder",
            description=body,
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.set_footer(text=guild.name)
        return embed

    @_inactive.command(name="testmsg", description="Preview the activity check DM by sending it to yourself")
    async def _admin_inactive_check_testmsg_cmd(
        self,
        interaction: discord.Interaction,
    ):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        msg_id = await self._get_activity_check_msg_id(guild)
        if not msg_id:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="The activity check has not been started."),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        season = await self.current_season(guild)
        if not (season and season.number):
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Unable to determine the current season."),
                ephemeral=True,
            )

        embed = await self._build_activity_check_dm_embed(guild, msg_id)

        try:
            # Preview must match what players receive, buttons included.
            await interaction.user.send(embed=embed, view=build_activity_check_dm_view(guild.id, season.number))
        except discord.Forbidden:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Unable to DM you. Check your DM settings."),
                ephemeral=True,
            )

        await interaction.followup.send(
            embed=GreenEmbed(description="Test DM sent. Check your direct messages."),
            ephemeral=True,
        )

    def _still_missing_activity_check(self, guild: discord.Guild, season_id: int, member: discord.Member):
        """Build a send-time check that the player still has not responded.

        A batch takes minutes to drain, so a player may complete their check
        between queueing and delivery. Cheaper than a redundant DM.
        """

        async def check() -> bool:
            checks = await self.season_activity_checks(
                guild,
                season_id=season_id,
                discord_id=member.id,
                completed=False,
                missing=True,
            )
            return any(not c.completed for c in checks)

        return check

    @_inactive.command(name="dm", description="DM players who have not completed the activity check")
    async def _admin_inactive_check_dm_cmd(
        self,
        interaction: discord.Interaction,
    ):
        guild = interaction.guild
        if not guild:
            return

        # Verify activity check is running
        msg_id = await self._get_activity_check_msg_id(guild)
        if not msg_id:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="The activity check has not been started."),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        # Get current season
        season = await self.current_season(guild)
        if not (season and season.id and season.number):
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Unable to determine the current season."),
                ephemeral=True,
            )

        # Fetch missing activity checks. Same helper `populate` uses, so the
        # number quoted below always reconciles with what `populate` reports.
        try:
            missing_checks = await self._fetch_missing_activity_checks(guild, season.id)
            to_dm, left_guild, lookup_failed = await self._resolve_members_by_id(
                guild, [c.discord_id for c in missing_checks if c.discord_id]
            )
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        if not (to_dm or left_guild or lookup_failed):
            return await interaction.followup.send(
                embed=GreenEmbed(
                    title="Activity Check",
                    description="All players have completed the activity check!",
                ),
                ephemeral=True,
            )

        if not to_dm:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Nobody To DM",
                    description=(
                        f"All **{len(left_guild) + len(lookup_failed)}** player(s) missing an activity check "
                        "are unreachable. They have left the server or could not be looked up."
                    ),
                ),
                ephemeral=True,
            )

        # Confirmation gate. Nothing is queued until Confirm is pressed.
        desc = (
            f"About to DM **{len(to_dm)}** player(s) who have not completed the activity check "
            f"for **Season {season.number}**.\n\n"
            f"Skipped (left the server): **{len(left_guild)}**\n"
            f"Skipped (lookup failed): **{len(lookup_failed)}**"
        )
        last_season, last_run, last_executor = await self._get_activity_check_dm_last_run(guild)
        if last_season == season.number and last_run:
            # <t:...:F> renders in each admin's own timezone
            by = f" by <@{last_executor}>" if last_executor else ""
            desc += f"\n\n\N{WARNING SIGN} Activity check DMs were already sent for this season on <t:{last_run}:F>{by}."

        confirm_embed = BlueEmbed(title="Confirm Activity Check DMs", description=desc)
        # Show who, not just how many. Truncates to the embed field limit.
        confirm_embed.add_field(
            name="Recipients",
            value=self._format_truncated_list([m.mention for m in to_dm]),
            inline=False,
        )

        confirm_view = DMConfirmView(interaction, confirm_embed, loading_title="Queueing Activity Check DMs")
        await confirm_view.prompt()
        await confirm_view.wait()

        if not confirm_view.result:
            return

        # Claim the run before queueing so a second admin confirming concurrently
        # sees the warning rather than double DMing everyone.
        await self._set_activity_check_dm_last_run(guild, season.number, int(datetime.now(UTC).timestamp()), interaction.user.id)
        log.info(f"{interaction.user} queued activity check DMs for {len(to_dm)} player(s) in S{season.number}", guild=guild)

        # Build embed for the DM
        dm_embed = await self._build_activity_check_dm_embed(guild, msg_id)

        # Queue DMs via the shared rate-limited helper
        queued = 0
        for member in to_dm:
            # A fresh view per DM. `send()` stores the view against the message id,
            # so a shared instance would have its cache key rewritten on every send.
            await self._dm_helper.enqueue(
                member,
                embed=dm_embed,
                view=build_activity_check_dm_view(guild.id, season.number),
                precheck=self._still_missing_activity_check(guild, season.id, member),
            )
            queued += 1

        result = f"**{queued}** DMs queued. Use `/admin dmstatus` to track progress, `/admin dmcancel` to abort."
        if left_guild:
            result += f"\n\nSkipped **{len(left_guild)}** player(s) who left the server."
        if lookup_failed:
            result += f"\nSkipped **{len(lookup_failed)}** player(s) that could not be looked up."

        await interaction.edit_original_response(
            embed=GreenEmbed(title="Activity Check DMs Queued", description=result),
            view=None,
        )
