import discord
import logging
import itertools

from discord.ext import tasks
from datetime import datetime, time, timedelta

from redbot.core import Config, app_commands, commands, checks

from rscapi import ApiClient, TransactionsApi, LeaguePlayersApi
from rscapi.exceptions import ApiException
from rscapi.models.cut_a_player_from_a_league import CutAPlayerFromALeague
from rscapi.models.re_sign_player import ReSignPlayer
from rscapi.models.sign_a_player_to_a_team_in_a_league import (
    SignAPlayerToATeamInALeague,
)
from rscapi.models.transaction_response import TransactionResponse
from rscapi.models.player_transaction_updates import PlayerTransactionUpdates
from rscapi.models.temporary_fa_sub import TemporaryFASub
from rscapi.models.player_transaction_updates import PlayerTransactionUpdates
from rscapi.models.expire_a_player_sub import ExpireAPlayerSub
from rscapi.models.league_player import LeaguePlayer

from rsc.abc import RSCMixIn
from rsc.enums import Status
from rsc.const import CAPTAIN_ROLE, DEV_LEAGUE_ROLE, FREE_AGENT_ROLE
from rsc.embeds import (
    ErrorEmbed,
    SuccessEmbed,
    BlueEmbed,
    ExceptionErrorEmbed,
    ApiExceptionErrorEmbed,
)
from rsc.exceptions import RscException, translate_api_error
from rsc.teams import TeamMixIn
from rsc.transactions.views import TradeAnnouncementModal, TradeAnnouncementView
from rsc.types import Substitute
from rsc.utils import utils


from typing import Optional, TypedDict, List

log = logging.getLogger("red.rsc.transactions")

defaults = {
    "TransChannel": None,
    "TransDMs": False,
    "TransLogChannel": None,
    "TransNotifications": False,
    "TransRole": None,
    "CutMessage": None,
    "ContractExpirationMessage": None,
    "Substitutes": [],
}

# Noon - Eastern (-5) - Not DST aware
# Have to use UTC for loop. TZ aware object causes issues with clock drift calculations
SUB_LOOP_TIME = time(hour=17)


class TransactionMixIn(RSCMixIn):
    def __init__(self):
        # Prepare configuration group
        self.config.init_custom("Transactions", 1)
        self.config.register_custom("Transactions", **defaults)
        super().__init__()

    # Tasks

    @tasks.loop(time=SUB_LOOP_TIME)
    async def expire_sub_contract_loop(self):
        """Send contract expiration message to Transaction Channel"""
        log.debug("Expire sub contract loop is running")
        for guild in self.bot.guilds:
            subs: List[Substitute] = await self._get_substitutes(guild)
            if not subs:
                log.debug(f"No substitutes to expire in  {guild.name}")
                continue

            tchan = await self._trans_channel(guild)
            if not tchan:
                log.warning(
                    f"Substitutes found but transaction channel not set in {guild.name}"
                )
                continue

            subbed_out_role = await utils.get_subbed_out_role(guild)

            guild_tz = await self.timezone(guild)
            yesterday = datetime.now(guild_tz) - timedelta(1)

            # Loop through checkins.
            for s in subs:
                sub_date = datetime.fromisoformat(s["date"])
                if sub_date.date() <= yesterday.date():
                    log.debug(f"[{guild.name} Expiring Sub Contract: {s['player_in']}")
                    await self._rm_substitute(guild, s)
                    await tchan.send(
                        content=f"<@{s['player_in']}> has finished their time as a substitute for {s['team']} (<@{s['gm']}> - {s['tier']})",
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                    if subbed_out_role:
                        m = guild.get_member(s["player_out"])
                        if m:
                            await m.remove_roles(subbed_out_role)

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
        notifications = await self._notifications_enabled(interaction.guild)
        dms = await self._trans_dms_enabled(interaction.guild)
        cut_msg = await self._get_cut_message(interaction.guild) or "None"

        settings_embed = discord.Embed(
            title="Transactions Settings",
            description="Current configuration for Transactions",
            color=discord.Color.blue(),
        )

        settings_embed.add_field(
            name="Notifications Enabled", value=notifications, inline=False
        )

        settings_embed.add_field(
            name="Direct Messages Enabled", value=dms, inline=False
        )

        # Check channel values before mention to avoid exception
        settings_embed.add_field(
            name="Transaction Channel",
            value=trans_channel.mention if trans_channel else "None",
            inline=False,
        )

        settings_embed.add_field(
            name="Log Channel",
            value=log_channel.mention if log_channel else "None",
            inline=False,
        )

        settings_embed.add_field(
            name="Committee Role",
            value=trans_role.mention if trans_role else "None",
            inline=False,
        )

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

    @_transactions.command(
        name="dm", description="Toggle player direct messages on or off"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def transactions_dms_toggle(self, interaction: discord.Interaction):
        """Toggle channel notifications on or off"""
        status = await self._trans_dms_enabled(interaction.guild)
        log.debug(f"Current DM Status: {status}")
        status ^= True  # Flip boolean with xor
        log.debug(f"New Transaction DMs Status: {status}")
        await self._set_trans_dm(interaction.guild, status)
        result = "**enabled**" if status else "**disabled**"
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Successs",
                description=f"Player transaction direct messages are now {result}.",
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
                embed=ErrorEmbed(description="Only admins can process an override.")
            )
            return

        # Defer
        await interaction.response.defer(ephemeral=True)

        try:
            result = await self.cut(
                interaction.guild,
                player=player,
                executor=interaction.user,
                override=override,
            )
            log.debug(f"Cut Result: {result}")
        except RscException as exc:
            log.warning(
                f"[{interaction.guild.name}] Transaction Exception: {exc.reason}"
            )
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return

        ptu = await self.league_player_from_transaction(result, player=player)

        # Update tier role, handle promotion case
        log.debug(f"[{interaction.guild.name}] Updating tier roles for {player.id}")
        old_tier_role = await utils.get_tier_role(interaction.guild, ptu.old_team.tier)
        tier_role = await utils.get_tier_role(interaction.guild, ptu.player.tier.name)
        if old_tier_role != tier_role:
            await player.remove_roles(old_tier_role)
            await player.add_roles(tier_role)

        # Apply tier role if they never had it
        if tier_role not in player.roles:
            await player.add_roles(tier_role)

        # Free agent roles
        fa_role = await utils.get_free_agent_role(interaction.guild)
        tier_fa_role = await utils.get_tier_fa_role(
            interaction.guild, ptu.player.tier.name
        )

        # Franchise Role
        franchise_role = await utils.franchise_role_from_name(
            interaction.guild, result.first_franchise.name
        )
        if not franchise_role:
            log.error(
                f"[{interaction.guild.name}] Unable to find franchise name during cut: {result.first_franchise.name}"
            )
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"Unable to find franchise role for **{result.first_franchise.name}**"
                ),
                ephemeral=True,
            )
            return

        # Make changes for Non-GM player
        if result.first_franchise.gm.discord_id != player.id:
            new_nick = f"FA | {await utils.remove_prefix(player)}"
            log.debug(f"Changing cut players nickname to: {new_nick}")
            await player.edit(nick=new_nick)
            await player.remove_roles(franchise_role)
            await player.add_roles(fa_role, tier_fa_role)

            # Add Dev League Interest if it exists
            # dev_league_role = discord.utils.get(
            #     interaction.guild.roles, name=DEV_LEAGUE_ROLE
            # )
            # if dev_league_role:
            #     await player.add_roles(dev_league_role)

        # Announce to transaction channel
        trans_channel = await self._trans_channel(interaction.guild)
        if trans_channel:
            await trans_channel.send(
                f"{player.mention} was cut by {ptu.old_team.name} (<@{result.first_franchise.gm.discord_id}> - {ptu.old_team.tier})",
                allowed_mentions=discord.AllowedMentions(users=True),
            )

        # Send cut message to user directly
        dm_status = await self._trans_dms_enabled(interaction.guild)
        cutmsg = await self._get_cut_message(interaction.guild)
        if dm_status and cutmsg:
            embed = BlueEmbed(
                title=f"Message from {interaction.guild.name}", description=cutmsg
            )
            if interaction.guild.icon:
                embed.set_thumbnail(url=interaction.guild.icon.url)
            await player.send(embed=embed)

        # Send result
        await interaction.followup.send(
            embed=SuccessEmbed(
                description=f"{player.mention} has been released to the Free Agent pool."
            ),
            ephemeral=True,
        )

    @_transactions.command(
        name="sign", description="Sign a player to the specified team"
    )
    @app_commands.describe(
        player="Player to sign",
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
        if override and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Only admins can process an override.")
            )
            return

        # Sign player
        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.sign(
                interaction.guild,
                player=player,
                team=team,
                executor=interaction.user,
                override=override,
            )
            log.debug(f"[{interaction.guild.name}] Sign Result: {result}]")
        except RscException as exc:
            log.warning(
                f"[{interaction.guild.name}] Transaction Exception: {exc.reason}"
            )
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return

        ptu: PlayerTransactionUpdates = await self.league_player_from_transaction(
            result, player=player
        )

        # Remove FA roles
        log.debug(f"[{interaction.guild.name}] Removing FA roles from {player.id}")
        fa_role = await utils.get_free_agent_role(interaction.guild)
        tier_fa_role = await utils.get_tier_fa_role(
            interaction.guild, ptu.player.tier.name
        )
        await player.remove_roles(fa_role, tier_fa_role)

        # Add franchise role
        log.debug(f"[{interaction.guild.name}] Adding franchise role to {player.id}")
        frole = await utils.franchise_role_from_league_player(
            interaction.guild, ptu.player
        )

        # Verify player has tier role
        log.debug(f"[{interaction.guild.name}] Adding tier role to {player.id}")
        tier_role = await utils.get_tier_role(interaction.guild, name=ptu.new_team.tier)
        await player.add_roles(frole, tier_role)

        # Change member prefix
        new_nick = (
            f"{ptu.player.team.franchise.prefix} | {await utils.remove_prefix(player)}"
        )
        log.debug(
            f"[{interaction.guild.name}] Changing signed player nick to {player.id}"
        )
        await player.edit(nick=new_nick)

        # Announce to transaction channel
        trans_channel = await self._trans_channel(interaction.guild)
        if trans_channel:
            await trans_channel.send(
                f"{player.mention} was signed by {ptu.new_team.name} (<@{result.second_franchise.gm.discord_id}> - {ptu.new_team.tier})",
                allowed_mentions=discord.AllowedMentions(users=True),
            )

        # Send result
        await interaction.followup.send(
            embed=SuccessEmbed(
                description=f"{player.mention} has been signed to **{ptu.new_team.name}**"
            ),
            ephemeral=True,
        )

    @_transactions.command(name="resign", description="Re-sign a player to their team.")
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)
    async def _transactions_resign(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        team: str,
        override: bool = False,
    ):
        if override and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Only admins can process an override.")
            )
            return

        await interaction.response.defer(ephemeral=True)
        # Process sign
        try:
            result = await self.resign(
                interaction.guild,
                player=player,
                team=team,
                executor=interaction.user,
                override=override,
            )
            log.debug(f"[{interaction.guild.name}] Re-sign Result: {result}]")
        except RscException as exc:
            log.warning(
                f"[{interaction.guild.name}] Transaction Exception: {exc.reason}"
            )
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return

        ptu: PlayerTransactionUpdates = await self.league_player_from_transaction(
            result, player=player
        )

        # We check roles and name here just in case.
        # Remove FA roles
        log.debug(f"[{interaction.guild.name}] Removing FA roles from {player.id}")
        fa_role = await utils.get_free_agent_role(interaction.guild)
        tier_fa_role = await utils.get_tier_fa_role(
            interaction.guild, ptu.player.tier.name
        )
        await player.remove_roles(fa_role, tier_fa_role)

        # Add franchise role
        log.debug(f"[{interaction.guild.name}] Adding franchise role to {player.id}")
        frole = await utils.franchise_role_from_league_player(
            interaction.guild, ptu.player
        )

        # Verify player has tier role
        log.debug(f"[{interaction.guild.name}] Adding tier role to {player.id}")
        tier_role = await utils.get_tier_role(
            interaction.guild.roles, name=ptu.new_team.tier
        )
        await player.add_roles(frole, tier_role)

        # Change member prefix
        new_nick = (
            f"{ptu.player.team.franchise.prefix} | {await utils.remove_prefix(player)}"
        )
        log.debug(
            f"[{interaction.guild.name}] Changing signed player nick to {player.id}"
        )
        await player.edit(nick=new_nick)

        # Announce to transaction channel
        trans_channel = await self._trans_channel(interaction.guild)
        if trans_channel:
            await trans_channel.send(
                f"{player.mention} was re-signed by {ptu.new_team.name} (<@{result.first_franchise.gm.discord_id}> - {ptu.new_team.tier})",
                allowed_mentions=discord.AllowedMentions(users=True),
            )

        # Send result
        await interaction.followup.send(
            embed=SuccessEmbed(
                description=f"{player.mention} has been re-signed to **{ptu.new_team.name}**"
            ),
            ephemeral=True,
        )

    @_transactions.command(name="sub", description="Substitute a player on a team")
    @app_commands.describe(
        player_in="Player being subbed in on the team",
        player_out="Player being subbed out on the team",
        notes="Substitation notes (Optional)",
        override="Admin only override",
    )
    async def _transactions_substitute(
        self,
        interaction: discord.Interaction,
        player_in: discord.Member,
        player_out: discord.Member,
        notes: Optional[str] = None,
        override: bool = False,
    ):
        if override and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Only admins can process an override.")
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.substitution(
                interaction.guild,
                player_in=player_in,
                player_out=player_out,
                executor=interaction.user,
                notes=notes,
                override=override,
            )
            log.debug(f"Sub Result: {result}")
        except RscException as exc:
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return

        ptu_in: PlayerTransactionUpdates = await self.league_player_from_transaction(
            result, player_in
        )
        ptu_out: PlayerTransactionUpdates = await self.league_player_from_transaction(
            result, player_out
        )

        gm_id = result.second_franchise.gm.discord_id

        # Send to transaction channel
        tchan = await self._trans_channel(interaction.guild)
        if tchan:
            await tchan.send(
                f"{player_in.mention} was signed to a temporary contract by {ptu_in.new_team.name}, subbing for {player_out.mention} (<@{gm_id}> - {ptu_in.new_team.tier})",
                allowed_mentions=discord.AllowedMentions(users=True),
            )

        # Save sub for expiration later
        tz = await self.timezone(interaction.guild)
        sub_obj = Substitute(
            date=str(datetime.now(tz)),
            player_in=player_in.id,
            player_out=player_out.id,
            team=ptu_in.new_team.name,
            gm=result.second_franchise.gm.discord_id,
            tier=ptu_in.new_team.tier,
        )
        await self._add_substitute(interaction.guild, sub_obj)

        # Subbed out role
        subbed_out_role = await utils.get_subbed_out_role(interaction.guild)
        await player_out.add_roles(subbed_out_role)

        embed = SuccessEmbed(
            description=f"{player_out.mention} has been subbed out for {player_in.mention}"
        )
        embed.add_field(
            name="Date", value=result.var_date.strftime("%Y-%m-%d"), inline=True
        )
        embed.add_field(name="Match Day", value=result.match_day, inline=True)
        embed.add_field(name="Type", value=result.type, inline=True)
        if result.notes:
            embed.add_field(name="Notes", value=result.notes, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

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
        await interaction.response.defer(ephemeral=True)
        # Get team of player being made captain
        player_list = await self.players(
            interaction.guild, discord_id=player.id, limit=1
        )

        if not player_list:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"{player.mention} is not a league player."
                ),
                ephemeral=True,
            )
            return

        player_data = player_list.pop()

        if player_data.status != Status.ROSTERED:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"{player.mention} is not currently rostered."
                ),
                ephemeral=True,
            )
            return

        # Get team data
        team_players = await self.team_players(interaction.guild, player_data.team.id)

        # Get Captain Role
        cpt_role = await utils.get_captain_role(interaction.guild)
        if not cpt_role:
            await interaction.followup.send(
                embed=ErrorEmbed(description="Captain role does not exist in guild.")
            )
            return

        # Remove captain role from anyone on the team that has it just in case
        notFound = []
        for p in team_players:
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

        # Announce to transaction channel
        trans_channel = await self._trans_channel(interaction.guild)
        if trans_channel:
            await trans_channel.send(
                f"{player.mention} was elected captain of {player_data.team.name} (<@{player_data.team.franchise.gm.discord_id}> - {player_data.tier.name})",
                allowed_mentions=discord.AllowedMentions(users=True),
            )

        # Send Result
        embed = SuccessEmbed(
            title="Captain Designated",
            description=f"{player.mention} has been promoted to **captain**",
        )
        if notFound:
            embed.add_field(name="Players Not Found", value="\n".join(notFound))

        await interaction.followup.send(embed=embed, ephemeral=True)

    @_transactions.command(
        name="expire",
        description="Manually expire a temporary FA contract",
    )
    async def _transactions_expire(
        self, interaction: discord.Interaction, player: discord.Member
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.expire_sub(
                interaction.guild,
                player=player,
                executor=interaction.user,
            )
            log.debug(f"Expire Sub Result: {result}")
        except RscException as exc:
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return

        # Get sub object and remove it from saved list
        sub_obj = await self.get_sub(player)
        if sub_obj:
            await self._rm_substitute(interaction.guild, sub_obj)

            # Remove subbed out role from subbed player
            subbed_out_role = await utils.get_subbed_out_role(interaction.guild)
            p_out = interaction.guild.get_member(sub_obj["player_out"])
            if subbed_out_role and p_out:
                await p_out.remove_roles(subbed_out_role)

            # Post to transactions
            tchan = await self._trans_channel(interaction.guild)
            if tchan:
                await tchan.send(
                    content=f"{player.mention} has finished their time as a substitute for {sub_obj['team']} (<@{sub_obj['gm']}> - {sub_obj['tier']})",
                    allowed_mentions=discord.AllowedMentions(users=True),
                )

        await interaction.followup.send(
            embed=SuccessEmbed(
                description=f"The temporary FA contract for {player.mention} has been expired."
            ),
            ephemeral=True,
        )

    @_transactions.command(
        name="sublist",
        description="Fetch a list of all players with a temporary FA contract",
    )
    async def _transactions_sublist(self, interaction: discord.Interaction):
        subs = await self._get_substitutes(interaction.guild)
        embed = BlueEmbed(
            title="Temporary FA Contracts",
            description="List of all players with a temporary FA contract",
        )
        sub_fmt = [(x["player_in"], x["player_out"], x["team"]) for x in subs]
        embed.add_field(
            name="In", value="\n".join([f"<@{x[0]}>" for x in sub_fmt]), inline=True
        )
        embed.add_field(
            name="Out", value="\n".join([f"<@{x[1]}>" for x in sub_fmt]), inline=True
        )
        embed.add_field(
            name="Team", value="\n".join([x[2] for x in sub_fmt]), inline=True
        )
        await interaction.response.send_message(embed=embed)

    # Functions

    async def league_player_from_transaction(
        self, transaction: TransactionResponse, player=discord.Member
    ) -> PlayerTransactionUpdates:
        lp = next(
            (
                x
                for x in transaction.player_updates
                if x.player.player.discord_id == player.id
            )
        )
        return lp

    async def get_sub(self, member: discord.Member) -> Optional[Substitute]:
        """Get sub from saved subsitute list"""
        subs = await self._get_substitutes(member.guild)
        s = next((x for x in subs if x["player_in"] == member.id), None)
        return s

    # API

    async def sign(
        self,
        guild: discord.Guild,
        player: discord.Member,
        team: str,
        executor: discord.Member,
        override: bool = False,
    ) -> TransactionResponse:
        """Sign player to a team"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TransactionsApi(client)
            data = SignAPlayerToATeamInALeague(
                player=player.id,
                league=self._league[guild.id],
                team=team,
                executor=executor.id,
                admin_override=override,
            )
            log.debug(f"[{guild.name}] Sign Parameters: {data}")
            try:
                return await api.transactions_sign_create(data)
            except ApiException as exc:
                await translate_api_error(exc)

    async def cut(
        self,
        guild: discord.Guild,
        player: discord.Member,
        executor: discord.Member,
        override: bool = False,
    ) -> TransactionResponse:
        """Cut a player from their team"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TransactionsApi(client)
            data = CutAPlayerFromALeague(
                player=player.id,
                league=self._league[guild.id],
                executor=executor.id,
                admin_override=override,
            )
            log.debug(f"[{guild.name}] Cut Parameters: {data}")
            try:
                return await api.transactions_cut_create(data)
            except ApiException as exc:
                await translate_api_error(exc)

    async def resign(
        self,
        guild: discord.Guild,
        player: discord.Member,
        team: str,
        executor: discord.Member,
        override: bool = False,
    ) -> TransactionResponse:
        """Resign player to a team"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TransactionsApi(client)
            data = ReSignPlayer(
                player=player.id,
                league=self._league[guild.id],
                team=team,
                executor=executor.id,
                admin_override=override,
            )
            log.debug(f"[{guild.name}] Resign Parameters: {data}")
            try:
                return await api.transactions_resign_create(data)
            except ApiException as exc:
                await translate_api_error(exc)

    async def set_captain(self, guild: discord.Guild, id: int) -> LeaguePlayer:
        """Set a player as captain using their discord ID"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = LeaguePlayersApi(client)
            return await api.league_players_set_captain(id)

    async def substitution(
        self,
        guild: discord.Guild,
        player_in: discord.Member,
        player_out: discord.Member,
        executor: discord.Member,
        notes: Optional[str] = None,
        override: bool = False,
    ) -> TransactionResponse:
        """Sub a player in for another player"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TransactionsApi(client)
            data = TemporaryFASub(
                league=self._league[guild.id],
                player_in=player_in.id,
                player_out=player_out.id,
                executor=executor.id,
                notes=notes,
                admin_override=override,
            )
            log.debug(f"Sub Data: {data}")
            try:
                return await api.transactions_substitution_create(data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def expire_sub(
        self,
        guild: discord.Guild,
        player: discord.Member,
        executor: discord.Member,
    ) -> LeaguePlayer:
        """Sub a player in for another player"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TransactionsApi(client)
            data = ExpireAPlayerSub(
                league=self._league[guild.id], player=player.id, executor=executor.id
            )
            log.debug(f"Expire Sub Data: {data}")
            try:
                return await api.transactions_expire_create(data)
            except ApiException as exc:
                raise RscException(response=exc)

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

    async def _trans_dms_enabled(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Transactions", guild.id).TransDMs()

    async def _set_trans_dm(self, guild: discord.Guild, enabled: bool):
        await self.config.custom("Transactions", guild.id).TransDMs.set(enabled)

    async def _get_substitutes(self, guild: discord.Guild) -> List[Substitute]:
        return await self.config.custom("Transactions", guild.id).Substitutes()

    async def _set_substitutes(self, guild: discord.Guild, subs: List[Substitute]):
        await self.config.custom("Transactions", guild.id).Substitutes.set(subs)

    async def _add_substitute(self, guild: discord.Guild, sub: Substitute):
        s = await self.config.custom("Transactions", guild.id).Substitutes()
        s.append(sub)
        await self._set_substitutes(guild, s)

    async def _rm_substitute(self, guild: discord.Guild, sub: Substitute):
        s = await self.config.custom("Transactions", guild.id).Substitutes()
        s.remove(sub)
        await self._set_substitutes(guild, s)
