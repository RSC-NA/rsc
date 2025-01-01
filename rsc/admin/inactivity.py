import logging
from typing import MutableMapping

import discord
from redbot.core import app_commands

from rsc.admin import AdminMixIn
from rsc.admin.views import InactiveCheckView
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    BlueEmbed,
    ErrorEmbed,
    GreenEmbed,
    YellowEmbed,
)
from rsc.enums import ActivityCheckStatus
from rsc.exceptions import RscException
from rsc.logs import GuildLogAdapter
from rsc.utils import utils

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

    async def setup_persistent_activity_check(self, guild: discord.Guild):
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
            log.warning(
                "Inactive check channel does not exist but is turned on. Resetting..."
            )
            await self._set_actvity_check_msg_id(guild, None)
            return

        log.debug(f"[{guild.name}] Making activity check persistent: {msg_id}")
        # Create and attach view to persistent message ID
        inactive_view = InactiveCheckView(
            guild=guild, league_id=league_id, api_conf=conf
        )
        self.bot.add_view(inactive_view, message_id=msg_id)

    # Commands

    @_inactive.command(  #  type: ignore
        name="start",
        description="Create a channel and ping for inactive check. (FA/DE players only)",
    )
    async def _admin_inactive_check_start_cmd(
        self, interaction: discord.Interaction, category: discord.CategoryChannel
    ):
        guild = interaction.guild
        if not guild:
            return

        de_role = await utils.get_draft_eligible_role(guild)
        gm_role = await utils.get_gm_role(guild)
        agm_role = await utils.get_agm_role(guild)

        if not (de_role and gm_role and agm_role):
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Draft Eligible, General Manager, or Assistant GM role does not exist in guild."
                ),
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

        activity_overwrites: MutableMapping[
            discord.Member | discord.Role, discord.PermissionOverwrite
        ] = {
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

        inactive_view = InactiveCheckView(
            guild=guild, league_id=league_id, api_conf=conf
        )

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

    @_inactive.command(  # type: ignore
        name="stop", description="End inactivity check and delete channel."
    )
    async def _admin_inactive_check_stop_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        msg_id = await self._get_activity_check_msg_id(guild)
        if not msg_id:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="The activity check has not been started."
                ),
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

    @_inactive.command(  # type: ignore
        name="manual", description="Manually change a players activity check status"
    )
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
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Only admins can process an override.")
            )
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
            return await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )

        if result.missing:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="Player activity check was completed but the API returned **missing**"
                )
            )

        if not result.completed:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="Player activity check was completed but the API returned **not completed**"
                )
            )

        if result.returning_status != returning:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"Player activity check was completed but API returning status does not match submitted status.\n\nSubmitted: {returning}\nReceived: {result.returning_status}"
                )
            )

        if result.returning_status:
            status_fmt = "**returning**"
        else:
            status_fmt = "**not returning**"

        await interaction.followup.send(
            embed=GreenEmbed(
                title="Active Status Updated",
                description=f"{player.mention} has been marked as {status_fmt}",
            )
        )
