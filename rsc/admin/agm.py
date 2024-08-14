import logging

import discord
from redbot.core import app_commands

from rsc.admin import AdminMixIn
from rsc.admin.modals import AgmMessageModal
from rsc.embeds import BlueEmbed, ErrorEmbed
from rsc.franchises import FranchiseMixIn
from rsc.logs import GuildLogAdapter
from rsc.utils import utils

logger = logging.getLogger("red.rsc.admin.agm")
log = GuildLogAdapter(logger)


class AdminAGMMixIn(AdminMixIn):
    def __init__(self):
        log.debug("Initializing AdminMixIn:AGM")

        super().__init__()

    _agm = app_commands.Group(
        name="agm",
        description="Manage franchise AGMs",
        parent=AdminMixIn._admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @_agm.command(name="message", description="Configure the AGM promotion message")  # type: ignore
    async def _agm_set_message_cmd(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        agm_msg_modal = AgmMessageModal()
        await interaction.response.send_modal(agm_msg_modal)
        await agm_msg_modal.wait()

        await self._set_agm_message(
            interaction.guild, value=agm_msg_modal.agm_msg.value
        )

    @_agm.command(  # type: ignore
        name="add", description="Add an Assistant GM to a franchise"
    )
    @app_commands.describe(franchise="Franchise name", agm="Player to promote to AGM")
    @app_commands.autocomplete(franchise=FranchiseMixIn.franchise_autocomplete)  # type: ignore
    async def _franchise_promote_agm_cmd(
        self,
        interaction: discord.Interaction,
        franchise: str,
        agm: discord.Member,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        # Get AGM promotion message
        agm_msg = await self._get_agm_message(guild)
        if not agm_msg:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="AGM promotion message is not configured.")
            )

        # Get AGM role
        agm_role = await utils.get_agm_role(guild)

        # Find transaction channel
        tchannel = await self.get_transaction_channel(guild, franchise)
        if not tchannel:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"Unable to find transaction channel for **{franchise}**"
                )
            )

        # Add AGM role to player
        await agm.add_roles(agm_role)

        # Add AGM permissions to transaction channel
        agm_overwrite = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            add_reactions=True,
            use_external_emojis=False,
            read_message_history=True,
            read_messages=True,
            use_application_commands=True,
        )

        await tchannel.set_permissions(
            agm, overwrite=agm_overwrite, reason="Player was promoted to AGM"
        )

        # Send promotion message
        await tchannel.send(
            content=f"{agm.mention}\n\n{agm_msg}",
            allowed_mentions=discord.AllowedMentions(users=True),
        )

        embed = BlueEmbed(
            title="AGM Promoted",
            description=f"{agm.mention} has been promoted to an AGM.",
        )

        embed.add_field(name="Franchise", value=franchise, inline=False)
        embed.add_field(
            name="Transaction Channel", value=tchannel.mention, inline=False
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @_agm.command(  # type: ignore
        name="remove", description="Remove an Assistant GM from a franchise"
    )
    @app_commands.describe(franchise="Franchise name", agm="Player to remove from AGM")
    @app_commands.autocomplete(franchise=FranchiseMixIn.franchise_autocomplete)  # type: ignore
    async def _franchise_remove_agm_cmd(
        self,
        interaction: discord.Interaction,
        franchise: str,
        agm: discord.Member,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        # Get AGM role
        agm_role = await utils.get_agm_role(guild)

        # Find transaction channel
        franchise_fmt = franchise.lower().replace(" ", "-")
        tchannel_name = f"{franchise_fmt}-transactions"
        log.debug(f"Searching for transaction channel: {tchannel_name}")

        tchannel = discord.utils.get(guild.channels, name=tchannel_name)
        if not tchannel:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"Unable to find transaction channel: **{tchannel_name}**"
                )
            )

        # Add AGM role to player
        await agm.remove_roles(agm_role)

        await tchannel.set_permissions(
            agm, overwrite=None, reason="Player was removed from AGM"
        )

        embed = BlueEmbed(
            title="AGM Removed", description=f"{agm.mention} has been removed as AGM."
        )

        embed.add_field(name="Franchise", value=franchise, inline=False)
        embed.add_field(
            name="Transaction Channel", value=tchannel.mention, inline=False
        )

        await interaction.followup.send(embed=embed, ephemeral=True)
