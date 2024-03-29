import logging
import re
from datetime import datetime, time, timedelta
from pathlib import Path

import discord
from discord.ext import tasks
from redbot.core import app_commands, commands
from rscapi import ApiClient, LeaguePlayersApi, TransactionsApi
from rscapi.exceptions import ApiException
from rscapi.models.cut_a_player_from_a_league import CutAPlayerFromALeague
from rscapi.models.draft_pick import DraftPick
from rscapi.models.expire_a_player_sub import ExpireAPlayerSub
from rscapi.models.franchise_identifier import FranchiseIdentifier
from rscapi.models.inactive_reserve import InactiveReserve
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.player1 import Player1
from rscapi.models.player_transaction_updates import PlayerTransactionUpdates
from rscapi.models.re_sign_player import ReSignPlayer
from rscapi.models.retire_a_player import RetireAPlayer
from rscapi.models.sign_a_player_to_a_team_in_a_league import (
    SignAPlayerToATeamInALeague,
)
from rscapi.models.temporary_fa_sub import TemporaryFASub
from rscapi.models.trade_item import TradeItem

# from rscapi.models.trade_schema import TradeSchema
from rscapi.models.trade_value import TradeValue
from rscapi.models.transaction_response import TransactionResponse

from rsc.abc import RSCMixIn

# from rsc.const import GM_ROLE
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    BlueEmbed,
    ErrorEmbed,
    ExceptionErrorEmbed,
    SuccessEmbed,
)
from rsc.enums import Status, TransactionType
from rsc.exceptions import (
    MalformedTransactionResponse,
    RscException,
    TradeParserException,
    translate_api_error,
)
from rsc.teams import TeamMixIn
from rsc.transactions.views import TradeAnnouncementModal
from rsc.types import Substitute, TransactionSettings
from rsc.utils import utils

log = logging.getLogger("red.rsc.transactions")

PICK_TRADE_REGEX = re.compile(
    r"^(?P<gm>[a-z0-9\x20]+)?(?:'s\s+)?(?P<round>\d)(?:st|nd|rd|th)\s+Round\s+(?P<tier>\w+)\s+\((?P<pick>\d{1,2})\)$",
    re.IGNORECASE,
)
FUTURE_TRADE_REGEX = re.compile(
    r"^(?P<gm>[a-z0-9\x20]+)'s\s+S(?P<season>\d+)\s+(?P<round>\d)(?:st|nd|rd|th)\s+Round\s+(?P<tier>\w+)$",
    re.IGNORECASE,
)
GM_TRADE_REGEX = re.compile(r"^(?P<gm>[a-z0-9\x20]+) receives:$", re.IGNORECASE)
PLAYER_TRADE_REGEX = re.compile(
    r"^@(?P<player>[a-z0-9\x20]+?)(?:\sto\s(?P<team>[a-z0-9\x20]+))?$", re.IGNORECASE
)

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
        log.info("Expire sub contracts loop started")
        for guild in self.bot.guilds:
            log.info(f"[{guild.name}] Expire sub contract loop is running")
            subs: list[Substitute] = await self._get_substitutes(guild)
            if not subs:
                log.debug(f"No substitutes to expire in {guild.name}")
                continue

            tchan = await self._trans_channel(guild)
            if not tchan or not hasattr(tchan, "send"):
                # Still need to remove player from sub list after.
                log.warning(
                    f"Substitutes found but transaction channel not set in {guild.name}"
                )

            subbed_out_role = await utils.get_subbed_out_role(guild)

            guild_tz = await self.timezone(guild)
            yesterday = datetime.now(guild_tz) - timedelta(1)

            # Get ContractExpired image
            img_path = (
                Path(__file__).parent.parent
                / "resources/transactions/ContractExpired.png"
            )

            # Loop through checkins.
            log.debug(f"Total substitute count: {len(subs)}")
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

                    m_in_fmt = m_in.mention if m_in else f"<@{s['player_in']}>"
                    m_out_fmt = m_out.mention if m_out else f"<@{s['player_out']}>"

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

                    embed.add_field(
                        name="Player In",
                        value=m_out_fmt,
                        inline=True,
                    )
                    embed.add_field(
                        name="Player Out",
                        value=m_in_fmt,
                        inline=True,
                    )
                    embed.add_field(name="Franchise", value=s["franchise"], inline=True)

                    # Send ping for player/GM then quickly remove it
                    if tchan and hasattr(tchan, "send"):
                        pingstr = f"<@{s['player_in']}> <@{s['gm']}>"
                        tmsg = await tchan.send(
                            content=pingstr,
                            embed=embed,
                            files=dFiles,
                            allowed_mentions=discord.AllowedMentions(users=True),
                        )
                        await tmsg.edit(content=None, embed=embed)

                    await self._rm_substitute(guild, s)
                    if subbed_out_role and m_out:
                        await m_out.remove_roles(subbed_out_role)
                else:
                    log.debug(
                        f"{s['player_in']} is not ready to be expired. Sub Date: {s['date']}"
                    )
        log.info("Finished expire substitute daily loop.")

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
                (
                    f"[{guild.name}] {member.display_name} ({member.id}) has left the server but is not on a team."
                    " No action taken."
                )
            )
            return

        # Check if user was forcibly removed from server
        perp, reason = await utils.get_audit_log_reason(
            member.guild, member, discord.AuditLogAction.kick
        )

        p = players.pop(0)
        log.info(
            (
                f"[{guild.name}] {member.display_name} ({member.id}) has left the server."
                f" Player is being retired. Reason: {reason}"
            )
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

        if not (p.team and p.team.franchise):
            log.info(f"{member.display_name} has no team. Skipping notifications...")
            return

        fname = p.team.franchise.name or "**Unknown Franchise**"
        gm_id = p.team.franchise.gm.discord_id

        match p.status:
            case Status.ROSTERED | Status.IR | Status.AGMIR:
                desc = f"Player left server while rostered on **{fname}**"
            case Status.UNSIGNED_GM:
                desc = "A general manager has left the server."
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
            franchise=fname,
            gm=gm_id,
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

    @_transactions.command(  # type: ignore
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

    @_transactions.command(  # type: ignore
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

    @_transactions.command(  # type: ignore
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

    @_transactions.command(  # type: ignore
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

    @_transactions.command(  # type: ignore
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

    @_transactions.command(  # type: ignore
        name="role", description="Configure the transaction committee role"
    )
    @app_commands.describe(role="Transaction committee discord role")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _transactions_role(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        if not interaction.guild:
            return
        await self._save_trans_role(interaction.guild, role.id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"Transaction committee role configured to {role.mention}",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_transactions.command(  # type: ignore
        name="cutmsg", description="Configure the player cut message"
    )
    @app_commands.describe(msg="Cut message string")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _transactions_cutmsg(self, interaction: discord.Interaction, *, msg: str):
        """Set cut message (4096 characters max)"""
        if not interaction.guild:
            return

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

    @_transactions.command(name="cut", description="Release a player from their team")  # type: ignore
    @app_commands.describe(
        player="Player to cut",
        notes="Transaction notes (Optional)",
        override="Admin only override",
    )
    async def _transactions_cut(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        notes: str | None = None,
        override: bool = False,
    ):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        if override and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Only admins can process an override.")
            )
            return

        # Defer
        await interaction.response.defer(ephemeral=True)

        try:
            result = await self.cut(
                guild,
                player=player,
                executor=interaction.user,
                notes=notes,
                override=override,
            )
            log.debug(f"Cut Result: {result}")
        except RscException as exc:
            log.warning(f"[{guild.name}] Transaction Exception: {exc.reason}")
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return

        ptu = await self.league_player_from_transaction(result, player=player)

        if not ptu.old_team:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=(
                        "Player was cut but the API did not return any information on previous team. "
                        "Please reach out to modmail.\n\n"
                        "**Roles and names were not modified**"
                    )
                )
            )

        if not ptu.player.tier or not ptu.player.tier.name:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=(
                        "Player was cut but the API did not return any tier information. "
                        "Please reach out to modmail.\n\n"
                        "**Roles and names were not modified**"
                    )
                )
            )

        # Update tier role, handle promotion case
        log.debug(f"[{guild.name}] Updating tier roles for {player.id}")
        old_tier_role = await utils.get_tier_role(guild, ptu.old_team.tier)
        tier_role = await utils.get_tier_role(guild, ptu.player.tier.name)
        if old_tier_role != tier_role:
            await player.remove_roles(old_tier_role)
            await player.add_roles(tier_role)

        # Apply tier role if they never had it
        if tier_role not in player.roles:
            await player.add_roles(tier_role)

        # Free agent roles
        fa_role = await utils.get_free_agent_role(guild)
        tier_fa_role = await utils.get_tier_fa_role(guild, ptu.player.tier.name)

        if not result.first_franchise:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=(
                        "Player was cut but the API did not return first/second franchise data. "
                        "Please reach out to modmail.\n\n"
                        "**Roles and names were not modified**"
                    )
                )
            )

        # Franchise Role
        franchise_role = await utils.franchise_role_from_name(
            guild, result.first_franchise.name
        )
        if not franchise_role:
            log.error(
                f"[{guild.name}] Unable to find franchise name during cut: {result.first_franchise.name}"
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
            guild=guild,
            response=result,
            player_in=player,
        )

        # Announce to transaction channel
        await self.announce_transaction(
            guild,
            embed=embed,
            files=files,
            player=player,
            gm=result.first_franchise.gm.discord_id,
        )

        # Send cut message to user directly
        await self.send_cut_msg(guild, player=player)

        # Send result
        await interaction.followup.send(
            embed=SuccessEmbed(
                description=f"{player.mention} has been released to the Free Agent pool."
            ),
            ephemeral=True,
        )

    @_transactions.command(  # type: ignore
        name="sign", description="Sign a player to the specified team"
    )
    @app_commands.describe(
        player="Player to sign",
        team="Team the player is being sign on",
        notes="Transaction notes (Optional)",
        override="Admin only override",
    )
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)  # type: ignore
    async def _transactions_sign(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        team: str,
        notes: str | None = None,
        override: bool = False,
    ):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        if override and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Only admins can process an override.")
            )
            return

        # Sign player
        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.sign(
                guild,
                player=player,
                team=team,
                executor=interaction.user,
                notes=notes,
                override=override,
            )
            log.debug(f"[{guild.name}] Sign Result: {result}]")
        except RscException as exc:
            log.warning(f"[{guild.name}] Transaction Exception: {exc.reason}")
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return

        ptu: PlayerTransactionUpdates = await self.league_player_from_transaction(
            result, player=player
        )

        if not ptu.player.tier or not ptu.player.tier.name:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=(
                        "Player was cut but the API did not return any tier information. "
                        "Please reach out to modmail.\n\n"
                        "**Roles and names were not modified**"
                    )
                )
            )

        # Remove FA roles
        log.debug(f"[{guild.name}] Removing FA roles from {player.id}")
        fa_role = await utils.get_free_agent_role(guild)
        tier_fa_role = await utils.get_tier_fa_role(guild, ptu.player.tier.name)
        await player.remove_roles(fa_role, tier_fa_role)

        # Add franchise role
        log.debug(f"[{guild.name}] Adding franchise role to {player.id}")
        frole = await utils.franchise_role_from_league_player(guild, ptu.player)

        # Verify player has tier role
        log.debug(f"[{guild.name}] Adding tier role to {player.id}")
        tier_role = await utils.get_tier_role(guild, name=ptu.new_team.tier)
        await player.add_roles(frole, tier_role)

        # Change member prefix
        new_nick = (
            f"{ptu.player.team.franchise.prefix} | {await utils.remove_prefix(player)}"
        )
        log.debug(f"[{guild.name}] Changing signed player nick to {player.id}")
        try:
            await player.edit(nick=new_nick)
        except discord.Forbidden:
            log.warning(f"Forbidden to change name of {player.display_name}")
            pass

        embed, files = await self.build_transaction_embed(
            guild=guild, response=result, player_in=player
        )

        await self.announce_transaction(
            guild=guild,
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

    @_transactions.command(name="resign", description="Re-sign a player to their team.")  # type: ignore
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)  # type: ignore
    @app_commands.describe(
        player="RSC Discord Member",
        team="Name of team player resigning player",
        notes="Transaction notes (Optional)",
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
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        if override and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Only admins can process an override.")
            )
            return

        await interaction.response.defer(ephemeral=True)
        # Process sign
        try:
            result = await self.resign(
                guild,
                player=player,
                team=team,
                executor=interaction.user,
                notes=notes,
                override=override,
            )
            log.debug(f"[{guild.name}] Re-sign Result: {result}]")
        except RscException as exc:
            log.warning(f"[{guild.name}] Transaction Exception: {exc.reason}")
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return

        ptu: PlayerTransactionUpdates = await self.league_player_from_transaction(
            result, player=player
        )

        # We check roles and name here just in case.
        # Remove FA roles
        log.debug(f"[{guild.name}] Removing FA roles from {player.id}")
        fa_role = await utils.get_free_agent_role(guild)
        tier_fa_role = await utils.get_tier_fa_role(guild, ptu.player.tier.name)
        await player.remove_roles(fa_role, tier_fa_role)

        # Add franchise role
        log.debug(f"[{guild.name}] Adding franchise role to {player.id}")
        frole = await utils.franchise_role_from_league_player(guild, ptu.player)

        # Verify player has tier role
        log.debug(f"[{guild.name}] Adding tier role to {player.id}")
        tier_role = await utils.get_tier_role(guild, name=ptu.new_team.tier)
        await player.add_roles(frole, tier_role)

        # Change member prefix
        new_nick = (
            f"{ptu.player.team.franchise.prefix} | {await utils.remove_prefix(player)}"
        )
        log.debug(f"[{guild.name}] Changing signed player nick to {player.id}")
        await player.edit(nick=new_nick)

        embed, files = await self.build_transaction_embed(
            guild=guild, response=result, player_in=player
        )

        await self.announce_transaction(
            guild=guild, embed=embed, files=files, player=player
        )

        # Send result
        await interaction.followup.send(
            embed=SuccessEmbed(
                description=f"{player.mention} has been re-signed to **{ptu.new_team.name}**"
            ),
            ephemeral=True,
        )

    @_transactions.command(name="sub", description="Substitute a player on a team")  # type: ignore
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
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)

        if override and not interaction.user.guild_permissions.manage_guild:
            await interaction.followup.send(
                embed=ErrorEmbed(description="Only admins can process an override.")
            )
            return

        try:
            result = await self.substitution(
                guild,
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

        embed, files = await self.build_transaction_embed(
            guild=guild,
            response=result,
            player_in=player_in,
            player_out=player_out,
        )

        await self.announce_transaction(
            guild=guild,
            embed=embed,
            files=files,
            player=player_in,
            gm=result.second_franchise.gm.discord_id,
        )

        # Save sub for expiration later
        tz = await self.timezone(guild)
        sub_obj = Substitute(
            date=str(datetime.now(tz)),
            player_in=player_in.id,
            player_out=player_out.id,
            team=ptu_in.new_team.name,
            gm=result.second_franchise.gm.discord_id,
            tier=ptu_in.new_team.tier,
            franchise=result.second_franchise.name,
        )
        await self._add_substitute(guild, sub_obj)

        # Subbed out role
        subbed_out_role = await utils.get_subbed_out_role(guild)
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

    @_transactions.command(  # type: ignore
        name="announce",
        description="Perform a generic announcement to the transactions channel.",
    )
    @app_commands.describe(
        message="Desired message to announce. Accepts discord member mentions."
    )
    async def _transactions_announce(
        self, interaction: discord.Interaction, message: str
    ):
        if not interaction.guild:
            return

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

    @_transactions.command(  # type: ignore
        name="announcetrade",
        description="Announce a trade between two franchises to the transaction chanenl",
    )
    async def _transactions_announcetrade(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        # await utils.not_implemented(interaction)
        # return

        trans_channel = await self._trans_channel(interaction.guild)
        if not trans_channel:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Transaction channel is not configured."),
                ephemeral=True,
            )
            return

        trade_modal = TradeAnnouncementModal()
        await interaction.response.send_modal(trade_modal)

        if not trade_modal.trade:
            await interaction.followup.send(
                content="No trade information provided... Try again.", ephemeral=True
            )
            return

        # log.debug(f"Trade Announcement: {trade.trade}")
        # await trans_channel.send(content=trade.trade, allowed_mentions=discord.AllowedMentions(users=True))
        # TODO - modal not working for this because mentions

    @_transactions.command(  # type: ignore
        name="trade",
        description="Process a trade between franchises",
    )
    @app_commands.describe(override="Admin only override")
    async def _transactions_trade_cmd(
        self, interaction: discord.Interaction, override: bool = False
    ):
        guild = interaction.guild
        if not guild:
            return

        trans_channel = await self._trans_channel(guild)
        if not trans_channel:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Transaction channel is not configured."),
                ephemeral=True,
            )
            return

        trade_modal = TradeAnnouncementModal()
        await interaction.response.send_modal(trade_modal)
        await trade_modal.wait()

        if not trade_modal.trade:
            await interaction.followup.send(
                content="No trade information provided... Try again.", ephemeral=True
            )
            return

        try:
            trade_items = await self.parse_trade_text(
                guild=guild, data=trade_modal.trade.value
            )
            log.debug(trade_items)

            embed = BlueEmbed(
                title="Debug Trades",
                description="Trade Overview",
            )

            players = []
            futures = []
            for x in trade_items:
                if x.value.player:
                    p = (
                        str(x.source.id),
                        str(x.destination.id),
                        str(x.value.player.id)[:8],
                        x.value.player.team,
                    )
                    players.append(p)
                else:
                    f = (
                        str(x.source.gm)[:8],
                        str(x.destination.id),
                        str(x.value.pick.round),
                        x.value.pick.tier,
                    )
                    futures.append(f)

            if players:
                embed.add_field(name="Player Trades", value="", inline=False)
                embed.add_field(
                    name="Source", value="\n".join([x[0] for x in players]), inline=True
                )
                embed.add_field(
                    name="Dest", value="\n".join([x[1] for x in players]), inline=True
                )
                embed.add_field(
                    name="Player", value="\n".join([x[2] for x in players]), inline=True
                )
                embed.add_field(
                    name="Team", value="\n".join([x[3] for x in players]), inline=True
                )

            if futures:
                embed.add_field(name="Draft Picks", value="", inline=False)
                embed.add_field(
                    name="Source", value="\n".join([x[0] for x in futures]), inline=True
                )
                embed.add_field(
                    name="Dest", value="\n".join([x[1] for x in futures]), inline=True
                )
                embed.add_field(
                    name="Round", value="\n".join([x[2] for x in futures]), inline=True
                )
                embed.add_field(
                    name="Tier", value="\n".join([x[3] for x in futures]), inline=True
                )
            await interaction.followup.send(embed=embed, ephemeral=False)
        except TradeParserException as exc:
            await interaction.followup.send(
                embed=ExceptionErrorEmbed(
                    title="Trade Parsing Error", exc_message=exc.message
                ),
                ephemeral=True,
            )
            return

    @_transactions.command(  # type: ignore
        name="captain",
        description="Promote a player to captain of their team",
    )
    @app_commands.describe(player="RSC Discord Member")
    async def _transactions_captain(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        player1: discord.Member | None = None,
        player2: discord.Member | None = None,
        player3: discord.Member | None = None,
        player4: discord.Member | None = None,
        player5: discord.Member | None = None,
        player6: discord.Member | None = None,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        argv = locals()
        captains: list[discord.Member] = []

        log.debug(f"Locals: {argv}")
        for k, v in argv.items():
            if v and k.startswith("player"):
                captains.append(v)
        log.debug(f"Captain Count: {len(captains)}")

        # Get Captain Role
        cpt_role = await utils.get_captain_role(guild)
        if not cpt_role:
            await interaction.followup.send(
                embed=ErrorEmbed(description="Captain role does not exist in guild.")
            )
            return

        # Get team of player being made captain
        player_list = await self.players(guild, discord_id=player.id, limit=1)

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
        team_players = await self.team_players(guild, player_data.team.id)

        # Remove captain role from anyone on the team that has it just in case
        alreadyCaptain = False
        for p in team_players:
            m = guild.get_member(p.discord_id)

            if not m:
                log.error(
                    f"[{guild.name}] Unable to find rostered player in guild: {p.discord_id}"
                )
                continue

            if m.id == player.id and p.captain:
                log.debug(
                    f"{player.display_name} is already captain. Removing captain status"
                )
                alreadyCaptain = True
            log.debug(f"Removing captain role from: {m.display_name}")
            await m.remove_roles(cpt_role)

        # Promote new player to captain or flip captain flag off.
        await self.set_captain(guild, player_data.id)

        # If player was already captain, they are being removed.
        if alreadyCaptain:
            embed = SuccessEmbed(
                title="Captain Removed",
                description=f"{player.mention} has been removed as **captain**",
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Add captain role
        await player.add_roles(cpt_role)

        # Announce to transaction channel
        trans_channel = await self._trans_channel(guild)
        if trans_channel:
            str_fmt = (
                f"{player.mention} was elected captain of {player_data.team.name}"
                f" (<@{player_data.team.franchise.gm.discord_id}> - {player_data.tier.name})"
            )
            await trans_channel.send(
                content=str_fmt,
                allowed_mentions=discord.AllowedMentions(users=True),
            )

        # Send Result
        embed = SuccessEmbed(
            title="Captain Designated",
            description=f"{player.mention} has been promoted to **captain**",
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @_transactions.command(  # type: ignore
        name="expire",
        description="Manually expire a temporary FA contract",
    )
    @app_commands.describe(player="RSC Discord Member")
    async def _transactions_expire(
        self, interaction: discord.Interaction, player: discord.Member
    ):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.expire_sub(
                guild,
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
            subbed_out_role = await utils.get_subbed_out_role(guild)
            m_out = guild.get_member(p_out)
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
            tier_color = await utils.tier_color_by_name(guild, stier)

            # Post to transactions
            tchan = await self._trans_channel(guild)
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
            await self._rm_substitute(guild, sub_obj)

        await interaction.followup.send(
            embed=SuccessEmbed(
                description=f"The temporary FA contract for {player.mention} has been expired."
            ),
            ephemeral=True,
        )

    @_transactions.command(  # type: ignore
        name="sublist",
        description="Fetch a list of all players with a temporary FA contract",
    )
    async def _transactions_sublist(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

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

    @_transactions.command(  # type: ignore
        name="ir",
        description="Modify inactive reserve status of a player",
    )
    @app_commands.describe(
        action="Inactive Reserve Action",
        player="RSC Discord Member",
        notes="Transaction notes (Optional)",
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
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        if override and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Only admins can process an override.")
            )
            return
        await interaction.response.defer(ephemeral=True)

        remove = bool(action.value)
        log.debug(f"Remove from IR: {remove}")

        try:
            result = await self.inactive_reserve(
                guild,
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
        ir_role = await utils.get_ir_role(guild)

        if ir_role:
            if remove:
                await player.remove_roles(ir_role)
            else:
                await player.add_roles(ir_role)

        embed, files = await self.build_transaction_embed(
            guild=guild, response=result, player_in=player
        )

        await self.announce_transaction(
            guild=guild,
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

    @_transactions.command(name="retire", description="Retire a player from the league")  # type: ignore
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
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        if override and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Only admins can process an override.")
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.retire(
                guild,
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
        fname = None
        if result.first_franchise:
            fname = result.first_franchise.name

        # Roles
        old_tier_role = None
        franchise_role = None
        league_role = await utils.get_league_role(guild)
        if fname:
            franchise_role = await utils.franchise_role_from_name(guild, fname)
        if ptu.old_team:
            old_tier_role = await utils.get_tier_role(guild, ptu.old_team.tier)

        roles_to_remove = []

        if old_tier_role:
            roles_to_remove.append(old_tier_role)

        if league_role:
            roles_to_remove.append(league_role)

        if franchise_role:
            roles_to_remove.append(franchise_role)

        if roles_to_remove:
            await player.remove_roles(*roles_to_remove)

        spectator_role = await utils.get_spectator_role(guild)
        if spectator_role:
            await player.add_roles(spectator_role)

        embed, files = await self.build_transaction_embed(
            guild=guild, response=result, player_in=player
        )

        await self.announce_transaction(
            guild=guild, embed=embed, files=files, player=player
        )

        # Send result
        await interaction.followup.send(
            embed=SuccessEmbed(
                description=f"{player.mention} has been retired from the league."
            ),
            ephemeral=True,
        )

    @_transactions.command(  # type: ignore
        name="clearsublist", description="Clear cached substitute list"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _transactions_clear_sub_list(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        await self._set_substitutes(interaction.guild, subs=[])
        await interaction.response.send_message(
            "Locally cached substitute list has been cleared.", ephemeral=True
        )

    @_transactions.command(name="history", description="Fetch transaction history")  # type: ignore
    @app_commands.describe(
        player="RSC Discord Member (Optional)",
        executor="Transaction Executor (Optional)",
        season='RSC Season Number. Example: "19" (Optional)',
        type="Transaction Type (Optional)",
    )
    async def _transactions_history_cmd(
        self,
        interaction: discord.Interaction,
        player: discord.Member | None = None,
        executor: discord.Member | None = None,
        season: int | None = None,
        type: TransactionType | None = None,
    ):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.transaction_history(
                guild, player=player, executor=executor, season=season, trans_type=type
            )
            log.debug(f"Transaction History Result: {result}")
        except RscException as exc:
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return

    # Functions

    async def announce_transaction(
        self,
        guild: discord.Guild,
        embed: discord.Embed,
        files: list[discord.File] | None = None,
        player: discord.Member | int | None = None,
        gm: discord.Member | int | None = None,
    ) -> discord.Message | None:
        if files is None:
            files = []
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

        # Locals
        author_fmt = "Generic Transaction"
        author_icon: discord.File | str | None = None
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
                if not (ptu_in.old_team and response.first_franchise):
                    raise MalformedTransactionResponse
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
                if not (ptu_in.new_team and response.second_franchise):
                    raise MalformedTransactionResponse
                author_icon = await self.franchise_logo(
                    guild, response.second_franchise.id
                )

                tier = ptu_in.new_team.tier

                author_fmt = f"{ptu_in.player.player.name} has been signed by {ptu_in.new_team.name} ({tier})"

                franchise = response.second_franchise.name
                gm_id = response.second_franchise.gm.discord_id

            case TransactionType.RESIGN:
                if not (ptu_in.new_team and response.second_franchise):
                    raise MalformedTransactionResponse
                author_icon = await self.franchise_logo(
                    guild, response.second_franchise.id
                )

                tier = ptu_in.new_team.tier

                author_fmt = f"{ptu_in.player.player.name} has been re-signed by {ptu_in.new_team.name} ({tier})"

                franchise = response.second_franchise.name
                gm_id = response.second_franchise.gm.discord_id

            case TransactionType.TEMP_FA | TransactionType.SUBSTITUTION:
                if not (ptu_in.new_team and response.second_franchise):
                    raise MalformedTransactionResponse
                author_icon = await self.franchise_logo(
                    guild, response.second_franchise.id
                )

                tier = ptu_in.new_team.tier
                pname = ptu_in.player.player.name
                pteam = ptu_in.new_team.name

                author_fmt = f"{pname} has been signed to a temporary contract by {pteam} ({tier})"

                franchise = response.second_franchise.name

            case TransactionType.RETIRE:
                if guild.icon:
                    author_icon = guild.icon.url

                author_fmt = f"{ptu_in.player.player.name} has retired from the league"

                if response.first_franchise:
                    franchise = response.first_franchise.name
                    gm_id = response.first_franchise.gm.discord_id

            case TransactionType.INACTIVE_RESERVE:
                if not (ptu_in.old_team and response.first_franchise):
                    raise MalformedTransactionResponse
                author_icon = await self.franchise_logo(
                    guild, response.first_franchise.id
                )

                tier = ptu_in.old_team.tier
                pname = ptu_in.player.player.name
                pteam = ptu_in.old_team.name

                author_fmt = (
                    f"{pname} has been moved to Inactive Reserve by {pteam} ({tier})"
                )

                franchise = response.first_franchise.name
                gm_id = response.first_franchise.gm.discord_id

            case TransactionType.IR_RETURN:
                if not (ptu_in.old_team and response.first_franchise):
                    raise MalformedTransactionResponse
                author_icon = await self.franchise_logo(
                    guild, response.first_franchise.id
                )

                tier = ptu_in.old_team.tier
                pname = ptu_in.player.player.name
                pteam = ptu_in.old_team.name

                author_fmt = f"{pname} has been removed from Inactive Reserve by {pteam} ({tier})"

                franchise = response.first_franchise.name
                gm_id = response.first_franchise.gm.discord_id

            case _:
                raise NotImplementedError

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

        embed.colour = color
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
        if not transaction.player_updates:
            raise ValueError("Transaction response contains no Player Updates.")

        lp = next(
            (
                x
                for x in transaction.player_updates
                if x.player.player.discord_id == player.id
            )
        )
        return lp

    async def get_sub(self, member: discord.Member) -> Substitute | None:
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

    async def parse_trade_text(
        self, guild: discord.Guild, data: str
    ) -> list[TradeItem]:
        if not data:
            raise TradeParserException(message="No trade data provided...")

        try:
            league_role = await utils.get_league_role(guild=guild)
            gm_role = await utils.get_gm_role(guild=guild)
        except ValueError as exc:
            raise TradeParserException(message=exc.args[0])

        from pprint import pformat

        # Iterate once to get all franchises involved
        log.debug("Finding all franchises in trade.")
        franchises = []
        for line in data.splitlines():
            line = line.strip()
            log.debug(f"Line: {line}")

            if match := GM_TRADE_REGEX.search(line):
                if not match.group("gm"):
                    raise TradeParserException(
                        message=f"Unable to parse GM name from: {line}"
                    )

                gm_str = match.group("gm").strip()
                log.debug(f"GM str: {gm_str}")

                # Find name in GM role members
                for m in gm_role.members:
                    tmp = await utils.remove_prefix(m)
                    if tmp.lower().startswith(gm_str.lower()):
                        gm = m
                        break

                if not gm:
                    raise TradeParserException(
                        message=f"Unable to parse GM name from: {line}"
                    )
                log.debug(f"Trade GM: {gm.display_name}")

                # Get franchise from API
                fdata = await self.franchises(guild=guild, gm_name=tmp)
                if not fdata or len(fdata) > 1:
                    raise TradeParserException(
                        message=f"Error finding franchise for GM: {tmp}"
                    )

                fname = fdata[0].name
                fid = fdata[0].id
                log.debug(f"Franchise ID: {fid} Name: {fname} GM: {gm.id}")
                f_object = FranchiseIdentifier(gm=gm.id, name=fname, id=fid)
                franchises.append(f_object)
                continue

        # Initial validation on franchises
        if len(franchises) < 2:
            raise TradeParserException(
                "Unable to identify 2 or more franchises in trade."
            )

        trade_list = []
        dest_franchise = None
        log.debug("Parsing trades...")
        for line in data.splitlines():
            line = line.strip()
            log.debug(f"Line: {line}")

            # Skip line breaks
            if len(line) == 0:
                continue

            # New franchise data
            elif line.startswith("---"):
                log.debug("Trade line break. Resetting destination...")
                dest_franchise = None
                continue

            # Check for GM
            elif match := GM_TRADE_REGEX.search(line):
                if not match.group("gm"):
                    raise TradeParserException(
                        message=f"Unable to parse GM name from: {line}"
                    )

                gm_str = match.group("gm").strip()
                log.debug(f"GM str: {gm_str}")

                # Find name in GM role members
                for m in gm_role.members:
                    tmp = await utils.remove_prefix(m)
                    if tmp.lower().startswith(gm_str.lower()):
                        gm = m
                        break

                if not gm:
                    raise TradeParserException(
                        message=f"Unable to parse GM name from: {line}"
                    )
                log.debug(f"Trade GM: {gm.display_name}")

                # Get franchise from API
                dest_franchise = next((x for x in franchises if x.gm == gm.id), None)

                log.debug(f"Destination Franchise: {dest_franchise}")
                if not dest_franchise:
                    raise TradeParserException(
                        message=f"Error finding franchise for GM: {gm.display_name} ({gm.id})"
                    )
                continue

            # Player trade
            elif match := PLAYER_TRADE_REGEX.search(line):
                if not dest_franchise:
                    raise TradeParserException(
                        message="Destination franchise is `None`"
                    )

                # Parse line with regex
                if not match or not match.group("player"):
                    raise TradeParserException(
                        message=f"Unable to parse player trade from: {line}"
                    )

                m_str = match.group("player").strip()
                log.debug(f"Player str: {m_str}")
                player = discord.utils.get(league_role.members, display_name=m_str)

                if not player:
                    raise TradeParserException(
                        message=f"Unable to parse player from: `{m_str}`"
                    )

                # Get source franchise
                plist = await self.players(guild=guild, discord_id=player.id)

                if not plist:
                    raise TradeParserException(
                        message=f"Unable to find league player: {player.mention})"
                    )

                pdata = plist[0]

                if not pdata.team:
                    raise TradeParserException(
                        message=f"Player is not a team: {player.mention})"
                    )

                if not pdata.team.franchise:
                    raise TradeParserException(
                        message=f"API Error. No franchise id or name for player: {player.mention}"
                    )

                sf_id = pdata.team.franchise.id
                sf_name = pdata.team.franchise.name
                log.debug(f"Source. ID={sf_id} NAME={sf_name}")
                sfranchise = FranchiseIdentifier(id=sf_id, name=sf_name, gm=None)

                # Get destination team name (find by current tier)
                dest_team = None
                if match.group("team"):
                    dest_team = match.group("team").strip()
                else:
                    if not pdata.tier:
                        raise TradeParserException(
                            message=f"API Error. Player has no tier data: {player.mention}"
                        )

                    team_list = await self.teams(
                        guild=guild, franchise=dest_franchise.name, tier=pdata.tier.name
                    )

                    if not team_list or len(team_list) > 1:
                        raise TradeParserException(
                            message=f"Error finding destination team. Franchise: {dest_franchise.id} Tier: {pdata.tier.name}"
                        )

                    dest_team = team_list[0].name

                log.debug(f"Destination Team Name: {dest_team}")

                tvalue = TradeValue(player=Player1(id=player.id, team=dest_team))
                log.debug(tvalue)

                item = TradeItem(
                    source=sfranchise, destination=dest_franchise, value=tvalue
                )
                log.debug(pformat(item))

                trade_list.append(item)
            elif match := FUTURE_TRADE_REGEX.match(line):
                if not match:
                    raise TradeParserException(
                        message=f"Unable to parse future trade from: {line}"
                    )
                if not dest_franchise:
                    raise TradeParserException(
                        message="Destination franchise is `None`. Parser error."
                    )

                gm_str = match.group("gm").strip()
                tier = match.group("tier")
                # season = int(match.group("season"))
                round = int(match.group("round"))

                # Find name in GM role members
                source_gm = None
                for m in gm_role.members:
                    tmp = await utils.remove_prefix(m)
                    if tmp.lower().startswith(gm_str.lower()):
                        source_gm = m
                        break

                if not source_gm:
                    raise TradeParserException(
                        message=f"Error finding discord member for future source GM: `{gm_str}`"
                    )

                sfranchise = FranchiseIdentifier(id=None, name=None, gm=source_gm.id)

                tvalue = TradeValue(
                    pick=DraftPick(tier=tier, round=round, number=0, future=True)
                )
                log.debug(tvalue)

                item = TradeItem(
                    source=sfranchise, destination=dest_franchise, value=tvalue
                )
                log.debug(pformat(item))

                trade_list.append(item)

            elif match := PICK_TRADE_REGEX.match(line):
                if not match:
                    raise TradeParserException(
                        message=f"Unable to parse future trade from: {line}"
                    )
                if not dest_franchise:
                    raise TradeParserException(
                        message="Destination franchise is `None`. Parser error."
                    )

                tier = match.group("tier")
                round = int(match.group("round"))
                # pick = int(match.group("pick"))

                # Check if GM was provided (3+ way trade)
                gm_str = None
                source_gm = None
                if match.group("gm"):
                    gm_str = match.group("gm").strip()

                    # Find name in GM role members
                    source_gm = None
                    for m in gm_role.members:
                        tmp = await utils.remove_prefix(m)
                        if tmp.lower().startswith(gm_str.lower()):
                            source_gm = m
                            break

                # If no source gm, check if only two GMs involved
                raise NotImplementedError("uh what if this is in the first pick?")
                if not source_gm:
                    raise TradeParserException(
                        message=f"Error finding discord member for future source GM: `{gm_str}`"
                    )

                sfranchise = FranchiseIdentifier(id=None, name=None, gm=source_gm.id)

                tvalue = TradeValue(
                    pick=DraftPick(tier=tier, round=round, number=0, future=True)
                )
                log.debug(tvalue)

                item = TradeItem(
                    source=sfranchise, destination=dest_franchise, value=tvalue
                )
                log.debug(pformat(item))

                trade_list.append(item)

            else:
                raise TradeParserException(
                    message=f"Unknown line in trade data: {line}"
                )

        return trade_list

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

    async def transaction_history(
        self,
        guild: discord.Guild,
        player: discord.Member | None = None,
        executor: discord.Member | None = None,
        season: int | None = None,
        trans_type: TransactionType | None = None,
    ) -> list[TransactionResponse]:
        """Fetch transaction history based on specified criteria"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TransactionsApi(client)
            player_id = player.id if player else None
            executor_id = executor.id if executor else None
            log.debug(
                f"Transaction History Query. Player: {player_id} Executor: {executor_id} Season: {season} Type: {trans_type}"
            )
            try:
                return await api.transactions_history_list(
                    league=self._league[guild.id],
                    player=player_id,
                    executor=executor_id,
                    transaction_type=str(trans_type),
                    season_number=season,
                )
            except ApiException as exc:
                raise RscException(response=exc)

    # Config

    async def _trans_role(self, guild: discord.Guild) -> discord.Role | None:
        trans_role_id = await self.config.custom(
            "Transactions", str(guild.id)
        ).TransRole()
        return guild.get_role(trans_role_id)

    async def _save_trans_role(self, guild: discord.Guild, trans_role_id: int | None):
        await self.config.custom("Transactions", str(guild.id)).TransRole.set(
            trans_role_id
        )

    async def _trans_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        channel_id = await self.config.custom(
            "Transactions", str(guild.id)
        ).TransChannel()
        if not channel_id:
            return None
        c = guild.get_channel(channel_id)
        if not c or not isinstance(c, discord.TextChannel):
            return None
        return c

    async def _save_trans_channel(
        self, guild: discord.Guild, trans_channel: int | None
    ):
        await self.config.custom("Transactions", str(guild.id)).TransChannel.set(
            trans_channel
        )

    async def _trans_log_channel(
        self, guild: discord.Guild
    ) -> discord.TextChannel | None:
        channel_id = await self.config.custom(
            "Transactions", str(guild.id)
        ).TransLogChannel()
        if not channel_id:
            return None
        c = guild.get_channel(channel_id)
        if not c or not isinstance(c, discord.TextChannel):
            return None
        return c

    async def _save_trans_log_channel(
        self, guild: discord.Guild, trans_log_channel: int | None
    ):
        await self.config.custom("Transactions", str(guild.id)).TransLogChannel.set(
            trans_log_channel
        )

    async def _get_cut_message(self, guild: discord.Guild) -> str | None:
        return await self.config.custom("Transactions", str(guild.id)).CutMessage()

    async def _save_cut_message(self, guild: discord.Guild, message):
        await self.config.custom("Transactions", str(guild.id)).CutMessage.set(message)

    async def _notifications_enabled(self, guild: discord.Guild) -> bool:
        return await self.config.custom(
            "Transactions", str(guild.id)
        ).TransNotifications()

    async def _set_notifications(self, guild: discord.Guild, enabled: bool):
        await self.config.custom("Transactions", str(guild.id)).TransNotifications.set(
            enabled
        )

    async def _trans_dms_enabled(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Transactions", str(guild.id)).TransDMs()

    async def _set_trans_dm(self, guild: discord.Guild, enabled: bool):
        await self.config.custom("Transactions", str(guild.id)).TransDMs.set(enabled)

    async def _get_substitutes(self, guild: discord.Guild) -> list[Substitute]:
        return await self.config.custom("Transactions", str(guild.id)).Substitutes()

    async def _set_substitutes(self, guild: discord.Guild, subs: list[Substitute]):
        await self.config.custom("Transactions", str(guild.id)).Substitutes.set(subs)

    async def _add_substitute(self, guild: discord.Guild, sub: Substitute):
        s = await self.config.custom("Transactions", str(guild.id)).Substitutes()
        s.append(sub)
        await self._set_substitutes(guild, s)

    async def _rm_substitute(self, guild: discord.Guild, sub: Substitute):
        s = await self.config.custom("Transactions", str(guild.id)).Substitutes()
        try:
            s.remove(sub)
        except ValueError:
            return
        await self._set_substitutes(guild, s)
