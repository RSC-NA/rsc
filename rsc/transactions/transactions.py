import discord
import logging

from redbot.core import Config, app_commands, commands, checks

from rsc.abc import RSCMeta
from rsc.embeds import ErrorEmbed

from typing import Optional

log = logging.getLogger("red.rsc.transactions")

defaults = {
    "TransChannel": None,
    "TransLogChannel": None,
    "TransNotifications": False,
    "TransRole": None,
    "CutMessage": None,
    "ContractExpirationMessage": None,
}


class TransactionMixIn(metaclass=RSCMeta):
    def __init__(self):
        # Prepare configuration group
        self.config.init_custom("Transactions", 1)
        self.config.register_custom("Transactions", **defaults)
        super().__init__()

    # Settings

    _transactions = app_commands.Group(
        name="transactions",
        description="Transactions Configuration",
        guild_only=True
    )

    @_transactions.command(
        name="settings", description="Display settings for transactions", guild_only=True
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _show_transactions_settings(self, interaction: discord.Interaction):
        """Show transactions settings"""
        log_channel = await self._trans_log_channel(interaction.guild)
        trans_channel = await self._trans_channel(interaction.guild)
        trans_role = await self._trans_role(interaction.guild)
        cut_msg = await self._get_cut_message(interaction.guild) or "None"
        notifications = await self._notifications_enabled(interaction.guild)
        settings_embed = discord.Embed(
            title="Transactions Settings",
            description="Current configuration for Transactions Cog.",
            color=discord.Color.blue(),
        )

        # Check channel values before mention to avoid exception
        settings_embed.add_field(
            name="Notifications Enabled", value=notifications, inline=False
        )

        if trans_channel:
            settings_embed.add_field(
                name="Transaction Channel", value=trans_channel.mention, inline=False
            )
        else:
            settings_embed.add_field(
                name="Transaction Channel", value="None", inline=False
            )

        if log_channel:
            settings_embed.add_field(
                name="Log Channel", value=log_channel.mention, inline=False
            )
        else:
            settings_embed.add_field(name="Log Channel", value="None", inline=False)

        if trans_role:
            settings_embed.add_field(
                name="Committee Role", value=trans_role.mention, inline=False
            )
        else:
            settings_embed.add_field(name="Committee Role", value="None", inline=False)

        # Discord embed field max length is 1024. Send a seperate embed for cut message if greater.
        if len(cut_msg) <= 1024:
            settings_embed.add_field(name="Cut Message", value=cut_msg, inline=False)
            await interaction.response.send_message(
                embed=settings_embed, ephemeral=True
            )
        else:
            await interaction.response.send_message(
                embed=settings_embed, ephemeral=True
            )
            cut_embed = discord.Embed(
                title="Cut Message", description=cut_msg, color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=cut_embed, ephemeral=True)

    @_transactions.command(
        name="notifications", description="Toggle channel notifications on or off"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _toggle_notifications(self, interaction: discord.Interaction):
        """Toggle channel notifications on or off"""
        status = await self._notifications_enabled(interaction.guild)
        log.debug(f"Current Notifications: {status}")
        status ^= True  # Flip boolean with xor
        log.debug(f"Transaction Notifications: {status}")
        await self._set_notifications(interaction.guild, status)
        result = "**enabled**" if status else "**disabled**"
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Successs",
                description=f"Transaction committee and GM notifications are now {result}.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_transactions.command(name="channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _set_transactions_channel(
        self, interaction: discord.Interaction, trans_channel: discord.TextChannel
    ):
        """Set transaction channel"""
        await self._save_trans_channel(interaction.guild, trans_channel.id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"Transaction channel configured to {trans_channel.mention}",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_transactions.command(
        name="log", description="Set the transactions committee log channel"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _set_transactions_logchannel(
        self, interaction: discord.Interaction, log_channel: discord.TextChannel
    ):
        """Set transactions log channel"""
        await self._save_trans_log_channel(interaction.guild, log_channel.id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"Transaction log channel configured to {log_channel.mention}",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_transactions.command(
        name="role", description="Set the transaction committee role"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _set_transactions_role(
        self, interaction: discord.Interaction, trans_role: discord.Role
    ):
        """Set transactions log channel"""
        await self._save_trans_role(interaction.guild, trans_role.id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"Transaction committee role configured to {trans_role.mention}",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_transactions.command(name="cutmsg", description="Set the cut message")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _set_cut_msg(self, interaction: discord.Interaction, *, msg: str):
        """Set cut message (4096 characters max)"""
        if len(msg) > 4096:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description=f"Cut message must be a maximum of 4096 characters. (Length: {len(msg)})"
                )
            )
            return

        await self._save_cut_message(interaction.guild, msg)
        cut_embed = discord.Embed(
            title="Cut Message", description=f"{msg}", color=discord.Color.green()
        )
        cut_embed.set_footer(text="Successfully configured new cut message.")
        await interaction.response.send_message(embed=cut_embed, ephemeral=True)

    # Commands

    # Config

    async def _trans_role(self, guild: discord.Guild) -> Optional[discord.Role]:
        trans_role_id = await self.config.custom("Transactions", guild).TransRole()
        return guild.get_role(trans_role_id)

    async def _save_trans_role(
        self, guild: discord.Guild, trans_role_id: Optional[int]
    ):
        await self.config.custom("Transactions", guild).TransRole.set(trans_role_id)

    async def _trans_channel(
        self, guild: discord.Guild
    ) -> Optional[discord.TextChannel]:
        trans_channel_id = await self.config.custom(
            "Transactions", guild
        ).TransChannel()
        return guild.get_channel(trans_channel_id)

    async def _save_trans_channel(
        self, guild: discord.Guild, trans_channel: Optional[int]
    ):
        await self.config.custom("Transactions", guild).TransChannel.set(trans_channel)

    async def _trans_log_channel(
        self, guild: discord.Guild
    ) -> Optional[discord.TextChannel]:
        log_channel_id = await self.config.custom(
            "Transactions", guild
        ).TransLogChannel()
        return guild.get_channel(log_channel_id)

    async def _save_trans_log_channel(
        self, guild: discord.Guild, trans_log_channel: Optional[int]
    ):
        await self.config.custom("Transactions", guild).TransLogChannel.set(
            trans_log_channel
        )

    async def _get_cut_message(self, guild: discord.Guild) -> Optional[str]:
        return await self.config.custom("Transactions", guild).CutMessage()

    async def _save_cut_message(self, guild: discord.Guild, message):
        await self.config.custom("Transactions", guild).CutMessage.set(message)

    async def _notifications_enabled(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Transactions", guild).TransNotifications()

    async def _set_notifications(self, guild: discord.Guild, enabled: bool):
        await self.config.custom("Transactions", guild).TransNotifications.set(enabled)