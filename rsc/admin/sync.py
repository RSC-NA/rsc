import logging
from datetime import time
from typing import TYPE_CHECKING

import discord
from discord.ext import tasks
from redbot.core import app_commands

from rsc import const
from rsc.admin import AdminMixIn
from rsc.admin.views import ConfirmSyncView
from rsc.embeds import (  # YellowEmbed,
    ApiExceptionErrorEmbed,
    BlueEmbed,
    ErrorEmbed,
    ExceptionErrorEmbed,
    SuccessEmbed,
    WarningEmbed,
)
from rsc.enums import Status
from rsc.exceptions import DiscordNameTooLong, RscException
from rsc.logs import GuildLogAdapter
from rsc.transactions.roles import (
    update_draft_eligible_discord,
    update_free_agent_discord,
    update_league_player_discord,
    update_nonplaying_discord,
    update_nonplaying_gm_discord,
)
from rsc.utils import images, utils
from rsc.views import CancelView

if TYPE_CHECKING:
    from rscapi.models.league_player import LeaguePlayer
    from rscapi.models.member import Member as RSCMember
    from rscapi.models.tier import Tier

logger = logging.getLogger("red.rsc.admin.sync")
log = GuildLogAdapter(logger)


SYNC_LOOP_TIME = time(hour=7)  # 7:00 AM UTC


class AdminSyncMixIn(AdminMixIn):
    def __init__(self):
        log.debug("Initializing AdminMixIn:Sync")
        super().__init__()

        # Start sync loop
        if not self.sync_discord_roles.is_running():
            self.sync_discord_roles.start()

    # Tasks
    @tasks.loop(time=SYNC_LOOP_TIME)
    async def sync_discord_roles(self):
        log.info("Discord role sync loop is running.")
        guilds: list[discord.Guild] = list(self.bot.guilds)
        for guild in guilds:
            log.info("Syncing discord roles", guild=guild)
            if guild.id != 395806681994493964:
                continue

            # Get list of all tiers
            try:
                log.debug("Fetching tiers", guild=guild)
                tiers: list[Tier] = await self.tiers(guild)
            except RscException as exc:
                log.exception("Error fetching tiers", guild=guild, exc=exc)

            # One request answers AGM membership for the whole league. Resolving
            # it per member would be a full franchise list each time.
            try:
                log.debug("Fetching AGMs", guild=guild)
                agm_map = await self.agm_franchise_map(guild)
            except (RscException, RuntimeError) as exc:
                log.exception("Error fetching AGMs. Skipping guild.", guild=guild, exc=exc)
                continue

            log.debug("Fetching league players", guild=guild)
            total = 0
            synced = 0
            api_player: LeaguePlayer

            # Rostered
            async for api_player in self.paged_players(guild=guild):
                total += 1
                if not api_player.player.discord_id:
                    continue

                m = guild.get_member(api_player.player.discord_id)
                if not m:
                    if api_player.status not in [Status.DROPPED, Status.FORMER]:
                        log.warning(
                            "League player not in guild: %d",
                            api_player.player.discord_id,
                            guild=guild,
                        )
                    continue

                franchise = None
                if api_player.status == Status.UNSIGNED_GM:
                    # Get Franchise information
                    flist = await self.franchises(guild=guild, gm_discord_id=m.id)
                    if not flist:
                        log.error("Unsigned GM has no franchise in API: %s (%d)", m.display_name, m.id, guild=guild)
                        continue
                    franchise = flist.pop(0)

                add_devleague_role = await self.should_get_devleague_role(m)
                log.debug(f"Add Dev League Role: {add_devleague_role}")

                log.debug("Syncing Player: %s (%d)", m.display_name, m.id, guild=guild)
                synced += 1
                try:
                    await update_league_player_discord(
                        guild=guild,
                        player=m,
                        league_player=api_player,
                        franchise=franchise,
                        tiers=tiers,
                        devleague=add_devleague_role,
                        agm_franchise=agm_map.get(m.id),
                    )
                except DiscordNameTooLong as exc:
                    # The roles are already applied at this point, only the
                    # nickname was skipped. An API name nobody can fit in 32
                    # characters is not a bug, so log it without a traceback.
                    log.warning(
                        "Unable to update nickname for %s (%d): %s",
                        m.display_name,
                        m.id,
                        exc,
                        guild=guild,
                    )
                except (ValueError, AttributeError) as exc:
                    log.exception("Error syncing player: %s (%d)", m.display_name, m.id, guild=guild, exc_info=exc)

            log.debug("Total Players: %d", total, guild=guild)
            log.debug("Total Synced: %d", synced, guild=guild)
            log.info("Finished syncing league players", guild=guild)

    @sync_discord_roles.before_loop
    async def before_sync_discord_roles(self):
        await self.bot.wait_until_ready()

    _sync = app_commands.Group(
        name="sync",
        description="Sync various API data to the RSC discord server",
        parent=AdminMixIn._admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @_sync.command(
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
            if icons_allowed and guild_icon is not None:
                result = await guild.create_role(
                    name=const.LEAGUE_ROLE,
                    hoist=False,
                    display_icon=guild_icon,
                    permissions=const.GENERIC_ROLE_PERMS,
                    reason="Syncing required roles.",
                )
            else:
                result = await guild.create_role(
                    name=const.LEAGUE_ROLE,
                    hoist=False,
                    permissions=const.GENERIC_ROLE_PERMS,
                    reason="Syncing required roles.",
                )
            role_list.append(result)

        # General Manager
        r = discord.utils.get(guild.roles, name=const.GM_ROLE)
        if not r:
            if icons_allowed and guild_icon is not None:
                result = await guild.create_role(
                    name=const.GM_ROLE,
                    hoist=False,
                    display_icon=guild_icon,
                    permissions=const.GENERIC_ROLE_PERMS,
                    color=0x00D9FF,
                    reason="Syncing required roles.",
                )
            else:
                result = await guild.create_role(
                    name=const.GM_ROLE,
                    hoist=False,
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
            if icons_allowed and guild_icon is not None:
                result = await guild.create_role(
                    name=const.FREE_AGENT_ROLE,
                    hoist=False,
                    display_icon=guild_icon,
                    permissions=const.GENERIC_ROLE_PERMS,
                    reason="Syncing required roles.",
                )
            else:
                result = await guild.create_role(
                    name=const.FREE_AGENT_ROLE,
                    hoist=False,
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

        # Perm FA (Waiting)
        r = discord.utils.get(guild.roles, name=const.PERM_FA_WAITING_ROLE)
        if not r:
            result = await guild.create_role(
                name=const.PERM_FA_WAITING_ROLE,
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

    @_sync.command(
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
                log.error("%d has no name associated with it.", t.id)
                await interaction.followup.send(embed=ErrorEmbed(description=f"{t.id} has no name associated with it."))
                return

            schannel = None
            tchannel = None
            trole = None
            farole = None

            log.debug("Syncing %s roles", t.name, guild=guild)

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
                    display_icon=fa_icon or discord.utils.MISSING,
                    permissions=const.GENERIC_ROLE_PERMS,
                    color=t.color or discord.Color.default(),
                    reason="Syncing tier roles from API.",
                )
            elif t.color:
                await farole.edit(colour=t.color)

            if scorecategory:
                # Score Reporting Permissions
                s_overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
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
                    await schannel.edit(overwrites=s_overwrites)

            if chatcategory:
                # Tier Chat Permissions
                t_overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
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
                    await tchannel.edit(overwrites=t_overwrites)

            # Store roles for response
            roles[t.name] = [trole, farole]

        embed = BlueEmbed(
            title="Tiers Roles Synced",
            description="Synced all tier roles and created associated channels",
        )
        embed.add_field(
            name="Name",
            value="\n".join([t.name for t in tiers]),
            inline=True,
        )

        role_fmt = []
        for v in roles.values():
            role_fmt.append(", ".join([r.mention for r in v]))  # noqa: PERF401

        embed.add_field(name="Roles", value="\n".join(role_fmt), inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @_sync.command(
        name="transactionchannels",
        description="Check if all franchise transaction channels. If not, create them.",
    )
    @app_commands.describe(
        category="Guild category that holds all franchise transaction channels",
        delete_stale="Delete channels in the category that no longer match an active franchise",
    )
    async def _validate_transaction_channels(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel,
        delete_stale: bool = False,
    ):
        added: list[discord.TextChannel] = []
        deleted: list[str] = []
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
        channel_names = []

        for f in franchises:
            if not f.name:
                log.error("Franchise %d has no name.", f.id)
                await interaction.edit_original_response(embed=ErrorEmbed(description=f"Franchise {f.id} has no name in the API..."))
                return

            channel_names.append(await self.get_franchise_transaction_channel_name(f.name))

        if delete_stale:
            franchise_channel_names = set(channel_names)

            for channel in category.text_channels:
                if channel.name in franchise_channel_names:
                    continue

                log.info("Deleting stale transaction channel: %s", channel.name, guild=guild)
                deleted.append(channel.name)
                await channel.delete(reason="Removing stale franchise transaction channels during API sync")

        for f in franchises:
            if not f.name:
                log.error("Franchise %d has no name.", f.id)
                await interaction.edit_original_response(embed=ErrorEmbed(description=f"Franchise {f.id} has no name in the API..."))
                return

            channel = await self.get_franchise_transaction_channel(guild, f.name)

            if channel:
                log.debug("Found transaction channel: %s", channel.name, guild=guild)
                existing.append(channel)
            else:
                channel_name = await self.get_franchise_transaction_channel_name(f.name)
                log.info("Creating new transaction channel: %s", channel_name, guild=guild)
                content = None
                gm = None

                # Default Permissions
                overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
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
        if delete_stale and deleted:
            embed.add_field(name="Deleted", value="\n".join(deleted), inline=True)

        await interaction.edit_original_response(embed=embed)

    @_sync.command(
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

        # Fetched once for the whole run. Non-playing AGMs are the population
        # this command exists to get right, and they have no league player to
        # read a franchise off.
        try:
            log.debug("Fetching AGMs", guild=guild)
            agm_map = await self.agm_franchise_map(guild)
        except RscException as exc:
            return await interaction.edit_original_response(embed=ApiExceptionErrorEmbed(exc))
        except RuntimeError as exc:
            return await interaction.edit_original_response(embed=ExceptionErrorEmbed(exc_message=str(exc)))

        log.debug("Fetching all members", guild=guild)
        total = 0
        synced = 0
        # Members the loop below already reconciled, so the reverse sweep does
        # not spend a second Discord call removing a role it just removed.
        reconciled: set[int] = set()
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

            log.debug("Syncing non-playing member: %s (%d)", m.display_name, m.id, guild=guild)

            if not dryrun:
                try:
                    await update_nonplaying_discord(
                        guild=guild, member=m, tiers=tiers, default_roles=default_roles, agm_franchise=agm_map.get(m.id)
                    )
                    reconciled.add(m.id)
                except (ValueError, AttributeError) as exc:
                    await interaction.followup.send(content=str(exc), ephemeral=True)
            synced += 1

        log.debug("Total Members: %d", total, guild=guild)
        log.debug("Total Synced: %d", synced, guild=guild)

        # Reverse sweep.
        #
        # The loop above can only reconcile members the API returns. Someone
        # holding the Assistant GM role who has no member record at all -- they
        # left the league, or predate the API -- is invisible to it, and the role
        # is the one piece of AGM state nothing else would ever take back.
        #
        # Only the role comes off here. A stale AGM who is still a rostered
        # player legitimately keeps their franchise role and prefix; `/admin sync
        # players` owns the rest of their state.
        stale_agms: list[discord.Member] = []
        try:
            agm_role = await utils.get_agm_role(guild)
        except ValueError as exc:
            log.warning(f"Skipping stale AGM sweep: {exc}", guild=guild)
        else:
            for m in agm_role.members:
                if m.id in agm_map or m.id in reconciled:
                    continue
                log.info("Removing stale AGM role: %s (%d)", m.display_name, m.id, guild=guild)
                stale_agms.append(m)
                if not dryrun:
                    await m.remove_roles(agm_role, reason="API has no AGM record for this member")

        embed = BlueEmbed(
            title="Non-Playing Sync",
            description="All non-playing RSC members have been synced.",
        )
        if stale_agms:
            verb = "Would remove" if dryrun else "Removed"
            # Capped so a large sweep cannot blow the 1024 character field limit.
            listed = "\n".join(m.mention for m in stale_agms[:20])
            if len(stale_agms) > 20:
                listed += f"\n...and {len(stale_agms) - 20} more"
            embed.add_field(
                name=f"Stale AGM Roles ({len(stale_agms)})",
                value=f"{verb} the AGM role from:\n{listed}",
                inline=False,
            )
        embed.set_footer(text=f"Synced {synced}/{total} RSC member(s).")
        await interaction.edit_original_response(embed=embed)

    @_sync.command(
        name="players",
        description="Sync all league players in discord members. (Long Execution Time)",
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

        # One request for the whole run, not one per player.
        try:
            log.debug("Fetching AGMs", guild=guild)
            agm_map = await self.agm_franchise_map(guild)
        except RscException as exc:
            return await interaction.edit_original_response(embed=ApiExceptionErrorEmbed(exc))
        except RuntimeError as exc:
            return await interaction.edit_original_response(embed=ExceptionErrorEmbed(exc_message=str(exc)))

        log.debug("Fetching all rostered players", guild=guild)
        total = 0
        synced = 0
        api_player: LeaguePlayer

        # Rostered
        async for api_player in self.paged_players(guild=guild):
            total += 1
            if not api_player.player.discord_id:
                log.warning("League player has no discord id: %d", api_player.id, guild=guild)
                await interaction.followup.send(
                    embed=ErrorEmbed(description=f"League player {api_player.player.name} has no discord id in the API."),
                    ephemeral=True,
                )
                continue

            m = guild.get_member(api_player.player.discord_id)
            if not m:
                if api_player.status not in [Status.DROPPED, Status.FORMER]:
                    log.warning(
                        "League player not in guild and is active: %d",
                        api_player.player.discord_id,
                        guild=guild,
                    )
                    await interaction.followup.send(
                        embed=ErrorEmbed(description=f"League player {api_player.player.name} not in guild and is active."),
                        ephemeral=True,
                    )
                continue

            franchise = None
            if api_player.status == Status.UNSIGNED_GM:
                # Get Franchise information
                flist = await self.franchises(guild=guild, gm_discord_id=m.id)
                if not flist:
                    return await interaction.followup.send(
                        embed=ErrorEmbed(description=f"{m.mention} is an un-signed GM but franchise could not be found in API."),
                        ephemeral=False,
                    )
                franchise = flist.pop(0)

            log.debug("Syncing player: %s (%d)", m.display_name, m.id, guild=guild)
            synced += 1
            if not dryrun:
                try:
                    await update_league_player_discord(
                        guild=guild,
                        player=m,
                        league_player=api_player,
                        franchise=franchise,
                        tiers=tiers,
                        agm_franchise=agm_map.get(m.id),
                    )
                except DiscordNameTooLong as exc:
                    # Roles were applied, only the nickname was skipped. Report
                    # it so an admin can shorten the name in the API.
                    log.warning("Unable to update nickname for %s (%d): %s", m.display_name, m.id, exc, guild=guild)
                    await interaction.followup.send(
                        embed=WarningEmbed(
                            title="Nickname Too Long",
                            description=(
                                f"{m.mention} was synced but their nickname was left alone. "
                                f"`{exc.nickname}` is {len(exc.nickname)} characters and discord allows "
                                f"{utils.NICKNAME_MAX_LENGTH}."
                            ),
                        ),
                        ephemeral=True,
                    )
                except (ValueError, AttributeError) as exc:
                    await interaction.followup.send(content=str(exc), ephemeral=True)

        log.debug("Total Players: %d", total, guild=guild)
        log.debug("Total Synced: %d", synced, guild=guild)
        log.info("Finished syncing player")

        embed = BlueEmbed(
            title="League Player Sync",
            description="All RSC league players have been synced.",
        )
        embed.set_footer(text=f"Synced {synced}/{total} RSC players(s).")
        await interaction.edit_original_response(embed=embed)

    @_sync.command(
        name="member",
        description="Sync an individual members from the API to discord",
    )
    @app_commands.describe(member="RSC Discord member to sync")
    async def _sync_member_cmd(self, interaction: discord.Interaction, member: discord.Member):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer()
        try:
            default_roles = await self._get_welcome_roles(guild=guild)
            plist = await self.players(guild, discord_id=member.id, limit=1)
            tiers = await self.tiers(guild)
            # One list answers both "are they a GM" and "are they an AGM".
            all_franchises = await self.franchises(guild=guild)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=False)

        agm_franchise = next(
            (f for f in all_franchises if any(a.discord_id == member.id for a in (f.agms or []))),
            None,
        )

        if not plist:
            # Check if player is a non-playing GM
            gm = False
            franchise = None
            for f in all_franchises:
                if f.gm and f.gm.discord_id == member.id:
                    gm = True
                    franchise = f
                    break

            try:
                if gm and franchise:
                    await update_nonplaying_gm_discord(guild=guild, player=member, franchise=franchise, tiers=tiers)
                else:
                    await update_nonplaying_discord(
                        guild=guild, member=member, tiers=tiers, default_roles=default_roles, agm_franchise=agm_franchise
                    )
            except (ValueError, AttributeError) as exc:
                return await interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(exc)))
        else:
            lp = plist.pop(0)
            if lp.status == Status.UNSIGNED_GM:
                # Get Franchise information
                flist = await self.franchises(guild=guild, gm_discord_id=member.id)
                if not flist:
                    return await interaction.followup.send(
                        embed=ErrorEmbed(description=f"{member.mention} is an un-signed GM but franchise could not be found in API."),
                        ephemeral=False,
                    )
                franchise = flist.pop(0)

                # Devleague
                add_devleague_role = await self.should_get_devleague_role(member)
                log.debug(f"Add Dev League Role: {add_devleague_role}")

                try:
                    await update_league_player_discord(
                        guild=guild,
                        player=member,
                        league_player=lp,
                        tiers=tiers,
                        franchise=franchise,
                        default_roles=default_roles,
                        devleague=add_devleague_role,
                        agm_franchise=agm_franchise,
                    )
                except (ValueError, AttributeError) as exc:
                    return await interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(exc)))
            else:
                try:
                    await update_league_player_discord(
                        guild=guild, player=member, league_player=lp, tiers=tiers, agm_franchise=agm_franchise
                    )
                except (ValueError, AttributeError) as exc:
                    return await interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(exc)))

        await interaction.followup.send(
            embed=SuccessEmbed(description=f"Successfully synced {member.mention} from the API. Discord roles and name have been updated."),
            ephemeral=False,
        )

    @_sync.command(
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
        log.debug("Total FA: %d", total_fa, guild=guild)
        log.debug("Total PermFA: %d", total_pfa, guild=guild)
        log.debug("Combined Total: %d", total_players, guild=guild)
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
                    "Couldn't find FA in guild: %s (%d)",
                    player.player.name,
                    player.id,
                    guild=guild,
                )
                continue
            log.debug("Syncing FA: %s", m.display_name, guild=guild)

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
                        "Received %d (error code %d: %s)",
                        exc.status,
                        exc.code,
                        exc.text,
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

    @_sync.command(
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

    @_sync.command(
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
                log.debug("Found franchise role: %s", frole.name, guild=guild)
                if frole.name != fname:
                    log.info("Changing franchise role: %s", frole.name, guild=guild)
                    await frole.edit(name=fname)
                    fixed.append(frole)
                else:
                    existing.append(frole)
            else:
                log.info("Creating new franchise role: %s", fname, guild=guild)
                if icons_allowed and f.logo is not None:
                    nrole = await guild.create_role(
                        name=fname,
                        hoist=True,
                        display_icon=f.logo,
                        permissions=const.FRANCHISE_ROLE_PERMS,
                        reason="Syncing franchise roles from API",
                    )
                else:
                    nrole = await guild.create_role(
                        name=fname,
                        hoist=True,
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
