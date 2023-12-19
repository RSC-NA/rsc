import discord
import logging
import itertools
from copy import deepcopy
from datetime import datetime

from discord.ext import tasks
from datetime import datetime, time, timedelta
from pathlib import Path

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
from rscapi.models.league import League
from rscapi.models.player_transaction_updates import PlayerTransactionUpdates
from rscapi.models.expire_a_player_sub import ExpireAPlayerSub
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.retire_a_player import RetireAPlayer
from rscapi.models.inactive_reserve import InactiveReserve

from rsc.abc import RSCMixIn
from rsc.enums import Status, TransactionType
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
from rsc.types import Substitute, TransactionSettings
from rsc.utils import utils


from typing import Optional, TypedDict, List

log = logging.getLogger("red.rsc.transactions")


defaults = TransactionSettings(
    TransChannel=None,
    TransDMs=False,
    TransLogChannel=None,
    TransNotifications=False,
    TransRole=None,
    CutMessage=None,
    ContractExpirationMessage=None,
    Substitutes=[],
)


# Noon - Eastern (-5) - Not DST aware
# Have to use UTC for loop. TZ aware object causes issues with clock drift calculations
SUB_LOOP_TIME = time(hour=17)


class TransactionMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing TransactionMixIn")
        # Prepare configuration group
        self.config.init_custom("Transactions", 1)
        self.config.register_custom("Transactions", **defaults)
        super().__init__()

        # Start sub expire loop
        self.expire_sub_contract_loop.start()

    # Tasks

    @tasks.loop(time=SUB_LOOP_TIME)
    async def expire_sub_contract_loop(self):
        """Send contract expiration message to Transaction Channel"""
        log.debug("Expire sub contracts loop started")
        for guild in self.bot.guilds:
            log.debug(f"[{guild.name}] Expire sub contract loop is running")
            subs: list[Substitute] = deepcopy(await self._get_substitutes(guild))
            if not subs:
                log.debug(f"No substitutes to expire in  {guild.name}")
                continue

            tchan = await self._trans_channel(guild)
            if not tchan or not hasattr(tchan, "send"):
                log.warning(
                    f"Substitutes found but transaction channel not set in {guild.name}"
                )
                continue

            subbed_out_role = await utils.get_subbed_out_role(guild)

            guild_tz = await self.timezone(guild)
            yesterday = datetime.now(guild_tz) - timedelta(1)

            # Get ContractExpired image
            img_path = (
                Path(__file__).parent.parent
                / "resources/transactions/ContractExpired.png"
            )

            # Loop through checkins.
            for s in subs:
                sub_date = datetime.fromisoformat(s["date"])
                dFiles = [discord.File(img_path)]
                if sub_date.date() <= yesterday.date():
                    # Get FA img resource
                    fa_icon = await utils.fa_img_from_tier(s["tier"], tiny=True)

                    # Tier color
                    tier_color = await utils.tier_color_by_name(guild, s["tier"])

                    # Get Member
                    m_in = guild.get_member(s["player_in"])
                    m_out = guild.get_member(s["player_out"])

                    m_in_fmt = m_in.display_name if m_in else f"<@{s['player_in']}>"
                    m_out_fmt = m_out.display_name if m_out else f"<@{s['player_out']}>"

                    log.debug(f"[{guild.name} Expiring Sub Contract: {s['player_in']}")
                    embed = discord.Embed(color=tier_color)
                    embed.set_image(url=f"attachment://{img_path.name}")
                    if fa_icon:
                        dFiles.append(fa_icon)
                        embed.set_author(
                            name=f"{m_in_fmt} has finished temporary contract for {s['team']}",
                            icon_url=f"attachment://{fa_icon.filename}",
                        )
                    else:
                        embed.set_author(
                            name=f"{m_in_fmt} has finished temporary contract for {s['team']}"
                        )

                    embed.add_field(name="Player In", value=m_out.mention if m_out else f"<@{s['player_in']}>", inline=True)
                    embed.add_field(name="Player Out", value=m_in.mention if m_in else f"<@{s['player_out']}>", inline=True)
                    embed.add_field(name="Franchise", value=s["franchise"], inline=True)

                    # Send ping for player/GM then quickly remove it
                    pingstr = f"<@{s['player_in']}> <@{s['gm']}>"
                    tmsg = await tchan.send(
                        content=pingstr,
                        embed=embed,
                        files=dFiles,
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                    await tmsg.edit(content=None, embed=embed)

                    await self._rm_substitute(guild, s)
                    if subbed_out_role:
                        if m_out:
                            await m_out.remove_roles(subbed_out_role)

    # Listeners

    @commands.Cog.listener("on_member_remove")
    async def _transactions_on_member_remove(self, member: discord.Member):
        """Check if a rostered player has left the server and report to tranasction log channel. Retire player"""
        if not member.guild:
            return

        guild = member.guild
        players = await self.players(guild, discord_id=member.id, limit=1)

        if not players:
            # Member is not a league player, do nothing
            log.debug(
                f"[{guild.name}] {member.display_name} ({member.id}) has left the server but is not on a team. No action taken."
            )
            return

        # Check if user was forcibly removed from server
        perp, reason = await utils.get_audit_log_reason(
            member.guild, member, discord.AuditLogAction.kick
        )

        p = players.pop(0)
        log.info(
            f"[{guild.name}] {member.display_name} ({member.id}) has left the server. Player is being retired. Reason: {reason}"
        )

        # Retire player
        try:
            await self.retire(
                guild,
                player=member,
                executor=member.guild.me,
                notes="Player left the RSC discord server",
                override=True,
            )
        except RscException as exc:
            log.error(f"Error retiring player that left guild: {exc}")
            return

        # Check if notifications are enabled
        if not await self._notifications_enabled(guild):
            return

        # Return if transaction log channel is not configured
        log_channel = await self._trans_log_channel(guild)
        if not log_channel:
            return

        tz = await self.timezone(guild)
        now = datetime.now(tz=tz)

        match p.status:
            case Status.ROSTERED | Status.IR | Status.AGMIR:
                desc = (
                    f"Player left server while rostered on **{p.team.franchise.name}**"
                )
            case Status.UNSIGNED_GM:
                desc = f"A general manager has left the server."
            case _:
                # We only notify for specific statuses
                log.debug(
                    f"Not sending transaction notification. Player Status: {p.status}"
                )
                return

        log_embed = discord.Embed(
            description=desc,
            color=discord.Color.orange(),
            timestamp=now,
        )

        log_embed.add_field(name="Member", value=member.mention, inline=True)
        log_embed.add_field(name="Member ID", value=str(member.id), inline=True)

        if perp:
            log_embed.add_field(name="Kicked", value=perp.mention, inline=True)
        if reason:
            log_embed.add_field(name="Reason", value=str(reason), inline=False)

        log_embed.set_author(
            name=f"{member} ({member.id}) has left the guild",
            url=member.display_avatar,
            icon_url=member.display_avatar,
        )
        log_embed.set_thumbnail(url=member.display_avatar)

        # Ping Transaction Committee if role is configured and send embed to log channel
        await self.announce_to_transaction_committee(
            guild=guild,
            embed=log_embed,
        )

        # Ping GM and AGM in franchise transaction channel.
        if not p.team:
            # Handle GM case
            return

        await self.announce_to_franchise_transactions(
            guild=guild,
            franchise=p.team.franchise.name,
            gm=p.team.franchise.gm.discord_id,
            embed=log_embed,
        )

    # Group

    _transactions = app_commands.Group(
        name="transactions",
        description="Transaction commands and configuration",
        guild_only=True,
        default_permissions=discord.Permissions(manage_roles=True),
    )

    # Settings

    @_transactions.command(
        name="settings", description="Display current transactions settings"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _transactions_settings(self, interaction: discord.Interaction):
        """Show transactions settings"""
        if not interaction.guild:
            return

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
        if not interaction.guild:
            return
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
        name="toggledm", description="Toggle player direct messages on or off"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def transactions_dms_toggle(self, interaction: discord.Interaction):
        """Toggle channel notifications on or off"""
        if not interaction.guild:
            return
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

    @_transactions.command(
        name="transactionchannel",
        description="Configure the transaction announcement channel",
    )
    @app_commands.describe(
        channel="Transaction announcement discord channel (Must be a text channel)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _transactions_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        """Set transaction channel"""
        if not interaction.guild:
            return
        await self._save_trans_channel(interaction.guild, channel.id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"Transaction channel configured to {channel.mention}",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_transactions.command(
        name="logchannel", description="Set the transactions committee log channel"
    )
    @app_commands.describe(
        channel="Transaction committee log discord channel (Must be a text channel)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _transactions_log(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        """Set transactions log channel"""
        if not interaction.guild:
            return
        await self._save_trans_log_channel(interaction.guild, channel.id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"Transaction log channel configured to {channel.mention}",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_transactions.command(
        name="role", description="Configure the transaction committee role"
    )
    @app_commands.describe(role="Transaction committee discord role")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _transactions_role(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        await self._save_trans_role(interaction.guild, role.id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"Transaction committee role configured to {role.mention}",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_transactions.command(
        name="cutmsg", description="Configure the player cut message"
    )
    @app_commands.describe(msg="Cut message string")
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
    @app_commands.describe(
        player="Player to cut",
        notes="Transaction notes [Optional]",
        override="Admin only override",
    )
    async def _transactions_cut(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        notes: str | None = None,
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
                notes=notes,
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

        embed, files = await self.build_transaction_embed(
            guild=interaction.guild,
            response=result,
            player_in=player,
        )

        # Announce to transaction channel
        await self.announce_transaction(
            interaction.guild,
            embed=embed,
            files=files,
            player=player,
            gm=result.first_franchise.gm.discord_id,
        )

        # Send cut message to user directly
        await self.send_cut_msg(interaction.guild, player=player)

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
        notes="Transaction notes [Optional]",
        override="Admin only override",
    )
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)
    async def _transactions_sign(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        team: str,
        notes: str | None = None,
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
                notes=notes,
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
        try:
            await player.edit(nick=new_nick)
        except discord.Forbidden:
            log.warning(f"Forbidden to change name of {player.display_name}")
            pass

        embed, files = await self.build_transaction_embed(
            guild=interaction.guild, response=result, player_in=player
        )

        await self.announce_transaction(
            guild=interaction.guild,
            embed=embed,
            files=files,
            player=player,
            gm=result.second_franchise.gm.discord_id,
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
    @app_commands.describe(
        player="RSC Discord Member",
        team="Name of team player resigning player",
        notes="Transaction notes [Optional]",
        override="Admin only override",
    )
    async def _transactions_resign(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        team: str,
        notes: str | None = None,
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
                notes=notes,
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

        embed, files = await self.build_transaction_embed(
            guild=interaction.guild, response=result, player_in=player
        )

        await self.announce_transaction(
            guild=interaction.guild, embed=embed, files=files, player=player
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
        notes: str | None = None,
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

        embed, files = await self.build_transaction_embed(
            guild=interaction.guild,
            response=result,
            player_in=player_in,
            player_out=player_out,
        )

        await self.announce_transaction(
            guild=interaction.guild,
            embed=embed,
            files=files,
            player=player_in,
            gm=result.second_franchise.gm.discord_id,
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
            franchise=result.second_franchise.name,
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
        embed.add_field(name="Match Day", value=str(result.match_day), inline=True)
        if result.notes:
            # embed.add_field(name="", value="", inline=False)
            embed.add_field(name="Notes", value=result.notes, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @_transactions.command(
        name="announce",
        description="Perform a generic announcement to the transactions channel.",
    )
    @app_commands.describe(
        message="Desired message to announce. Accepts discord member mentions."
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
    @app_commands.describe(player="RSC Discord Member")
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
    @app_commands.describe(player="RSC Discord Member")
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
            stier = sub_obj["tier"]
            p_in = sub_obj["player_in"]
            p_out = sub_obj["player_out"]
            gm_id = sub_obj["gm"]
            steam = sub_obj["team"]
            fname = sub_obj["franchise"]

            # Remove subbed out role from subbed player
            subbed_out_role = await utils.get_subbed_out_role(interaction.guild)
            m_out = interaction.guild.get_member(p_out)
            if subbed_out_role and m_out:
                await m_out.remove_roles(subbed_out_role)

            # Get FA img resource
            fa_icon = await utils.fa_img_from_tier(stier, tiny=True)
            img_path = (
                Path(__file__).parent.parent
                / "resources/transactions/ContractExpired.png"
            )

            dFiles = [discord.File(img_path)]
            if fa_icon:
                dFiles.append(fa_icon)

            # Tier color
            tier_color = await utils.tier_color_by_name(interaction.guild, stier)

            # Post to transactions
            tchan = await self._trans_channel(interaction.guild)
            if tchan:
                embed = discord.Embed(color=tier_color)
                embed.set_image(url="attachment://ContractExpired.png")
                embed.set_author(
                    name=f"{player.display_name} has finished temporary contract for {steam}",
                    icon_url=f"attachment://{fa_icon.filename}" if fa_icon else None,
                )
                embed.add_field(name="Player In", value=f"<@{p_out}>", inline=True)
                embed.add_field(name="Player Out", value=f"<@{p_in}>", inline=True)
                embed.add_field(name="Franchise", value=f"{fname}", inline=True)

                pingstr = f"{player.mention} <@{gm_id}>"

                tmsg = await tchan.send(
                    content=pingstr,
                    embed=embed,
                    files=dFiles,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
                await tmsg.edit(content=None, embed=embed)
            await self._rm_substitute(interaction.guild, sub_obj)

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

    @_transactions.command(
        name="ir",
        description="Modify inactive reserve status of a player",
    )
    @app_commands.describe(
        action="Inactive Reserve Action",
        player="RSC Discord Member",
        notes="Transaction notes [Optional]",
        override="Admin only override",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="MOVE", value=0),
            app_commands.Choice(name="RETURN", value=1),
        ]
    )
    async def _transactions_ir(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[int],
        player: discord.Member,
        notes: str | None = None,
        override: bool = False,
    ):
        if override and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Only admins can process an override.")
            )
            return
        await interaction.response.defer(ephemeral=True)

        remove = True if action.value else False
        log.debug(f"Remove from IR: {remove}")

        try:
            result = await self.inactive_reserve(
                interaction.guild,
                player=player,
                executor=interaction.user,
                notes=notes,
                override=override,
                remove=remove,
            )
            log.debug(f"Expire Sub Result: {result}")
        except RscException as exc:
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return

        # IR Role
        ir_role = await utils.get_ir_role(interaction.guild)

        if ir_role:
            if remove:
                await player.remove_roles(ir_role)
            else:
                await player.add_roles(ir_role)

        embed, files = await self.build_transaction_embed(
            guild=interaction.guild, response=result, player_in=player
        )

        await self.announce_transaction(
            guild=interaction.guild,
            embed=embed,
            files=files,
            player=player,
            gm=result.first_franchise.gm.discord_id,
        )

        action_fmt = "removed from" if remove else "moved to"
        await interaction.followup.send(
            embed=SuccessEmbed(
                description=f"{player.mention} has been {action_fmt} Inactive Reserve."
            ),
            ephemeral=True,
        )

    @_transactions.command(name="retire", description="Retire a player from the league")
    @app_commands.describe(
        player="RSC discord member to retire",
        notes="Transaction notes (Optional)",
        override="Admin only override",
    )
    async def _transactions_retire(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        notes: str | None = None,
        override: bool = False,
    ):
        if override and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Only admins can process an override.")
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.retire(
                interaction.guild,
                player=player,
                executor=interaction.user,
                notes=notes,
                override=override,
            )
            log.debug(f"Retire Result: {result}")
        except RscException as exc:
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return

        ptu = await self.league_player_from_transaction(result, player=player)
        gm_id = None
        fname = None
        tier_color = discord.Color.blue()
        if result.first_franchise:
            gm_id = result.first_franchise.gm.discord_id
            fname = result.first_franchise.name

        # Roles
        old_tier_role = None
        franchise_role = None
        league_role = await utils.get_league_role(interaction.guild)
        if fname:
            franchise_role = await utils.franchise_role_from_name(
                interaction.guild, fname
            )
        if ptu.old_team:
            tier_color = await utils.tier_color_by_name(
                interaction.guild, ptu.old_team.tier
            )
            old_tier_role = await utils.get_tier_role(
                interaction.guild, ptu.old_team.tier
            )

        roles_to_remove = []

        if old_tier_role:
            roles_to_remove.append(old_tier_role)

        if league_role:
            roles_to_remove.append(league_role)

        if franchise_role:
            roles_to_remove.append(franchise_role)

        if roles_to_remove:
            await player.remove_roles(*roles_to_remove)

        spectator_role = await utils.get_spectator_role(interaction.guild)
        if spectator_role:
            await player.add_roles(spectator_role)

        embed, files = await self.build_transaction_embed(
            guild=interactino.guild, response=result, player_in=player
        )

        await self.announce_transaction(
            guild=interaction.guild, embed=embed, files=files, player=player
        )

        # Send result
        await interaction.followup.send(
            embed=SuccessEmbed(
                description=f"{player.mention} has been retired from the league."
            ),
            ephemeral=True,
        )

    @_transactions.command(
        name="clearsublist", description="Clear cached substitute list"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _transactions_clear_sub_list(self, interaction: discord.Interaction):
        await self._set_substitutes(interaction.guild, subs=[])
        await interaction.response.send_message(
            "Locally cached substitute list has been cleared.", ephemeral=True
        )

    # Functions

    async def announce_transaction(
        self,
        guild: discord.Guild,
        embed: discord.Embed,
        files: list[discord.File] = [],
        player: discord.Member | int | None = None,
        gm: discord.Member | int | None = None,
    ) -> discord.Message | None:
        tchan = await self._trans_channel(guild)
        if not tchan:
            return None

        ping_fmt = None
        member_fmt = []

        if isinstance(player, discord.Member):
            member_fmt.append(player.mention)
        elif isinstance(player, int):
            member_fmt.append(f"<@{player}>")

        if isinstance(gm, discord.Member):
            member_fmt.append(gm.mention)
        elif isinstance(gm, int):
            member_fmt.append(f"<@{gm}>")

        ping_fmt = " ".join(member_fmt)
        tmsg = await tchan.send(
            content=ping_fmt,
            embed=embed,
            files=files,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        await tmsg.edit(content=None, embed=embed)
        return tmsg

    async def build_transaction_embed(
        self,
        guild: discord.Guild,
        response: TransactionResponse,
        player_in: discord.Member,
        player_out: discord.Member | None = None,
    ) -> tuple[discord.Embed, list[discord.File]]:
        action = TransactionType(response.type)
        log.debug(f"Building transactions embed for type {action.name}")

        # LeaguePlayer Objects
        ptu_in = await self.league_player_from_transaction(response, player_in)
        ptu_out = None
        if player_out:
            ptu_out = await self.league_player_from_transaction(response, player_out)

        # Locals
        author_fmt = "Generic Transaction"
        author_icon: discord.File | str = ""
        embed = discord.Embed()
        files: list[discord.File] = []
        franchise = None
        gm_id = None
        icon_url = None
        img = None
        tier = None

        # Image resource
        img = await utils.transaction_image_from_type(action)
        embed.set_image(url=f"attachment://{img.filename}")
        files.append(img)

        match action:
            case TransactionType.CUT:
                author_icon = await utils.fa_img_from_tier(
                    ptu_in.old_team.tier, tiny=True
                )
                if author_icon:
                    files.append(author_icon)

                tier = ptu_in.old_team.tier

                author_fmt = f"{ptu_in.player.player.name} has been released by {ptu_in.old_team.name} ({tier})"

                franchise = response.first_franchise.name
                gm_id = response.first_franchise.gm.discord_id
                # player_fmt = player_in.mention

            case TransactionType.PICKUP:
                author_icon = await self.franchise_logo(
                    guild, response.second_franchise.id
                )

                tier = ptu_in.new_team.tier

                author_fmt = f"{ptu_in.player.player.name} has been signed by {ptu_in.new_team.name} ({tier})"

                franchise = response.second_franchise.name
                gm_id = response.second_franchise.gm.discord_id

            case TransactionType.RESIGN:
                author_icon = await self.franchise_logo(
                    guild, response.second_franchise.id
                )

                tier = ptu_in.new_team.tier

                author_fmt = f"{ptu_in.player.player.name} has been re-signed by {ptu_in.new_team.name} ({tier})"

                franchise = response.second_franchise.name
                gm_id = response.second_franchise.gm.discord_id

            case TransactionType.TEMP_FA | TransactionType.SUBSTITUTION:
                author_icon = await self.franchise_logo(
                    guild, response.second_franchise.id
                )

                tier = ptu_in.new_team.tier

                author_fmt = f"{ptu_in.player.player.name} has been signed to a temporary contract by {ptu_in.new_team.name} ({tier})"

                franchise = response.second_franchise.name

            case TransactionType.RETIRE:
                if guild.icon:
                    author_icon = guild.icon.url

                author_fmt = f"{ptu_in.player.player.name} has retired from the league"

                if response.first_franchise:
                    franchise = response.first_franchise.name
                    gm_id = response.first_franchise.gm.discord_id

            case TransactionType.INACTIVE_RESERVE:
                author_icon = await self.franchise_logo(
                    guild, response.first_franchise.id
                )

                tier = ptu_in.old_team.tier

                author_fmt = f"{ptu_in.player.player.name} has been moved to Inactive Reserve by {ptu_in.old_team.name} ({tier})"

                franchise = response.first_franchise.name
                gm_id = response.first_franchise.gm.discord_id

            case TransactionType.IR_RETURN:
                author_icon = await self.franchise_logo(
                    guild, response.first_franchise.id
                )

                tier = ptu_in.old_team.tier

                author_fmt = f"{ptu_in.player.player.name} has been removed from Inactive Reserve by {ptu_in.old_team.name} ({tier})"

                franchise = response.first_franchise.name
                gm_id = response.first_franchise.gm.discord_id

            case _:
                raise NotImplemented

        # Player Fields
        if player_out:
            embed.add_field(name="Player In", value=player_in.mention, inline=True)
            embed.add_field(name="Player Out", value=player_out.mention, inline=True)
        else:
            embed.add_field(name="Player", value=player_in.mention, inline=True)

        # Franchise Field
        if franchise:
            embed.add_field(name="Franchise", value=franchise, inline=True)

        # GM Field
        if gm_id:
            embed.add_field(
                name="GM",
                value=f"<@{gm_id}>",
                inline=True,
            )

        if isinstance(author_icon, discord.File):
            icon_url = f"attachment://{author_icon.filename}"
        elif isinstance(author_icon, str):
            icon_url = author_icon

        embed.set_author(name=author_fmt, icon_url=icon_url or None)

        if tier:
            color = await utils.tier_color_by_name(guild, tier)
        else:
            color = discord.Color.blue()

        embed.color = color
        return embed, files

    async def send_cut_msg(
        self, guild: discord.Guild, player: discord.Member
    ) -> discord.Message | None:
        dm_status = await self._trans_dms_enabled(guild)

        if not dm_status:
            return None

        cutmsg = await self._get_cut_message(guild)
        if not cutmsg:
            return None

        embed = BlueEmbed(title=f"Message from {guild.name}", description=cutmsg)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        return await player.send(embed=embed)

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

    async def announce_to_transaction_committee(
        self, guild: discord.Guild, **kwargs
    ) -> discord.Message | None:
        channel = await self._trans_log_channel(guild)
        if not channel or not hasattr(channel, "send"):
            return None

        trole = await self._trans_role(guild)
        if not trole:
            return None

        log.debug(f"Announcing to {channel.name}")
        content = kwargs.pop("content", trole.mention)
        return await channel.send(
            content=content,
            allowed_mentions=discord.AllowedMentions(users=True, roles=True),
            **kwargs,
        )

    async def announce_to_franchise_transactions(
        self, guild: discord.Guild, franchise: str, gm: discord.Member | int, **kwargs
    ) -> discord.Message | None:
        channel_name = f"{franchise.lower().replace(' ', '-')}-transactions"
        channel = discord.utils.get(guild.text_channels, name=channel_name)
        if not channel:
            logchan = await self._trans_log_channel(guild)
            if logchan and hasattr(logchan, "send"):
                await logchan.send(
                    embed=ErrorEmbed(
                        description=f"Unable to find franchise transaction channel: **{channel_name}**"
                    )
                )
            return None

        content = None
        if isinstance(gm, discord.Member):
            content = gm.mention

        if isinstance(gm, int):
            content = f"<@{gm}>"

        log.debug(f"Announcing to {channel.name}")
        return await channel.send(
            content=content,
            allowed_mentions=discord.AllowedMentions(users=True, roles=True),
            **kwargs,
        )

    # API

    async def sign(
        self,
        guild: discord.Guild,
        player: discord.Member,
        team: str,
        executor: discord.Member,
        notes: str | None = None,
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
                notes=notes,
                admin_override=override,
            )
            log.debug(f"[{guild.name}] Sign Parameters: {data}")
            try:
                return await api.transactions_sign_create(data)
            except ApiException as exc:
                raise await translate_api_error(exc)

    async def cut(
        self,
        guild: discord.Guild,
        player: discord.Member,
        executor: discord.Member,
        notes: str | None = None,
        override: bool = False,
    ) -> TransactionResponse:
        """Cut a player from their team"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TransactionsApi(client)
            data = CutAPlayerFromALeague(
                player=player.id,
                league=self._league[guild.id],
                executor=executor.id,
                notes=notes,
                admin_override=override,
            )
            log.debug(f"[{guild.name}] Cut Parameters: {data}")
            try:
                return await api.transactions_cut_create(data)
            except ApiException as exc:
                raise await translate_api_error(exc)

    async def resign(
        self,
        guild: discord.Guild,
        player: discord.Member,
        team: str,
        executor: discord.Member,
        notes: str | None = None,
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
                notes=notes,
                admin_override=override,
            )
            log.debug(f"[{guild.name}] Resign Parameters: {data}")
            try:
                return await api.transactions_resign_create(data)
            except ApiException as exc:
                raise await translate_api_error(exc)

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
        notes: str | None = None,
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

    async def retire(
        self,
        guild: discord.Guild,
        player: discord.Member,
        executor: discord.Member,
        notes: str | None = None,
        override: bool = False,
    ) -> TransactionResponse:
        """Retire a player from the league"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TransactionsApi(client)
            data = RetireAPlayer(
                league=self._league[guild.id],
                player=player.id,
                executor=executor.id,
                notes=notes,
                admin_override=override,
            )
            log.debug(f"Retire Data: {data}")
            try:
                return await api.transactions_retire_create(data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def inactive_reserve(
        self,
        guild: discord.Guild,
        player: discord.Member,
        executor: discord.Member,
        notes: str | None = None,
        override: bool = False,
        remove: bool = False,
    ) -> TransactionResponse:
        """Move a player or AGM to inactive reserve"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TransactionsApi(client)
            data = InactiveReserve(
                league=self._league[guild.id],
                player=player.id,
                executor=executor.id,
                notes=notes,
                admin_override=override,
                remove_from_ir=remove,
            )
            log.debug(f"IR Data: {data}")
            try:
                return await api.transactions_inactive_reserve_create(data)
            except ApiException as exc:
                raise RscException(response=exc)

    # Config

    async def _trans_role(self, guild: discord.Guild) -> discord.Role | None:
        trans_role_id = await self.config.custom("Transactions", guild.id).TransRole()
        return guild.get_role(trans_role_id)

    async def _save_trans_role(self, guild: discord.Guild, trans_role_id: int | None):
        await self.config.custom("Transactions", guild.id).TransRole.set(trans_role_id)

    async def _trans_channel(
        self, guild: discord.Guild
    ) -> discord.abc.GuildChannel | None:
        trans_channel_id = await self.config.custom(
            "Transactions", guild.id
        ).TransChannel()
        if not trans_channel_id:
            return None
        return guild.get_channel(trans_channel_id)

    async def _save_trans_channel(
        self, guild: discord.Guild, trans_channel: int | None
    ):
        await self.config.custom("Transactions", guild.id).TransChannel.set(
            trans_channel
        )

    async def _trans_log_channel(
        self, guild: discord.Guild
    ) -> discord.abc.GuildChannel | None:
        log_channel_id = await self.config.custom(
            "Transactions", guild.id
        ).TransLogChannel()
        if not log_channel_id:
            return None
        return guild.get_channel(log_channel_id)

    async def _save_trans_log_channel(
        self, guild: discord.Guild, trans_log_channel: int | None
    ):
        await self.config.custom("Transactions", guild.id).TransLogChannel.set(
            trans_log_channel
        )

    async def _get_cut_message(self, guild: discord.Guild) -> str | None:
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

    async def _get_substitutes(self, guild: discord.Guild) -> list[Substitute]:
        return await self.config.custom("Transactions", guild.id).Substitutes()

    async def _set_substitutes(self, guild: discord.Guild, subs: list[Substitute]):
        await self.config.custom("Transactions", guild.id).Substitutes.set(subs)

    async def _add_substitute(self, guild: discord.Guild, sub: Substitute):
        s = await self.config.custom("Transactions", guild.id).Substitutes()
        s.append(sub)
        await self._set_substitutes(guild, s)

    async def _rm_substitute(self, guild: discord.Guild, sub: Substitute):
        s = await self.config.custom("Transactions", guild.id).Substitutes()
        try:
            s.remove(sub)
        except ValueError:
            return
        await self._set_substitutes(guild, s)
