import discord
import logging

from redbot.core import Config, app_commands, commands, checks

from rscapi import ApiClient, TransactionsApi, LeaguePlayersApi
from rscapi.exceptions import ApiException
from rscapi.models.cut_a_player_from_a_league import CutAPlayerFromALeague
from rscapi.models.league_player import LeaguePlayer

from rsc.abc import RSCMixIn
from rsc.enums import Status
from rsc.const import CAPTAIN_ROLE
from rsc.embeds import ErrorEmbed, SuccessEmbed, BlueEmbed, ExceptionErrorEmbed
from rsc.exceptions import PastTransactionsEndDate
from rsc.teams import TeamMixIn
from rsc.transactions.views import TradeAnnouncementModal, TradeAnnouncementView
from rsc.utils.utils import get_captain_role, is_gm

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


class TransactionMixIn(RSCMixIn):
    def __init__(self):
        # Prepare configuration group
        self.config.init_custom("Transactions", 1)
        self.config.register_custom("Transactions", **defaults)
        super().__init__()

    # Group

    _transactions = app_commands.Group(
        name="transactions",
        description="Transactions Configuration",
        guild_only=True,
        default_permissions=discord.Permissions(manage_roles=True),
    )

    # Settings

    @_transactions.command(
        name="settings", description="Display settings for transactions"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _transactions_settings(self, interaction: discord.Interaction):
        """Show transactions settings"""
        log_channel = await self._trans_log_channel(interaction.guild)
        trans_channel = await self._trans_channel(interaction.guild)
        trans_role = await self._trans_role(interaction.guild)
        cut_msg = await self._get_cut_message(interaction.guild) or "None"
        notifications = await self._notifications_enabled(interaction.guild)
        settings_embed = discord.Embed(
            title="Transactions Settings",
            description="Current configuration for Transactions",
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
    async def transactions_notifications(self, interaction: discord.Interaction):
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
    async def _transactions_channel(
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
    async def _transactions_log(
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
    async def _transactions_role(
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
    async def _transactions_cutmsg(self, interaction: discord.Interaction, *, msg: str):
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

    # Committee Commands

    @_transactions.command(name="cut", description="Release a player from their team")
    @app_commands.describe(player="Player to cut", override="Admin only override")
    async def _transactions_cut(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        override: bool = False,
    ):
        if override and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Only Admins can turn on override.")
            )
            return

        try:
            cut = await self.cut(
                interaction.guild,
                player=player,
                executor=interaction.user,
                override=override,
            )
            log.debug(cut)
        except PastTransactionsEndDate as exc:
            await interaction.response.send_message(
                embed=ExceptionErrorEmbed(exc_message=exc.reason), ephemeral=True
            )
            return

        # Handle not in the league
        # Handle not on a team

        # Query new data on tier/player from leagueplayers
        # remove prefix from user name
        # Handle if GM
        # Handle if AGM
        # Remove franchise role
        # Give tier FA role, Give Free Agent Role
        # Change prefix to FA

        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"{player.display_name} has been released to the Free Agent pool."
            ),
            ephemeral=True,
        )

    # Cut player
    # Send user the cut message

    @_transactions.command(
        name="sign", description="Sign a player to the specified team"
    )
    @app_commands.describe(
        player="Player to cut",
        team="Team the player is being sign on",
        override="Admin only override",
    )
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)
    async def _transactions_sign(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        team: str,
        override: bool = False,
    ):
        pass

    @_transactions.command(name="resign", description="Re-sign a player to their team.")
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)
    async def _transactions_resign(
        self, interaction: discord.Interaction, player: discord.Member, team: str
    ):
        pass

    @_transactions.command(name="sub", description="Substitute a player on a team")
    async def _transactions_substitute(self, interaction: discord.Interaction):
        # Automate this?
        pass

    @_transactions.command(
        name="announce",
        description="Perform a generic announcement to the transactions channel.",
    )
    async def _transactions_announce(
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

    @_transactions.command(
        name="announcetrade",
        description="Announce a trade between two franchises to the transaction chanenl",
    )
    async def _transactions_announcetrade(self, interaction: discord.Interaction):
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

    @_transactions.command(
        name="captain",
        description="Promote a player to captain of their team",
    )
    async def _transactions_captain(
        self, interaction: discord.Interaction, player: discord.Member
    ):
        # Get team of player being made captain
        player_list = await self.players(
            interaction.guild, discord_id=player.id, limit=1
        )

        if not player_list:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description=f"{player.mention} is  not a league player."
                ),
                ephemeral=True,
            )
            return

        player_data = player_list.pop()

        if player_data.status != Status.ROSTERED:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description=f"{player.mention} is  not currently rostered."
                ),
                ephemeral=True,
            )
            return

        # Get team data
        team_players = await self.team_players(interaction.guild, player_data.team.id)

        # Get Captain Role
        cpt_role = await get_captain_role(interaction.guild)
        if not cpt_role:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Captain role does not exist in guild.")
            )
            return

        # Find current captain and remove role. Iterate all just in case
        notFound = []
        for p in team_players:
            if not p.captain:
                continue
            m = interaction.guild.get_member(p.discord_id)

            if not m:
                log.error(
                    f"[{interaction.guild.name}] Unable to find rostered player in guild: {p.discord_id}"
                )
                notFound.append(str(p.discord_id))
                continue
            log.debug(f"Removing captain role from: {m.display_name}")
            await m.remove_roles(cpt_role)

        # Promote new player to captain
        await self.set_captain(interaction.guild, player_data.id)
        await player.add_roles(cpt_role)

        embed = SuccessEmbed(
            title="Captain Designated",
            description=f"{player.mention} has been promoted to **captain**",
        )
        if notFound:
            embed.add_field(
                name="Warning: Members not in guild", value="\n".join(notFound)
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # Non-Group Commands

    # API

    async def cut(
        self,
        guild: discord.Guild,
        player: discord.Member,
        executor: discord.Member,
        override: bool = False,
    ) -> CutAPlayerFromALeague:
        """Cut a player from their team"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TransactionsApi(client)
            data = CutAPlayerFromALeague(
                player=player.id,
                league=self._league[guild.id],
                executor=executor.id,
                admin_override=1 if override else 0,
            )
            log.debug(f"[{guild.name}] Cut Parameters: {data}")
            try:
                return await api.transactions_cut_create(data)
            except ApiException as exc:
                log.debug(f"EXC BODY TYPE: {type(exc.body)}")
                log.debug(f"EXC BODY: {exc.body}")
                reason = exc.body.get("detail", None)
                if not reason:
                    raise exc
                elif reason.startswith("Cannot cut a player past the transactions"):
                    raise PastTransactionsEndDate(response=exc)

    async def set_captain(self, guild: discord.Guild, id: int) -> LeaguePlayer:
        """Set a player as captain using their discord ID"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = LeaguePlayersApi(client)
            return await api.league_players_set_captain(id)

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
