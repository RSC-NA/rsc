import logging
from typing import TYPE_CHECKING

import discord
from redbot.core import app_commands

from rsc.admin import AdminMixIn
from rsc.admin.views import InactiveCheckView
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
        conf = self._api_conf[guild.id]
        if not conf:
            log.error(f"{guild.name} has an inactivity check but no API configuration")

        league_id = self._league[guild.id]
        if not league_id:
            log.error(f"{guild.name} has an inactivity check but no league ID")

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

        activity_overwrites: MutableMapping[discord.Member | discord.Role, discord.PermissionOverwrite] = {
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
        missing_checks = await self.season_activity_checks(
            guild,
            season_id=season.id,
            missing=True,
            limit=10000,
        )

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

    @_inactive.command(name="dm", description="DM players who have not completed the activity check")
    @app_commands.describe(message="Custom message to include in the DM (optional)")
    async def _admin_inactive_check_dm_cmd(
        self,
        interaction: discord.Interaction,
        message: str | None = None,
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
        if not (season and season.id):
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Unable to determine the current season."),
                ephemeral=True,
            )

        # Build jump URL to the persistent activity check message
        inactive_channel = discord.utils.get(guild.channels, name="inactivity-check")
        jump_url = None
        if inactive_channel:
            jump_url = f"https://discord.com/channels/{guild.id}/{inactive_channel.id}/{msg_id}"

        # Fetch missing activity checks
        try:
            missing_checks = await self.season_activity_checks(
                guild,
                season_id=season.id,
                missing=True,
                limit=10000,
            )
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        if not missing_checks:
            return await interaction.followup.send(
                embed=GreenEmbed(
                    title="Activity Check",
                    description="All players have completed the activity check!",
                ),
                ephemeral=True,
            )

        # Build embed for the DM
        default_msg = "You have **not** completed your activity check. Please do so as soon as possible."
        if jump_url:
            default_msg += f"\n\n**[Click here to complete your activity check]({jump_url})**"

        dm_embed = YellowEmbed(
            title="Activity Check Reminder",
            description=message or default_msg,
        )
        if guild.icon:
            dm_embed.set_thumbnail(url=guild.icon.url)
        dm_embed.set_footer(text=guild.name)

        # Queue DMs via the shared rate-limited helper
        queued = 0
        for check in missing_checks:
            if not check.discord_id:
                continue
            member = guild.get_member(check.discord_id)
            if not member:
                continue
            await self._dm_helper.enqueue(member, embed=dm_embed)
            queued += 1

        desc = f"**{queued}** DMs queued. Use `/admin dmstatus` to track progress."

        await interaction.followup.send(
            embed=GreenEmbed(title="Activity Check DMs Queued", description=desc),
            ephemeral=True,
        )
