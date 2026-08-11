import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import discord
from redbot.core import app_commands
from redbot.core.app_commands import Transform

from rsc.abc import RSCMixIn
from rsc.admin.modals import BulkRetireModal, LeagueDatesModal
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    BlueEmbed,
    ErrorEmbed,
    ExceptionErrorEmbed,
    GreenEmbed,
    OrangeEmbed,
    SuccessEmbed,
    YellowEmbed,
)
from rsc.exceptions import MalformedTransactionResponse, RscException
from rsc.logs import GuildLogAdapter
from rsc.transactions.roles import update_nonplaying_discord
from rsc.transformers import DateTransformer
from rsc.types import AdminSettings

if TYPE_CHECKING:
    from rsc.transactions import TransactionMixIn

logger = logging.getLogger("red.rsc.admin")
log = GuildLogAdapter(logger)

defaults_guild = AdminSettings(
    ActivityCheckMissingRole=None,
    ActivityCheckMsgId=None,
    AgmMessage=None,
    Dates=None,
    IntentChannel=None,
    IntentMissingRole=None,
    IntentMissingMsg=None,
    IntentDmLastSeason=None,
    IntentDmLastRun=None,
    IntentDmLastExecutor=None,
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

    @_admin.command(name="settings", description="Display RSC Admin settings.")
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

    @_admin.command(name="dates", description="Configure the dates command output")
    async def _admin_set_dates(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        dates_modal = LeagueDatesModal()
        await interaction.response.send_modal(dates_modal)
        await dates_modal.wait()

        await self._set_dates(interaction.guild, value=dates_modal.date_input.value)

    @_admin.command(name="dmstatus", description="Check the status of the bot DM queue")
    async def _admin_dmstatus_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        helper = self._dm_helper
        status = "Running" if helper.is_running else "Idle"
        processed = helper.success + helper.failed
        desc = (
            f"**Status:** {status}\n"
            f"**Progress:** {processed}/{helper.total}\n"
            f"**Sent:** {helper.success}\n"
            f"**Failed:** {helper.failed}\n"
            f"**Pending:** {helper.pending}\n"
            f"**Scheduled:** {helper.scheduled}"
        )
        if helper.skipped:
            desc += f"\n**Skipped (no longer needed):** {helper.skipped}"
        if helper.cancelled:
            desc += f"\n**Cancelled:** {helper.cancelled}"
        if helper.pending or helper.scheduled:
            desc += "\n\nUse `/admin dmcancel` to abort the remaining queue."

        embed_cls = YellowEmbed if helper.pending > 0 else GreenEmbed
        embed = embed_cls(title="DM Queue Status", description=desc)

        # Name who could not be reached so an admin can follow up manually. The DM
        # queue is shared across features, so this is not scoped to a single batch.
        # The field caps at 1024 chars, so only the first ~23 render regardless of
        # how many are retained - the count in the heading is the honest number.
        unreachable = helper.failed_members
        if unreachable:
            embed.add_field(
                name=f"Recently Undeliverable ({len(unreachable)})",
                value=self._format_truncated_list([f"{m.mention} ({m.id})" for m in unreachable]),
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_admin.command(name="dmcancel", description="Abort all pending bot DMs")
    async def _admin_dmcancel_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        helper = self._dm_helper
        queued = helper.pending + helper.scheduled
        if not queued:
            return await interaction.response.send_message(
                embed=GreenEmbed(title="Nothing To Cancel", description="The DM queue is already empty."),
                ephemeral=True,
            )

        # No confirmation gate on purpose. This is an abort - every second spent
        # confirming is another DM delivered.
        dropped = await helper.purge()
        log.warning(f"{interaction.user} cancelled {dropped} pending DM(s)", guild=guild)

        await interaction.response.send_message(
            embed=OrangeEmbed(
                title="DM Queue Cancelled",
                description=(f"Dropped **{dropped}** pending DM(s).\n\nA message already being sent when you ran this may still go out."),
            ),
            ephemeral=True,
        )

    @_admin.command(name="bulkretire", description="Bulk retire players by Discord ID")
    async def _admin_bulk_retire_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        bulk_modal = BulkRetireModal()
        await interaction.response.send_modal(bulk_modal)
        timed_out = await bulk_modal.wait()
        if timed_out or not bulk_modal.interaction:
            return

        modal_interaction = bulk_modal.interaction
        await modal_interaction.response.defer(ephemeral=True, thinking=True)

        discord_ids, invalid_ids = bulk_modal.parse_discord_ids()
        if not discord_ids:
            return await modal_interaction.followup.send(
                embed=ErrorEmbed(description="No valid Discord IDs were provided."),
                ephemeral=True,
            )

        try:
            tiers = await self.tiers(guild=guild)
            default_roles = await self._get_welcome_roles(guild)
            # Fetched once for the batch rather than per retiree.
            agm_map = await self.agm_franchise_map(guild)
        except RscException as exc:
            return await modal_interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
        except RuntimeError as exc:
            return await modal_interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(exc)), ephemeral=True)

        transactions = cast("TransactionMixIn", self)
        retired_players: list[str] = []
        skipped_players = [f"`{discord_id}` invalid ID" for discord_id in invalid_ids]
        failed_players: list[str] = []

        for discord_id in discord_ids:
            member = guild.get_member(discord_id)
            player: discord.Member | discord.User

            if member:
                player = member
            else:
                try:
                    player = await self.bot.fetch_user(discord_id)
                except discord.NotFound:
                    skipped_players.append(f"`{discord_id}` user not found")
                    continue
                except discord.HTTPException as exc:
                    failed_players.append(f"`{discord_id}` lookup failed: {exc}")
                    continue

            try:
                result = await transactions.retire(
                    guild,
                    player=player,
                    executor=interaction.user,
                    notes="Bulk retire",
                    override=True,
                )
                log.debug(f"Bulk Retire Result: {result}", guild=guild)

                if member:
                    await update_nonplaying_discord(
                        guild=guild,
                        member=member,
                        tiers=tiers,
                        default_roles=default_roles,
                        agm_franchise=agm_map.get(member.id),
                    )

                embed, files = await transactions.build_transaction_embed(
                    guild=guild,
                    response=result,
                    player_in=cast("discord.Member", player),
                )
                await transactions.announce_transaction(guild=guild, embed=embed, files=files, player=player.id)
            except RscException as exc:
                failed_players.append(f"{player.mention}: {exc}")
                continue
            except MalformedTransactionResponse as exc:
                failed_players.append(f"{player.mention}: retired, announcement failed: {exc}")
                continue
            except (discord.HTTPException, AttributeError, ValueError) as exc:
                failed_players.append(f"{player.mention}: retired, Discord update failed: {exc}")
                continue

            retired_players.append(player.mention)

        description = f"**Retired:** {len(retired_players)}\n**Skipped:** {len(skipped_players)}\n**Failed:** {len(failed_players)}"
        embed_cls = SuccessEmbed if retired_players and not skipped_players and not failed_players else YellowEmbed
        embed = embed_cls(title="Bulk Retire Complete", description=description)

        if retired_players:
            embed.add_field(name="Retired", value=self._format_truncated_list(retired_players), inline=False)
        if skipped_players:
            embed.add_field(name="Skipped", value=self._format_truncated_list(skipped_players), inline=False)
        if failed_players:
            embed.add_field(name="Failed", value=self._format_truncated_list(failed_players), inline=False)

        await modal_interaction.followup.send(embed=embed, ephemeral=True)

    @_admin.command(name="directmessage", description="Send a direct message to a user")
    @app_commands.describe(
        member="Discord member to DM",
        message="Message content to send",
        send_at="Schedule the DM for a future date/time (ISO 8601, e.g. 2025-04-20T18:00)",
    )
    async def _admin_dm_user_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        message: str,
        send_at: Transform[datetime, DateTransformer] | None = None,
    ):
        guild = interaction.guild
        if not guild:
            return

        # If scheduling, convert naive input to guild timezone then to UTC
        utc_send_at: datetime | None = None
        if send_at is not None:
            guild_tz = await self.timezone(guild)
            if send_at.tzinfo is None:
                send_at = send_at.replace(tzinfo=guild_tz)
            utc_send_at = send_at.astimezone(UTC)
            if utc_send_at <= datetime.now(UTC):
                return await interaction.response.send_message(
                    embed=YellowEmbed(description="Scheduled time must be in the future."),
                    ephemeral=True,
                )

        if utc_send_at:
            await self._dm_helper.enqueue(member, content=message, send_at=utc_send_at)
            local_fmt = discord.utils.format_dt(utc_send_at, style="F")
            await interaction.response.send_message(
                embed=GreenEmbed(description=f"DM to {member.mention} scheduled for {local_fmt}."),
                ephemeral=True,
            )
        else:
            try:
                await member.send(content=message)
            except discord.Forbidden:
                return await interaction.response.send_message(
                    embed=YellowEmbed(description=f"Unable to DM {member.mention}. They may have DMs disabled."),
                    ephemeral=True,
                )
            except discord.HTTPException as exc:
                return await interaction.response.send_message(
                    embed=YellowEmbed(description=f"Failed to DM {member.mention}: {exc}"),
                    ephemeral=True,
                )

            await interaction.response.send_message(
                embed=GreenEmbed(description=f"DM sent to {member.mention}."),
                ephemeral=True,
            )

    @_admin.command(name="pfachnanel", description="Configure the PermFA announcement channel")
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

    async def _set_intent_dm_last_run(self, guild: discord.Guild, season: int, timestamp: int, executor: int):
        await self.config.custom("Admin", str(guild.id)).IntentDmLastSeason.set(season)
        await self.config.custom("Admin", str(guild.id)).IntentDmLastRun.set(timestamp)
        await self.config.custom("Admin", str(guild.id)).IntentDmLastExecutor.set(executor)

    async def _get_intent_dm_last_run(self, guild: discord.Guild) -> tuple[int | None, int | None, int | None]:
        """Season, unix timestamp, and executor of the last `/admin intents dm` run."""
        conf = self.config.custom("Admin", str(guild.id))
        return await conf.IntentDmLastSeason(), await conf.IntentDmLastRun(), await conf.IntentDmLastExecutor()

    async def _set_activity_check_missing_role(self, guild: discord.Guild, role_id: int | None):
        await self.config.custom("Admin", str(guild.id)).ActivityCheckMissingRole.set(role_id)

    async def _get_activity_check_missing_role(self, guild: discord.Guild) -> discord.Role | None:
        role_id = await self.config.custom("Admin", str(guild.id)).ActivityCheckMissingRole()
        if not role_id:
            return None
        return guild.get_role(role_id)

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

    @staticmethod
    def _format_truncated_list(lines: list[str]) -> str:
        if not lines:
            return "None"

        value = "\n".join(lines)
        if len(value) <= 1024:
            return value

        visible_lines: list[str] = []
        remaining_count = len(lines)
        for line in lines:
            suffix = f"\n...and {remaining_count - 1} more"
            candidate = "\n".join([*visible_lines, line])
            if len(candidate) + len(suffix) > 1024:
                break
            visible_lines.append(line)
            remaining_count -= 1

        return "\n".join(visible_lines) + f"\n...and {remaining_count} more"

    async def _set_permfa_msg_ids(self, guild: discord.Guild, msg_ids: list[int]):
        await self.config.custom("Admin", str(guild.id)).PermFAMsgIds.set(msg_ids)

    async def _get_permfa_msg_ids(self, guild: discord.Guild) -> list[int]:
        ids = await self.config.custom("Admin", str(guild.id)).PermFAMsgIds()
        if not ids:
            return []
        return ids
