import logging
from typing import TYPE_CHECKING

import discord
from redbot.core import app_commands

from rsc import const
from rsc.admin import AdminMixIn
from rsc.admin.views import ConfirmSyncView
from rsc.embeds import ApiExceptionErrorEmbed, BlueEmbed, ErrorEmbed
from rsc.enums import Status
from rsc.exceptions import RscException
from rsc.logs import GuildLogAdapter
from rsc.transactions.roles import (
    update_draft_eligible_discord,
    update_free_agent_discord,
    update_nonplaying_discord,
    update_rostered_discord,
)
from rsc.utils import images, utils
from rsc.views import CancelView

if TYPE_CHECKING:
    from collections.abc import MutableMapping

    from rscapi.models.league_player import LeaguePlayer
    from rscapi.models.member import Member as RSCMember
    from rscapi.models.tier import Tier

logger = logging.getLogger("red.rsc.admin.sync")
log = GuildLogAdapter(logger)


class AdminSyncMixIn(AdminMixIn):
    def __init__(self):
        log.debug("Initializing AdminMixIn:Sync")

        super().__init__()

    _sync = app_commands.Group(
        name="sync",
        description="Sync various API data to the RSC discord server",
        parent=AdminMixIn._admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @_sync.command(  # type: ignore[type-var]
        name="requiredroles",
        description="Check if all base required roles exist. If not, create them.",
    )
    async def _validate_required_roles(
        self,
        interaction: discord.Interaction,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        guild_icon = None
        if guild.icon:
            gdata = await guild.icon.read()
            guild_icon = gdata

        role_list = []

        # Check feature list
        icons_allowed = "ROLE_ICONS" in guild.features

        # League
        r = discord.utils.get(guild.roles, name=const.LEAGUE_ROLE)
        if not r:
            result = await guild.create_role(
                name=const.LEAGUE_ROLE,
                hoist=False,
                display_icon=guild_icon if icons_allowed else None,  # type: ignore[arg-type]
                permissions=const.GENERIC_ROLE_PERMS,
                reason="Syncing required roles.",
            )
            role_list.append(result)

        # General Manager
        r = discord.utils.get(guild.roles, name=const.GM_ROLE)
        if not r:
            result = await guild.create_role(
                name=const.GM_ROLE,
                hoist=False,
                display_icon=guild_icon if icons_allowed else None,  # type: ignore[arg-type]
                permissions=const.GENERIC_ROLE_PERMS,
                color=0x00D9FF,
                reason="Syncing required roles.",
            )
            role_list.append(result)

        # AGM
        r = discord.utils.get(guild.roles, name=const.AGM_ROLE)
        if not r:
            result = await guild.create_role(
                name=const.AGM_ROLE,
                hoist=False,
                permissions=const.GM_ROLE_PERMS,
                color=0xCABDFF,
                reason="Syncing required roles.",
            )
            role_list.append(result)

        # Free Agent
        r = discord.utils.get(guild.roles, name=const.FREE_AGENT_ROLE)
        if not r:
            result = await guild.create_role(
                name=const.FREE_AGENT_ROLE,
                hoist=False,
                display_icon=guild_icon if icons_allowed else None,  # type: ignore[arg-type]
                permissions=const.GENERIC_ROLE_PERMS,
                reason="Syncing required roles.",
            )
            role_list.append(result)

        # Captain
        r = discord.utils.get(guild.roles, name=const.CAPTAIN_ROLE)
        if not r:
            result = await guild.create_role(
                name=const.CAPTAIN_ROLE,
                hoist=False,
                permissions=const.GENERIC_ROLE_PERMS,
                reason="Syncing required roles.",
            )
            role_list.append(result)

        # Former Player
        r = discord.utils.get(guild.roles, name=const.FORMER_PLAYER_ROLE)
        if not r:
            result = await guild.create_role(
                name=const.FORMER_PLAYER_ROLE,
                hoist=False,
                permissions=const.GENERIC_ROLE_PERMS,
                color=0xBB2F5D,
                reason="Syncing required roles.",
            )
            role_list.append(result)

        # Former Admin
        r = discord.utils.get(guild.roles, name=const.FORMER_ADMIN_ROLE)
        if not r:
            result = await guild.create_role(
                name=const.FORMER_ADMIN_ROLE,
                hoist=False,
                permissions=const.GENERIC_ROLE_PERMS,
                color=0xCF7864,
                reason="Syncing required roles.",
            )
            role_list.append(result)

        # Former Staff
        r = discord.utils.get(guild.roles, name=const.FORMER_STAFF_ROLE)
        if not r:
            result = await guild.create_role(
                name=const.FORMER_STAFF_ROLE,
                hoist=False,
                permissions=const.GENERIC_ROLE_PERMS,
                color=0xA18BFA,
                reason="Syncing required roles.",
            )
            role_list.append(result)

        # Spectator
        r = discord.utils.get(guild.roles, name=const.SPECTATOR_ROLE)
        if not r:
            result = await guild.create_role(
                name=const.SPECTATOR_ROLE,
                hoist=False,
                permissions=const.GENERIC_ROLE_PERMS,
                color=0xE91E63,
                reason="Syncing required roles.",
            )
            role_list.append(result)

        # Subbed Out
        r = discord.utils.get(guild.roles, name=const.SUBBED_OUT_ROLE)
        if not r:
            result = await guild.create_role(
                name=const.SUBBED_OUT_ROLE,
                hoist=False,
                permissions=const.GENERIC_ROLE_PERMS,
                reason="Syncing required roles.",
            )
            role_list.append(result)

        # IR
        r = discord.utils.get(guild.roles, name=const.IR_ROLE)
        if not r:
            result = await guild.create_role(
                name=const.IR_ROLE,
                hoist=False,
                permissions=const.GENERIC_ROLE_PERMS,
                reason="Syncing required roles.",
            )
            role_list.append(result)

        # Muted
        r = discord.utils.get(guild.roles, name=const.MUTED_ROLE)
        if not r:
            result = await guild.create_role(
                name=const.MUTED_ROLE,
                hoist=False,
                permissions=const.MUTED_ROLE_PERMS,
                color=0x0E0B0B,
                reason="Syncing required roles.",
            )
            role_list.append(result)

        # Perm FA
        r = discord.utils.get(guild.roles, name=const.PERM_FA_ROLE)
        if not r:
            result = await guild.create_role(
                name=const.PERM_FA_ROLE,
                hoist=False,
                permissions=const.GENERIC_ROLE_PERMS,
                reason="Syncing required roles.",
            )
            role_list.append(result)

        embed = BlueEmbed(
            title="Required Roles Synced",
            description="All of the following roles have been added to the server.",
        )

        embed.add_field(name="Name", value="\n".join([r.name for r in role_list]), inline=True)
        embed.add_field(name="Role", value="\n".join([r.mention for r in role_list]), inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @_sync.command(  # type: ignore[type-var]
        name="tiers",
        description="Check if all tier roles and channels exist. If not, create them.",
    )
    @app_commands.describe(
        scorecategory="Existing score reporting category. (Optional)",
        chatcategory="Existing category for tier chats. (Optional)",
    )
    async def _validate_tier_roles(
        self,
        interaction: discord.Interaction,
        chatcategory: discord.CategoryChannel | None = None,
        scorecategory: discord.CategoryChannel | None = None,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)
        tiers = await self.tiers(guild)

        # Validate response tier data
        if any(not t.name for t in tiers):
            return await interaction.followup.send(
                embed=ErrorEmbed(description="API returned malformed tier data. One or more tiers have no name."),
                ephemeral=True,
            )

        # Check feature list
        icons_allowed = "ROLE_ICONS" in guild.features

        gm_role = await utils.get_gm_role(guild)
        agm_role = await utils.get_agm_role(guild)
        league_role = await utils.get_league_role(guild)

        log.info("Syncing tier roles and channels", guild=guild)
        roles: dict[str, list[discord.Role]] = {}
        for t in tiers:
            if not t.name:
                log.error(f"{t.id} has no name associated with it.")
                await interaction.followup.send(embed=ErrorEmbed(description=f"{t.id} has no name associated with it."))
                return

            schannel = None
            tchannel = None
            trole = None
            farole = None

            log.debug(f"Syncing {t.name} roles", guild=guild)

            # Tier Role
            trole = discord.utils.get(guild.roles, name=t.name)
            if not trole:
                trole = await guild.create_role(
                    name=t.name,
                    hoist=False,
                    permissions=const.GENERIC_ROLE_PERMS,
                    color=t.color or discord.Color.default(),
                    reason="Syncing tier roles from API.",
                )
            elif t.color:
                await trole.edit(colour=t.color)

            # Get FA display icon
            fa_icon = None
            if icons_allowed:
                fa_img_path = await utils.fa_img_path_from_tier(t.name, tiny=True)
                if fa_img_path:
                    fa_icon = fa_img_path.read_bytes()

            # FA Role
            farole = discord.utils.get(guild.roles, name=f"{t.name}FA")
            if not farole:
                farole = await guild.create_role(
                    name=f"{t.name}FA",
                    hoist=False,
                    display_icon=fa_icon,  # type: ignore[arg-type]
                    permissions=const.GENERIC_ROLE_PERMS,
                    color=t.color or discord.Color.default(),
                    reason="Syncing tier roles from API.",
                )
            elif t.color:
                await farole.edit(colour=t.color)

            if scorecategory:
                # Score Reporting Permissions
                s_overwrites: MutableMapping[discord.Member | discord.Role, discord.PermissionOverwrite] = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=False, send_messages=False, add_reactions=False),
                    league_role: discord.PermissionOverwrite(
                        view_channel=True,
                        read_messages=True,
                        send_messages=False,
                        add_reactions=False,
                        read_message_history=True,
                    ),
                    trole: discord.PermissionOverwrite(
                        view_channel=True,
                        read_messages=True,
                        send_messages=True,
                        add_reactions=False,
                        read_message_history=True,
                    ),
                    farole: discord.PermissionOverwrite(
                        view_channel=True,
                        read_messages=True,
                        send_messages=True,
                        add_reactions=False,
                        read_message_history=True,
                    ),
                    gm_role: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_messages=True,
                        read_message_history=True,
                        add_reactions=True,
                    ),
                    agm_role: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_messages=True,
                        read_message_history=True,
                        add_reactions=True,
                    ),
                }

                log.debug(f"Syncing {t.name} score reporting channel", guild=guild)
                schannel = discord.utils.get(scorecategory.channels, name=f"{t.name}-score-reporting".lower())
                if not schannel:
                    # Create score reporting channel
                    schannel = await guild.create_text_channel(
                        name=f"{t.name}-score-reporting".lower(),
                        category=scorecategory,
                        overwrites=s_overwrites,
                        reason="Syncing tier channels from API",
                    )
                elif isinstance(schannel, discord.TextChannel):
                    await schannel.edit(overwrites=s_overwrites)  # type: ignore[arg-type]

            if chatcategory:
                # Tier Chat Permissions
                t_overwrites: MutableMapping[discord.Member | discord.Role, discord.PermissionOverwrite] = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=False, send_messages=False),
                    trole: discord.PermissionOverwrite(
                        view_channel=True,
                        read_messages=True,
                        send_messages=True,
                        add_reactions=True,
                        read_message_history=True,
                    ),
                    farole: discord.PermissionOverwrite(
                        view_channel=True,
                        read_messages=True,
                        send_messages=True,
                        add_reactions=True,
                        read_message_history=True,
                    ),
                    gm_role: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_messages=True,
                        read_message_history=True,
                        add_reactions=True,
                    ),
                }

                log.debug(f"Syncing {t.name} tier chat", guild=guild)
                tchannel = discord.utils.get(chatcategory.channels, name=f"{t.name}-chat".lower())
                if not tchannel:
                    # Create tier chat channel
                    tchannel = await guild.create_text_channel(
                        name=f"{t.name}-chat".lower(),
                        category=chatcategory,
                        overwrites=t_overwrites,
                        reason="Syncing tier channels from API",
                    )
                elif isinstance(tchannel, discord.TextChannel):
                    await tchannel.edit(overwrites=t_overwrites)  # type: ignore[arg-type]

            # Store roles for response
            roles[t.name] = [trole, farole]

        embed = BlueEmbed(
            title="Tiers Roles Synced",
            description="Synced all tier roles and created associated channels",
        )
        embed.add_field(
            name="Name",
            value="\n".join([t.name for t in tiers]),
            inline=True,  # type: ignore[type-var]
        )

        role_fmt = []
        for v in roles.values():
            role_fmt.append(", ".join([r.mention for r in v]))  # noqa: PERF401

        embed.add_field(name="Roles", value="\n".join(role_fmt), inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @_sync.command(  # type: ignore[type-var]
        name="transactionchannels",
        description="Check if all franchise transaction channels. If not, create them.",
    )
    @app_commands.describe(
        category="Guild category that holds all franchise transaction channels",
    )
    async def _validate_transaction_channels(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel,
    ):
        added: list[discord.TextChannel] = []
        existing: list[discord.TextChannel] = []

        guild = interaction.guild
        if not guild:
            return

        sync_view = ConfirmSyncView(interaction)
        await sync_view.prompt()
        franchises = await self.franchises(guild)
        await sync_view.wait()

        if not sync_view.result:
            return

        franchises = await self.franchises(guild)
        for f in franchises:
            if not f.name:
                log.error(f"Franchise {f.id} has no name.")
                await interaction.edit_original_response(embed=ErrorEmbed(description=f"Franchise {f.id} has no name in the API..."))
                return

            channel = await self.get_franchise_transaction_channel(guild, f.name)

            if channel:
                log.debug(f"Found transaction channel: {channel.name}", guild=guild)
                existing.append(channel)
            else:
                channel_name = await self.get_franchise_transaction_channel_name(f.name)
                log.info(f"Creating new transaction channel: {channel_name}", guild=guild)
                content = None
                gm = None

                # Default Permissions
                overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=False)
                }

                # Add Transactions
                trole = await self._trans_role(guild)
                if trole:
                    overwrites[trole] = discord.PermissionOverwrite(
                        manage_channels=True,
                        manage_permissions=True,
                        manage_messages=True,
                        view_channel=True,
                        send_messages=True,
                        embed_links=True,
                        attach_files=True,
                        read_messages=True,
                        read_message_history=True,
                        add_reactions=True,
                    )

                # Add GM
                if f.gm and f.gm.discord_id:
                    gm = guild.get_member(f.gm.discord_id)

                if gm:
                    content = f"Welcome to your new transaction channel {gm.mention}"
                    overwrites[gm] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        attach_files=True,
                        read_messages=True,
                        embed_links=True,
                        read_message_history=True,
                        add_reactions=True,
                    )

                channel = await guild.create_text_channel(
                    name=channel_name,
                    category=category,
                    overwrites=overwrites,
                    reason="Syncing franchise transaction channels from API",
                )

                # Ping GM
                if content:
                    await channel.send(
                        content=content,
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                added.append(channel)

        added.sort(key=lambda x: x.name)
        existing.sort(key=lambda x: x.name)
        embed = BlueEmbed(
            title="Franchise Transaction Channel Sync",
            description=f"Successfully synced {len(franchises)} transaction channels to the RSC discord.",
        )
        if existing:
            embed.add_field(
                name="Found",
                value="\n".join([r.mention for r in existing]),
                inline=True,
            )
        if added:
            embed.add_field(name="Created", value="\n".join([r.mention for r in added]), inline=True)

        await interaction.edit_original_response(embed=embed)

    @_sync.command(  # type: ignore[type-var]
        name="nonplaying",
        description="Sync all non playing discord members. (Long Execution Time)",
    )
    @app_commands.describe(dryrun="Do not modify any users.")
    async def _sync_nonplaying_cmd(self, interaction: discord.Interaction, dryrun: bool = False):
        guild = interaction.guild
        if not guild:
            return

        sync_view = ConfirmSyncView(interaction)
        await sync_view.prompt()

        try:
            log.debug("Fetching tiers", guild=guild)
            tiers: list[Tier] = await self.tiers(guild)
        except RscException as exc:
            return await interaction.edit_original_response(embed=ApiExceptionErrorEmbed(exc))

        # Wait for confirmation
        await sync_view.wait()

        if not sync_view.result:
            return

        default_roles = await self._get_welcome_roles(guild)

        log.debug("Fetching all members", guild=guild)
        total = 0
        synced = 0
        api_member: RSCMember
        async for api_member in self.paged_members(guild=guild, per_page=250):
            total += 1
            if not api_member.discord_id:
                continue

            # Check if member in league
            lp = await self.league_player_from_member(guild, api_member)
            if lp and lp.status != Status.DROPPED:
                continue

            m = guild.get_member(api_member.discord_id)
            if not m:
                continue

            log.debug(f"Syncing non-playing member: {m.display_name} ({m.id})", guild=guild)

            if not dryrun:
                try:
                    await update_nonplaying_discord(guild=guild, member=m, tiers=tiers, default_roles=default_roles)
                except (ValueError, AttributeError) as exc:
                    await interaction.followup.send(content=str(exc), ephemeral=True)
            synced += 1

        log.debug(f"Total Members: {total}", guild=guild)
        log.debug(f"Total Synced: {synced}", guild=guild)

        embed = BlueEmbed(
            title="Non-Playing Sync",
            description="All non-playing RSC members have been synced.",
        )
        embed.set_footer(text=f"Synced {synced}/{total} RSC member(s).")
        await interaction.edit_original_response(embed=embed)

    @_sync.command(  # type: ignore[type-var]
        name="players",
        description="Sync all players in discord members. (Long Execution Time)",
    )
    @app_commands.describe(dryrun="Do not modify any users.")
    async def _sync_players_cmd(self, interaction: discord.Interaction, dryrun: bool = False):
        guild = interaction.guild
        if not guild:
            return

        sync_view = ConfirmSyncView(interaction)
        await sync_view.prompt()

        try:
            log.debug("Fetching tiers", guild=guild)
            tiers: list[Tier] = await self.tiers(guild)
        except RscException as exc:
            return await interaction.edit_original_response(embed=ApiExceptionErrorEmbed(exc))

        # Wait for confirmation
        await sync_view.wait()

        if not sync_view.result:
            return

        log.debug("Fetching all rostered players", guild=guild)
        total = 0
        synced = 0
        api_player: LeaguePlayer

        # Rostered
        async for api_player in self.paged_players(guild=guild, status=Status.ROSTERED):
            total += 1
            if not api_player.player.discord_id:
                continue

            m = guild.get_member(api_player.player.discord_id)
            if not m:
                log.warning(
                    f"Rostered player not in guild: {api_player.player.discord_id}",
                    guild=guild,
                )
                continue

            log.debug(f"Syncing Player: {m.display_name} ({m.id})", guild=guild)
            synced += 1
            if not dryrun:
                try:
                    await update_rostered_discord(guild=guild, player=m, league_player=api_player, tiers=tiers)
                except (ValueError, AttributeError) as exc:
                    await interaction.followup.send(content=str(exc), ephemeral=True)

        # Renewed
        async for api_player in self.paged_players(guild=guild, status=Status.RENEWED):
            total += 1
            if not api_player.player.discord_id:
                continue

            m = guild.get_member(api_player.player.discord_id)
            if not m:
                log.warning(
                    f"Rostered player not in guild: {api_player.player.discord_id}",
                    guild=guild,
                )
                continue

            log.debug(f"Syncing Player: {m.display_name} ({m.id})", guild=guild)

            synced += 1
            if not dryrun:
                try:
                    await update_rostered_discord(guild=guild, player=m, league_player=api_player, tiers=tiers)
                except (ValueError, AttributeError) as exc:
                    await interaction.followup.send(content=str(exc), ephemeral=True)

        log.debug(f"Total Players: {total}", guild=guild)
        log.debug(f"Total Synced: {synced}", guild=guild)

        embed = BlueEmbed(
            title="Rostered Player Sync",
            description="All RSC rostered players have been synced.",
        )
        embed.set_footer(text=f"Synced {synced}/{total} RSC players(s).")
        await interaction.edit_original_response(embed=embed)

    @_sync.command(  # type: ignore[type-var]
        name="freeagent",
        description="Sync all free agent players in discord",
    )
    @app_commands.describe(dryrun="Do not modify any users.")
    async def _sync_freeagent_cmd(self, interaction: discord.Interaction, dryrun: bool = False):
        guild = interaction.guild
        if not guild:
            return

        sync_view = ConfirmSyncView(interaction)
        await sync_view.prompt()
        total_fa = await self.total_players(guild, status=Status.FREE_AGENT)
        total_pfa = await self.total_players(guild, status=Status.PERM_FA)
        tiers: list[Tier] = await self.tiers(guild)
        await sync_view.wait()

        if not sync_view.result:
            return

        # No tier data
        if not tiers:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    title="Free Agent Sync",
                    description="League has no tiers configured.",
                )
            )

        # Make sure tiers exist
        if not tiers:
            return await interaction.edit_original_response(
                embed=BlueEmbed(
                    title="Free Agent Sync",
                    description="League has no tiers configured.",
                )
            )

        loading_embed = BlueEmbed(
            title="Syncing Free Agents",
            description="Free Agent player synchronziation in progress",
        )

        # Send initial progress bar
        total_players = total_fa + total_pfa
        log.debug(f"Total FA: {total_fa}", guild=guild)
        log.debug(f"Total PermFA: {total_pfa}", guild=guild)
        log.debug(f"Combined Total: {total_players}", guild=guild)
        dFile = images.getProgressBar(
            x=10,
            y=10,
            w=225,
            h=30,
            progress=0.0,
            progress_bounds=(0, total_players),
        )

        # Progress View
        progress_view = CancelView(interaction, timeout=0)
        loading_embed.set_image(url="attachment://progress.jpeg")
        await interaction.edit_original_response(embed=loading_embed, attachments=[dFile], view=progress_view)

        idx = 0
        player: LeaguePlayer
        async for player in self.paged_players(guild, status=Status.FREE_AGENT):
            # Check if cancelled
            if progress_view.cancelled:
                loading_embed.title = "Sync Cancelled"
                loading_embed.description = "Cancelled synchronizing all free agent players."
                loading_embed.colour = discord.Color.red()
                return await interaction.edit_original_response(embed=loading_embed, attachments=[dFile], view=None)

            idx += 1

            if not (player.player and player.player.discord_id):
                continue

            # Get guild member from LeaguePlayer
            m = guild.get_member(player.player.discord_id)
            if not m:
                log.warning(
                    f"Couldn't find FA in guild: {player.player.name} ({player.id})",
                    guild=guild,
                )
                continue
            log.debug(f"Syncing FA: {m.display_name}", guild=guild)

            # Check if dry run
            if not dryrun:
                try:
                    await update_free_agent_discord(guild=guild, player=m, league_player=player, tiers=tiers)
                except (ValueError, AttributeError) as exc:
                    await interaction.followup.send(content=str(exc), ephemeral=True)

            # Update progress bar
            if (idx % 10) == 0:
                log.debug("Updating progress bar", guild=guild)
                progress = idx / total_players

                dFile = images.getProgressBar(
                    x=10,
                    y=10,
                    w=225,
                    h=30,
                    progress=progress,
                    progress_bounds=(idx, total_players),
                )

                try:
                    await interaction.edit_original_response(embed=loading_embed, attachments=[dFile], view=progress_view)
                except discord.HTTPException as exc:
                    log.warning(
                        f"Received {exc.status} (error code {exc.code}: {exc.text})",
                        guild=guild,
                    )
                    if exc.code == 50027:
                        # Try passing on Invalid Webhook Token (401)
                        pass

        # Perm FA
        loading_embed.title = "Syncing Perm FAs"
        loading_embed.description = "Permanent Free Agent player synchronziation in progress"

        # Update progress bar for PermFA
        dFile = images.getProgressBar(
            x=10,
            y=10,
            w=225,
            h=30,
            progress=idx / total_players,
            progress_bounds=(idx, total_players),
        )
        await interaction.edit_original_response(embed=loading_embed, attachments=[dFile], view=progress_view)

        async for player in self.paged_players(guild, status=Status.PERM_FA):
            # Check if cancelled
            if progress_view.cancelled:
                loading_embed.title = "Sync Cancelled"
                loading_embed.description = "Cancelled synchronizing all free agent players."
                loading_embed.colour = discord.Color.red()
                return await interaction.edit_original_response(embed=loading_embed, attachments=[dFile], view=None)

            idx += 1

            if not (player.player and player.player.discord_id):
                continue

            # Get guild member from LeaguePlayer
            m = guild.get_member(player.player.discord_id)
            if not m:
                log.warning(
                    f"Couldn't find PermFA in guild: {player.player.name} ({player.id})",
                    guild=guild,
                )
                continue
            log.debug(f"Syncing PermFA: {m.display_name}", guild=guild)

            # Check if dry run
            if not dryrun:
                try:
                    await update_free_agent_discord(guild=guild, player=m, league_player=player, tiers=tiers)
                except (ValueError, AttributeError) as exc:
                    await interaction.followup.send(content=str(exc), ephemeral=True)

            # Update progress bar
            if (idx % 10) == 0:
                log.debug("Updating progress bar", guild=guild)
                progress = idx / total_players

                dFile = images.getProgressBar(
                    x=10,
                    y=10,
                    w=225,
                    h=30,
                    progress=progress,
                    progress_bounds=(idx, total_players),
                )

                try:
                    await interaction.edit_original_response(embed=loading_embed, attachments=[dFile], view=progress_view)
                except discord.HTTPException as exc:
                    log.warning(
                        f"Received {exc.status} (error code {exc.code}: {exc.text})",
                        guild=guild,
                    )
                    if exc.code == 50027:
                        # Try passing on Invalid Webhook Token (401)
                        pass

        # Draw 100%
        dFile = images.getProgressBar(
            x=10,
            y=10,
            w=225,
            h=30,
            progress=1.0,
            progress_bounds=(total_players, total_players),
        )

        loading_embed.title = "Free Agent Sync"
        loading_embed.description = "Successfully synchronized all free agent players."
        await interaction.edit_original_response(embed=loading_embed, attachments=[dFile], view=None)

    @_sync.command(  # type: ignore[type-var]
        name="drafteligible",
        description="Sync all draft eligibile players in discord",
    )
    @app_commands.describe(dryrun="Do not modify any users.")
    async def _sync_drafteligible_cmd(self, interaction: discord.Interaction, dryrun: bool = False):
        guild = interaction.guild
        if not guild:
            return

        sync_view = ConfirmSyncView(interaction)
        await sync_view.prompt()
        plist = await self.players(guild, status=Status.DRAFT_ELIGIBLE, limit=10000)
        tiers: list[Tier] = await self.tiers(guild)
        await sync_view.wait()

        if not sync_view.result:
            return

        # Exit if no DE's exist
        if not plist:
            return await interaction.edit_original_response(
                embed=BlueEmbed(
                    title="Draft Eligible Sync",
                    description="There are no draft eligibile players to sync.",
                )
            )

        # No tier data
        if not tiers:
            return await interaction.edit_original_response(
                embed=BlueEmbed(
                    title="Draft Eligible Sync",
                    description="League has no configured tiers.",
                )
            )

        loading_embed = BlueEmbed(
            title="Syncing Draft Eligible",
            description="Draft eligible player synchronziation in progress",
        )

        total_de = len(plist)
        log.debug(f"Total DE: {total_de}")

        # Draw initial progress bar
        dFile = images.getProgressBar(
            x=10,
            y=10,
            w=225,
            h=30,
            progress=0.0,
            progress_bounds=(0, total_de),
        )

        # Progress View
        progress_view = CancelView(interaction, timeout=0)

        loading_embed.set_image(url="attachment://progress.jpeg")
        await interaction.edit_original_response(embed=loading_embed, attachments=[dFile], view=progress_view)

        for idx, player in enumerate(plist):
            # Check if cancelled
            if progress_view.cancelled:
                loading_embed.title = "Sync Cancelled"
                loading_embed.description = "Cancelled synchronizing all draft eligible players."
                loading_embed.colour = discord.Color.red()
                return await interaction.edit_original_response(embed=loading_embed, attachments=[dFile], view=None)

            idx += 1

            if not (player.player and player.player.discord_id):
                continue

            m = guild.get_member(player.player.discord_id)
            if not m:
                log.warning(f"Couldn't find DE in guild: {player.player.name} ({player.player.discord_id})")
                continue
            log.debug(f"Updating DE: {m.display_name}")

            if not dryrun:
                try:
                    await update_draft_eligible_discord(guild=guild, player=m, league_player=player, tiers=tiers)
                except (ValueError, AttributeError) as exc:
                    await interaction.followup.send(content=str(exc), ephemeral=True)

            # Update progress bar
            if (idx % 10) == 0:
                log.debug("Updating progress bar")
                progress = idx / total_de

                dFile = images.getProgressBar(
                    x=10,
                    y=10,
                    w=225,
                    h=30,
                    progress=progress,
                    progress_bounds=(idx, total_de),
                )

                await interaction.edit_original_response(embed=loading_embed, attachments=[dFile])

        # Draw 100%
        dFile = images.getProgressBar(
            x=10,
            y=10,
            w=225,
            h=30,
            progress=1.0,
            progress_bounds=(total_de, total_de),
        )

        loading_embed.title = "Draft Eligible Sync"
        loading_embed.description = "Successfully synchronized all draft eligible players."
        await interaction.edit_original_response(embed=loading_embed, attachments=[dFile], view=None)

    @_sync.command(  # type: ignore[type-var]
        name="franchiseroles",
        description="Check if all franchise roles exist. If not, create them.",
    )
    async def _validate_franchise_roles(
        self,
        interaction: discord.Interaction,
    ):
        added: list[discord.Role] = []
        existing: list[discord.Role] = []
        fixed: list[discord.Role] = []

        guild = interaction.guild
        if not guild:
            return

        sync_view = ConfirmSyncView(interaction)
        await sync_view.prompt()
        franchises = await self.franchises(guild)
        await sync_view.wait()

        if not sync_view.result:
            return

        log.debug(f"Guild Feature: {guild.features}")
        icons_allowed = "ROLE_ICONS" in guild.features
        for f in franchises:
            if not (f.name and f.gm):
                return await interaction.edit_original_response(
                    embed=ErrorEmbed(description=f"API returned no franchise name or GM name for ID: {f.id}")
                )

            fname = f"{f.name} ({f.gm.rsc_name})"
            frole = await utils.franchise_role_from_name(guild, f.name)
            if frole:
                log.debug(f"Found franchise role: {frole.name}", guild=guild)
                if frole.name != fname:
                    log.info(f"Changing franchise role: {frole.name}", guild=guild)
                    await frole.edit(name=fname)
                    fixed.append(frole)
                else:
                    existing.append(frole)
            else:
                log.info(f"Creating new franchise role: {fname}", guild=guild)
                nrole = await guild.create_role(
                    name=fname,
                    hoist=True,
                    display_icon=f.logo if icons_allowed else None,  # type: ignore[arg-type]
                    permissions=const.FRANCHISE_ROLE_PERMS,
                    reason="Syncing franchise roles from API",
                )
                added.append(nrole)

        added.sort(key=lambda x: x.name)
        existing.sort(key=lambda x: x.name)
        fixed.sort(key=lambda x: x.name)
        embed = BlueEmbed(
            title="Franchise Role Sync",
            description=f"Successfully synced {len(franchises)} franchise roles to the RSC discord.",
        )
        if existing:
            embed.add_field(
                name="Found",
                value="\n".join([r.mention for r in existing]),
                inline=True,
            )
        if fixed:
            embed.add_field(name="Fixed", value="\n".join([r.mention for r in fixed]), inline=True)
        if added:
            embed.add_field(name="Created", value="\n".join([r.mention for r in added]), inline=True)

        await interaction.edit_original_response(embed=embed)
