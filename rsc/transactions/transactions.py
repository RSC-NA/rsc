import discord
import logging

from redbot.core import Config, app_commands, commands, checks

from rsc.abc import RSCMeta
from rsc.embeds import ErrorEmbed
from rsc.teams import TeamMixIn
from rsc.transactions.views import TradeAnnouncementModal, TradeAnnouncementView

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
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @_transactions.command(
        name="settings", description="Display settings for transactions"
    )
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

    @app_commands.command(name="cut", description="Release a player from their team")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def _cut(self, interaction: discord.Interaction, player: discord.Member):
        pass

    @app_commands.command(
        name="sign", description="Sign a player to the specified team"
    )
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def _sign(
        self, interaction: discord.Interaction, player: discord.Member, team: str
    ):
        pass

    @app_commands.command(name="sub", description="Substitute a player on a team")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def _substitute(self, interaction: discord.Interaction):
        # Automate this?
        pass

    @app_commands.command(
        name="announce",
        description="Perform a generic announcement to the transactions channel.",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def _transaction_announce(
        self, interaction: discord.Interaction, message: str
    ):
        trans_channel = await self._trans_channel(interaction.guild)
        if not trans_channel:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Transaction channel is not configured."),
                ephemeral=True,
            )
            return

        await trans_channel.send(
            message, allowed_mentions=discord.AllowedMentions(users=True)
        )
        await interaction.response.send_message(content="Done", ephemeral=True)

    @app_commands.command(
        name="announcetrade",
        description="Announce a trade between two franchises to the transaction chanenl",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def _transaction_announcetrade(self, interaction: discord.Interaction):
        trans_channel = await self._trans_channel(interaction.guild)
        if not trans_channel:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Transaction channel is not configured."),
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="Trade Announcement", color=discord.Color.blue())
        trade_view = TradeAnnouncementView()
        await interaction.response.send_message(embed=embed, view=trade_view)

        # if not trade.trade:
        #     await interaction.followup.send_message(content="No trade announcement provided.", ephemeral=True)
        #     return

        # log.debug(f"Trade Announcement: {trade.trade}")
        # await trans_channel.send(content=trade.trade, allowed_mentions=discord.AllowedMentions(users=True))
        # TODO - modal not working for this because mentions

    # API

    # Config

    async def _trans_role(self, guild: discord.Guild) -> Optional[discord.Role]:
        trans_role_id = await self.config.custom("Transactions", guild.id).TransRole()
        return guild.get_role(trans_role_id)

    async def _save_trans_role(
        self, guild: discord.Guild, trans_role_id: Optional[int]
    ):
        await self.config.custom("Transactions", guild.id).TransRole.set(trans_role_id)

    async def _trans_channel(
        self, guild: discord.Guild
    ) -> Optional[discord.TextChannel]:
        trans_channel_id = await self.config.custom(
            "Transactions", guild.id
        ).TransChannel()
        return guild.get_channel(trans_channel_id)

    async def _save_trans_channel(
        self, guild: discord.Guild, trans_channel: Optional[int]
    ):
        await self.config.custom("Transactions", guild.id).TransChannel.set(
            trans_channel
        )

    async def _trans_log_channel(
        self, guild: discord.Guild
    ) -> Optional[discord.TextChannel]:
        log_channel_id = await self.config.custom(
            "Transactions", guild.id
        ).TransLogChannel()
        return guild.get_channel(log_channel_id)

    async def _save_trans_log_channel(
        self, guild: discord.Guild, trans_log_channel: Optional[int]
    ):
        await self.config.custom("Transactions", guild.id).TransLogChannel.set(
            trans_log_channel
        )

    async def _get_cut_message(self, guild: discord.Guild) -> Optional[str]:
        return await self.config.custom("Transactions", guild.id).CutMessage()

    async def _save_cut_message(self, guild: discord.Guild, message):
        await self.config.custom("Transactions", guild.id).CutMessage.set(message)

    async def _notifications_enabled(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Transactions", guild.id).TransNotifications()

    async def _set_notifications(self, guild: discord.Guild, enabled: bool):
        await self.config.custom("Transactions", guild.id).TransNotifications.set(
            enabled
        )
