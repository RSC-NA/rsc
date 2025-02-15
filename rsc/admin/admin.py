import logging

import discord
from redbot.core import app_commands

from rsc.abc import RSCMixIn
from rsc.admin.modals import LeagueDatesModal
from rsc.embeds import BlueEmbed, SuccessEmbed
from rsc.logs import GuildLogAdapter
from rsc.types import AdminSettings

logger = logging.getLogger("red.rsc.admin")
log = GuildLogAdapter(logger)

defaults_guild = AdminSettings(
    ActivityCheckMsgId=None,
    AgmMessage=None,
    Dates=None,
    IntentChannel=None,
    IntentMissingRole=None,
    IntentMissingMsg=None,
    PermFAChannel=None,
    PermFAMsgIds=None,
)


class AdminMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing AdminMixIn")

        self.config.init_custom("Admin", 1)
        self.config.register_custom("Admin", **defaults_guild)
        super().__init__()

    # Top Level Group

    _admin: app_commands.Group = app_commands.Group(
        name="admin",
        description="Admin Only Commands",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # Settings

    @_admin.command(name="settings", description="Display RSC Admin settings.")  # type: ignore[type-var]
    async def _admin_settings_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        intent_role = await self._get_intent_missing_role(guild)
        intent_channel = await self._get_intent_channel(guild)
        intent_missing_msg = await self._get_intent_missing_message(guild)
        dates = await self._get_dates(guild)
        agm_msg = await self._get_agm_message(guild)
        pfa_channel = await self._get_permfa_announce_channel(guild)

        # Intents

        intent_role_fmt = intent_role.mention if intent_role else "None"
        intent_channel_fmt = intent_channel.mention if intent_channel else "None"

        intent_embed = BlueEmbed(
            title="Admin Intent Settings",
            description="Displaying configured settings for RSC Admins",
        )
        intent_embed.add_field(name="Intent Missing Channel", value=intent_channel_fmt, inline=False)
        intent_embed.add_field(name="Intent Missing Role", value=intent_role_fmt, inline=False)
        intent_embed.add_field(name="Intent Missing Message", value=intent_missing_msg, inline=False)

        # PermFA

        pfa_channel_fmt = pfa_channel.mention if pfa_channel else "None"

        permfa_embed = BlueEmbed(title="Admin PermFA Settings")
        permfa_embed.add_field(name="PermFA Announcement Channel", value=pfa_channel_fmt, inline=False)

        # AGM & Dates

        agm_msg_embed = BlueEmbed(title="Admin Dates Setting", description=dates)
        dates_embed = BlueEmbed(title="Admin AGM Message", description=agm_msg)

        await interaction.response.send_message(
            embeds=[intent_embed, permfa_embed, agm_msg_embed, dates_embed],
            ephemeral=True,
        )

    @_admin.command(name="dates", description="Configure the dates command output")  # type: ignore[type-var]
    async def _admin_set_dates(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        dates_modal = LeagueDatesModal()
        await interaction.response.send_modal(dates_modal)
        await dates_modal.wait()

        await self._set_dates(interaction.guild, value=dates_modal.date_input.value)

    @_admin.command(  # type: ignore[type-var]
        name="pfachnanel", description="Configure the PermFA announcement channel"
    )
    @app_commands.describe(channel="Discord channel to announce PermFAs")
    async def _admin_set_pfa_channel_cmd(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.guild:
            return

        await self._set_permfa_announce_chnanel(interaction.guild, channel)
        await interaction.response.send_message(
            embed=SuccessEmbed(description=f"Configured PermFA announcement channel to {channel.mention}")
        )

    # Config

    async def _set_agm_message(self, guild: discord.Guild, value: str):
        await self.config.custom("Admin", str(guild.id)).AgmMessage.set(value)

    async def _get_agm_message(self, guild: discord.Guild) -> str:
        return await self.config.custom("Admin", str(guild.id)).AgmMessage()

    async def _set_dates(self, guild: discord.Guild, value: str):
        await self.config.custom("Admin", str(guild.id)).Dates.set(value)

    async def _get_dates(self, guild: discord.Guild) -> str:
        return await self.config.custom("Admin", str(guild.id)).Dates()

    async def _set_intent_channel(self, guild: discord.Guild, channel: discord.TextChannel):
        await self.config.custom("Admin", str(guild.id)).IntentChannel.set(channel.id)

    async def _get_intent_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        channel_id = await self.config.custom("Admin", str(guild.id)).IntentChannel()
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return None
        log.debug(f"Intent Channel: {channel}")
        return channel

    async def _set_intent_missing_role(self, guild: discord.Guild, role: discord.Role):
        await self.config.custom("Admin", str(guild.id)).IntentMissingRole.set(role.id)

    async def _get_intent_missing_role(self, guild: discord.Guild) -> discord.Role | None:
        role_id = await self.config.custom("Admin", str(guild.id)).IntentMissingRole()
        role = guild.get_role(role_id)
        log.debug(f"Intent Missing Role: {role}")
        return role

    async def _set_intent_missing_message(self, guild: discord.Guild, msg: str):
        await self.config.custom("Admin", str(guild.id)).IntentMissingMsg.set(msg)

    async def _get_intent_missing_message(self, guild: discord.Guild) -> str | None:
        return await self.config.custom("Admin", str(guild.id)).IntentMissingMsg()

    async def _set_actvity_check_msg_id(self, guild: discord.Guild, msg_id: int | None):
        await self.config.custom("Admin", str(guild.id)).ActivityCheckMsgId.set(msg_id)

    async def _get_activity_check_msg_id(self, guild: discord.Guild) -> int | None:
        return await self.config.custom("Admin", str(guild.id)).ActivityCheckMsgId()

    async def _set_permfa_announce_chnanel(self, guild: discord.Guild, channel: discord.TextChannel):
        await self.config.custom("Admin", str(guild.id)).PermFAChannel.set(channel.id)

    async def _get_permfa_announce_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        cid = await self.config.custom("Admin", str(guild.id)).PermFAChannel()
        if not cid:
            return None
        c = guild.get_channel(cid)
        if not isinstance(c, discord.TextChannel):
            return None
        return c

    async def _set_permfa_msg_ids(self, guild: discord.Guild, msg_ids: list[int]):
        await self.config.custom("Admin", str(guild.id)).PermFAMsgIds.set(msg_ids)

    async def _get_permfa_msg_ids(self, guild: discord.Guild) -> list[int]:
        ids = await self.config.custom("Admin", str(guild.id)).PermFAMsgIds()
        if not ids:
            return []
        return ids
