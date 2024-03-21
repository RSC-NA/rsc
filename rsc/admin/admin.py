import logging
import tempfile

import discord
from redbot.core import app_commands
from rscapi.models.franchise import Franchise
from rscapi.models.rebrand_a_franchise import RebrandAFranchise
from rscapi.models.team_details import TeamDetails

from rsc import const
from rsc.abc import RSCMixIn
from rsc.admin.modals import FranchiseRebrandModal, LeagueDatesModal
from rsc.admin.views import (
    ConfirmSyncView,
    CreateFranchiseView,
    DeleteFranchiseView,
    RebrandFranchiseView,
    TransferFranchiseView,
)
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    BlueEmbed,
    ErrorEmbed,
    SuccessEmbed,
    YellowEmbed,
)
from rsc.enums import Status
from rsc.exceptions import RscException
from rsc.franchises import FranchiseMixIn
from rsc.logs import GuildLogAdapter
from rsc.types import RebrandTeamDict
from rsc.utils import utils
from rsc.views import LinkButton

logger = logging.getLogger("red.rsc.admin")
log = GuildLogAdapter(logger)

defaults_guild = {"Dates": None}


class AdminMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing AdminMixIn")

        self.config.init_custom("Admin", 1)
        self.config.register_custom("Admin", **defaults_guild)
        super().__init__()

    # Top Level Group

    _admin = app_commands.Group(
        name="admin",
        description="Admin Only Commands",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # Sub Commands

    _members = app_commands.Group(
        name="members",
        description="RSC Member Management Commands",
        parent=_admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )
    _sync = app_commands.Group(
        name="sync",
        description="Sync various API data to the RSC discord server",
        parent=_admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )
    _franchise = app_commands.Group(
        name="franchise",
        description="Manage RSC franchises",
        parent=_admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # Member Commands

    @_members.command(name="changename", description="Change RSC name for a member")  # type: ignore
    @app_commands.describe(
        member="RSC discord member",
        name="New player name",
        tracker="Add a tracker link to the user. (Optional)",
    )
    async def _member_changename(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        name: str,
        tracker: str | None = None,
    ):
        if not interaction.guild:
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await self.change_member_name(interaction.guild, id=member.id, name=name)
            if tracker:
                await self.add_tracker(interaction.guild, member, tracker)
        except RscException as exc:
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return

        # Update nickname in RSC
        accolades = await utils.member_accolades(member)
        pfx = await utils.get_prefix(member)

        if pfx:
            new_nick = f"{pfx} | {name} {accolades}".strip()
        else:
            new_nick = f"{name} {accolades}".strip()

        await member.edit(nick=new_nick)
        await interaction.followup.send(
            embed=SuccessEmbed(
                description=f"Player RSC name has been updated to {member.mention}"
            )
        )

    @_members.command(name="create", description="Create an RSC member in the API")  # type: ignore
    @app_commands.describe(
        member="Discord member being added",
        rsc_name="RSC player name (Defaults to members display name)",
    )
    async def _member_create(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        rsc_name: str | None = None,
    ):
        if not interaction.guild:
            return

        try:
            await self.create_member(
                interaction.guild,
                member=member,
                rsc_name=rsc_name or member.display_name,
            )
        except RscException as exc:
            await interaction.response.send_message(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return

        # Change nickname if specified
        if rsc_name:
            await member.edit(nick=rsc_name)

        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"{member.mention} has been created in the RSC API."
            ),
            ephemeral=True,
        )

    @_members.command(name="delete", description="Delete an RSC member in the API")  # type: ignore
    @app_commands.describe(member="RSC discord member")
    async def _member_delete(
        self, interaction: discord.Interaction, member: discord.Member
    ):
        if not interaction.guild:
            return

        try:
            await self.delete_member(interaction.guild, member=member)
        except RscException as exc:
            await interaction.response.send_message(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"{member.mention} has been deleted from the RSC API."
            ),
            ephemeral=True,
        )

    @_members.command(  # type: ignore
        name="list", description="Fetch a list of members based on specified criteria."
    )
    @app_commands.describe(
        rsc_name="RSC in-game player name (Do not include prefix)",
        discord_username="Player discord username without discriminator",
        discord_id="Player discord ID",
        limit="Number of results to return (Default: 10, Max: 64)",
        offset="Return results starting at specified offset (Default: 0)",
    )
    async def _member_list(
        self,
        interaction: discord.Interaction,
        rsc_name: str | None = None,
        discord_username: str | None = None,
        discord_id: str | None = None,
        limit: app_commands.Range[int, 1, 64] = 10,
        offset: app_commands.Range[int, 0, 64] = 0,
    ):
        guild = interaction.guild
        if not guild:
            return

        if not (rsc_name or discord_username or discord_id):
            await interaction.response.send_message(
                "You must specify at least one search option.", ephemeral=True
            )
            return

        discord_id_int = None
        if discord_id:
            try:
                discord_id_int = int(discord_id)
            except ValueError:
                await interaction.response.send_message(
                    "Discord ID must be an integer.", ephemeral=True
                )
                return

        await interaction.response.defer(ephemeral=True)
        ml = await self.members(
            guild,
            rsc_name=rsc_name,
            discord_username=discord_username,
            discord_id=discord_id_int,
            limit=limit,
            offset=offset,
        )

        league_id = self._league[guild.id]
        m_fmt = []
        for m in ml:
            player = None
            if m.discord_id:
                p_member = guild.get_member(m.discord_id)
                if p_member:
                    player = p_member.mention
            else:
                player = m.rsc_name

            league = None
            if m.player_leagues:
                league = next(
                    (i for i in m.player_leagues if i.league.id == league_id), None
                )

            status = "Spectator"
            if league and league.status:
                status = Status(league.status).full_name

            m_fmt.append(
                (
                    player,
                    m.discord_id,
                    status,
                )
            )

        embed = BlueEmbed(
            title="RSC Member Results",
            description="The following members matched the specified criteria",
        )
        embed.add_field(
            name="Member", value="\n".join([str(x[0]) for x in m_fmt]), inline=True
        )
        embed.add_field(
            name="ID", value="\n".join([str(x[1]) for x in m_fmt]), inline=True
        )
        embed.add_field(
            name="Status", value="\n".join([x[2] for x in m_fmt]), inline=True
        )

        if embed.exceeds_limits():
            await interaction.followup.send(
                content="Result exceeds discord character limits. Please refine your search."
            )
            return

        await interaction.followup.send(embed=embed, ephemeral=True)

    # Validate Commands

    @_sync.command(  # type: ignore
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
                display_icon=guild_icon if icons_allowed else None,  # type: ignore
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
                display_icon=guild_icon if icons_allowed else None,  # type: ignore
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
                display_icon=guild_icon if icons_allowed else None,  # type: ignore
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

        embed.add_field(
            name="Name", value="\n".join([r.name for r in role_list]), inline=True
        )
        embed.add_field(
            name="Role", value="\n".join([r.mention for r in role_list]), inline=True
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @_sync.command(  # type: ignore
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
                await interaction.followup.send(
                    embed=ErrorEmbed(
                        description=f"{t.id} has no name associated with it."
                    )
                )
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
                    display_icon=fa_icon,  # type: ignore
                    permissions=const.GENERIC_ROLE_PERMS,
                    color=t.color or discord.Color.default(),
                    reason="Syncing tier roles from API.",
                )
            elif t.color:
                await farole.edit(colour=t.color)

            if scorecategory:
                # Score Reporting Permissions
                s_overwrites = {
                    guild.default_role: discord.PermissionOverwrite(
                        view_channel=False, send_messages=False, add_reactions=False
                    ),
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
                schannel = discord.utils.get(
                    scorecategory.channels, name=f"{t.name}-score-reporting".lower()
                )
                if not schannel:
                    # Create score reporting channel
                    schannel = await guild.create_text_channel(
                        name=f"{t.name}-score-reporting".lower(),
                        category=scorecategory,
                        overwrites=s_overwrites,  # type: ignore
                        reason="Syncing tier channels from API",
                    )
                else:
                    await schannel.edit(overwrites=s_overwrites)

            if chatcategory:
                # Tier Chat Permissions
                t_overwrites = {
                    guild.default_role: discord.PermissionOverwrite(
                        view_channel=False, send_messages=False
                    ),
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
                tchannel = discord.utils.get(
                    chatcategory.channels, name=f"{t.name}-chat".lower()
                )
                if not tchannel:
                    # Create tier chat channel
                    tchannel = await guild.create_text_channel(
                        name=f"{t.name}-chat".lower(),
                        category=chatcategory,
                        overwrites=t_overwrites,  # type: ignore
                        reason="Syncing tier channels from API",
                    )
                else:
                    await tchannel.edit(overwrites=t_overwrites)

            # Store roles for response
            roles[t.name] = [trole, farole]

        embed = BlueEmbed(
            title="Tiers Roles Synced",
            description="Synced all tier roles and created associated channels",
        )
        embed.add_field(
            name="Name", value="\n".join([t.name for t in tiers]), inline=True
        )

        role_fmt = []
        for v in roles.values():
            role_fmt.append(", ".join([r.mention for r in v]))
        embed.add_field(name="Roles", value="\n".join(role_fmt), inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @_sync.command(  # type: ignore
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
                await interaction.edit_original_response(
                    embed=ErrorEmbed(
                        description=f"Franchise {f.id} has no name in the API..."
                    )
                )
                return

            channel_name = f"{f.name.lower().replace(' ', '-')}-transactions"
            channel = discord.utils.get(guild.text_channels, name=channel_name)

            if channel:
                log.debug(f"Found transaction channel: {channel.name}", guild=guild)
                existing.append(channel)
            else:
                log.info(
                    f"Creating new transaction channel: {channel_name}", guild=guild
                )
                content = None
                gm = None

                # Default Permissions
                overwrites: dict[
                    discord.Role | discord.Member, discord.PermissionOverwrite
                ] = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=False)
                }

                # Add Transactions
                trole = await self._trans_role(guild)
                if trole:
                    overwrites[trole] = discord.PermissionOverwrite(
                        manage_channels=True,
                        manage_permissions=True,
                        view_channel=True,
                        send_messages=True,
                        embed_links=True,
                        attach_files=True,
                        read_messages=True,
                        read_message_history=True,
                        add_reactions=True,
                    )

                # Add GM
                if f.gm:
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
            embed.add_field(
                name="Created", value="\n".join([r.mention for r in added]), inline=True
            )

        await interaction.edit_original_response(embed=embed)

    @_sync.command(  # type: ignore
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
                    display_icon=f.logo if icons_allowed else None,  # type: ignore
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
            embed.add_field(
                name="Fixed", value="\n".join([r.mention for r in fixed]), inline=True
            )
        if added:
            embed.add_field(
                name="Created", value="\n".join([r.mention for r in added]), inline=True
            )

        await interaction.edit_original_response(embed=embed)

    # Franchise

    @_franchise.command(name="logo", description="Upload a logo for the franchise")  # type: ignore
    @app_commands.describe(franchise="Franchise name", logo="Franchise logo file (PNG)")
    @app_commands.autocomplete(franchise=FranchiseMixIn.franchise_autocomplete)  # type: ignore
    async def _franchise_logo(
        self, interaction: discord.Interaction, franchise: str, logo: discord.Attachment
    ):
        guild = interaction.guild
        if not guild:
            return

        # Defer in case file is large
        await interaction.response.defer(ephemeral=True)

        # validate franchise
        flist = await self.franchises(guild, name=franchise)
        if not flist:
            await interaction.followup.send(
                embed=ErrorEmbed(description=f"**{franchise}** does not exist."),
                ephemeral=True,
            )
            return

        if len(flist) > 1:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"**{franchise}** matches more than one franchise name."
                ),
                ephemeral=True,
            )
            return

        fdata = flist.pop()

        # Validate franchise data
        if not (fdata.id and fdata.prefix and fdata.name):
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"**{franchise}** returned malformed data from API."
                ),
                ephemeral=True,
            )
            return

        logo_bytes = await logo.read()
        # have to do this because monty sux
        try:
            with tempfile.NamedTemporaryFile() as fp:
                fp.write(logo_bytes)
                fp.seek(0)
                result: Franchise = await self.upload_franchise_logo(
                    guild, fdata.id, fp.name
                )
        except RscException as exc:
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc=exc),
                ephemeral=True,
            )
            return

        # Validate result
        if not result.logo:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description="Something went wrong during logo upload. API did not return a logo url."
                ),
                ephemeral=True,
            )
            return

        # Remove old emoji. Discord API doesn't let us update it in place
        old_emoji = await utils.emoji_from_prefix(guild, fdata.prefix)
        if old_emoji:
            log.debug(f"Deleting old franchise emoji: {old_emoji.name}")
            await old_emoji.delete(reason="Updating emoji to new logo")

        # Discord Max
        MAX_EMOJIS = 200 if "ROLE_ICONS" in guild.features else 50
        MAX_EMOJI_SIZE = 256000  # 256kb

        # Make sure we have enough emoji slots
        log.debug(
            f"[{guild.name}] Max Emojis: {MAX_EMOJIS} Emoji Size: {MAX_EMOJI_SIZE}"
        )
        if len(guild.emojis) >= MAX_EMOJIS:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    title="Logo Upload Error",
                    description=(
                        "Franchise logo was uploaded but guild doesn't have enough emoji slots available.\n\n"
                        f"Guild Emoji Count: {len(guild.emojis)}\n"
                        f"Max Emoji Count: {MAX_EMOJIS}"
                    ),
                )
            )
            return

        # Validate image size for emoji/icon. Resize to 128x128 if needed.
        log.debug(f"Img Size: {len(logo_bytes)}")
        if len(logo_bytes) >= MAX_EMOJI_SIZE:
            log.debug("Image is too large... resizing to 128x128")
            orig_size = len(logo_bytes)
            logo_bytes = await utils.img_to_thumbnail(logo_bytes, 128, 128, "PNG")
            log.debug(f"New Img Size: {len(logo_bytes)}")
            # Final size validation
            if len(logo_bytes) >= MAX_EMOJI_SIZE:
                await interaction.followup.send(
                    embed=ErrorEmbed(
                        title="Logo Upload Error",
                        description=(
                            "Franchise logo was uploaded but we were unable to resize it as a guild emoji.\n\n"
                            f"Original Image Size: {orig_size}\n"
                            f"Resized 128x128 Size: {len(logo_bytes)}\n"
                            f"Max Emoji Size: {MAX_EMOJI_SIZE}"
                        ),
                    )
                )
                return

        # Update franchise display icon
        icons_allowed = "ROLE_ICONS" in guild.features
        if icons_allowed:
            frole = await utils.franchise_role_from_name(guild, fdata.name)
            if not frole:
                log.error(f"Unable to find franchise role: {fdata.name}")
                await interaction.followup.send(
                    embed=YellowEmbed(
                        title="Logo Updated",
                        description=(
                            "Franchise logo was uploaded but we were unable to find the franchise role in the guild.\n\n"
                            f"Franchise Name: `{fdata.name}`"
                        ),
                    )
                )
                return
            else:
                await frole.edit(display_icon=logo_bytes)
        log.debug("Franchise role display icon was updated.")

        # Validate emoji name
        log.debug(f"Emoji Name: {fdata.prefix}")
        if not await utils.valid_emoji_name(fdata.prefix):
            await interaction.followup.send(
                embed=YellowEmbed(
                    title="Logo Updated",
                    description=(
                        "Franchise logo was uploaded but desired emoji name is invalid. "
                        "Must only contain the following characters. `[a-z0-9_]`.\n\n"
                        f"Emoji Name: `{fdata.prefix}`"
                    ),
                )
            )
            return

        # Recreate emoji
        new_emoji = await guild.create_custom_emoji(
            name=fdata.prefix, image=logo_bytes, reason=f"{franchise} has a new logo"
        )
        log.debug(f"New franchise emoji: {new_emoji.name}")

        full_logo_url = await self.full_logo_url(guild, result.logo)

        embed = SuccessEmbed(
            title="Logo Updated",
            description=(
                f"{franchise} logo has been uploaded to the API.\n\n"
                "Franchise emoji and display icon have also been updated."
            ),
        )
        embed.add_field(name="Height", value=logo.height, inline=True)
        embed.add_field(name="Width", value=logo.width, inline=True)
        embed.add_field(name="Size", value=logo.size, inline=True)
        embed.add_field(name="Emoji", value=f"`:{fdata.prefix}:`", inline=False)

        url_button = LinkButton(label="Logo Link", url=full_logo_url)
        logo_view = discord.ui.View()
        logo_view.add_item(url_button)

        # Add new logo as thumbnail in embed
        embed.set_thumbnail(url=logo.url)
        await interaction.followup.send(embed=embed, view=logo_view, ephemeral=True)

    @_franchise.command(name="rebrand", description="Rebrand a franchise")  # type: ignore
    @app_commands.autocomplete(franchise=FranchiseMixIn.franchise_autocomplete)  # type: ignore
    @app_commands.describe(
        franchise="Franchise to rebrand", override="Admin only override"
    )
    async def _franchise_rebrand(
        self,
        interaction: discord.Interaction,
        franchise: str,
        override: bool = False,
    ):
        guild = interaction.guild
        if not guild:
            return

        # Send modal
        rebrand_modal = FranchiseRebrandModal()
        await interaction.response.send_modal(rebrand_modal)

        # Fetch franchise data while user is in modal
        fl = await self.franchises(guild, name=franchise)
        await rebrand_modal.wait()

        # Validate original franchise exists
        if not fl:
            await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(description="No franchise found with that name."),
                ephemeral=True,
            )
            return
        if len(fl) > 1:
            await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Found multiple franchises matching that name... Please be more specific."
                ),
                ephemeral=True,
            )
            return

        fdata = fl.pop()

        if len(rebrand_modal.teams) != len(fdata.tiers):
            await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(
                    description=(
                        "Number of team names does not match number of tiers in franchise.\n\n"
                        f"**Tiers:** {len(fdata.tiers)}\n"
                        f"**Team Names:** {len(rebrand_modal.teams)}"
                    )
                ),
                ephemeral=True,
            )
            return

        # Match teams to tiers
        rebrands = []
        for t in fdata.tiers:
            rebrands.append(
                RebrandTeamDict(
                    name=rebrand_modal.teams.pop(0), tier=t.name, tier_id=t.id
                )
            )

        rebrand_view = RebrandFranchiseView(
            rebrand_modal.interaction,
            old_name=franchise,
            name=rebrand_modal.name,
            prefix=rebrand_modal.prefix,
            teams=rebrands,
        )
        await rebrand_view.prompt()
        await rebrand_view.wait()

        if not rebrand_view.result:
            return

        # Populate TeamDetails list with new names and team IDs
        tdetails: list[TeamDetails] = []
        for t in rebrands:
            tdetails.append(TeamDetails(tier=t["tier_id"], name=t["name"]))

        # Rebrand Franchise
        log.debug("Rebranding franchise.")
        rebrand = RebrandAFranchise(
            name=rebrand_modal.name,
            prefix=rebrand_modal.prefix,
            teams=tdetails,
            admin_override=override,
        )
        try:
            new_fdata = await self.rebrand_franchise(
                guild, id=fdata.id, rebrand=rebrand
            )
            log.debug(new_fdata)
        except RscException as exc:
            await rebrand_modal.interaction.edit_original_response(
                embed=ApiExceptionErrorEmbed(exc), view=None
            )
            return

        # Update franchise role
        frole = await utils.franchise_role_from_name(guild, franchise)
        if not frole:
            log.error(
                f"[{interaction.guild}] Unable to find franchise role for rebrand: {franchise}"
            )
            await rebrand_modal.interaction.edit_original_response(
                embed=ErrorEmbed(
                    description="Franchise was rebranded but franchise role was not found."
                )
            )
            return

        await frole.edit(name=f"{rebrand_modal.name} ({fdata.gm.rsc_name})")

        # Update all prefix
        await utils.update_prefix_for_franchise_role(frole, rebrand_modal.prefix)

        embed = SuccessEmbed(
            description=f"**{fdata.name}** has been rebranded to **{rebrand_modal.name}**"
        )
        await rebrand_modal.interaction.edit_original_response(embed=embed, view=None)

    @_franchise.command(name="delete", description="Delete a franchise")  # type: ignore
    @app_commands.describe(franchise="Franchise name")
    @app_commands.autocomplete(franchise=FranchiseMixIn.franchise_autocomplete)  # type: ignore
    async def _franchise_delete(
        self,
        interaction: discord.Interaction,
        franchise: str,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)
        fl = await self.franchises(guild, name=franchise)
        if not fl:
            await interaction.followup.send(
                embed=ErrorEmbed(description=f"**{franchise}** does not exist."),
                ephemeral=True,
            )
            return
        if len(fl) > 1:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"**{franchise}** matches more than one franchise name."
                ),
                ephemeral=True,
            )
            return

        delete_view = DeleteFranchiseView(interaction, name=franchise)
        await delete_view.prompt()

        # Get detailed information on players
        fdata = await self.franchise_by_id(guild, fl[0].id)
        await delete_view.wait()

        if not delete_view.result:
            return

        # Delete franchise in API
        try:
            await self.delete_franchise(guild, id=fdata.id)
        except RscException as exc:
            await interaction.edit_original_response(
                embed=ApiExceptionErrorEmbed(exc), view=None
            )
            return

        # Roles
        fa_role = await utils.get_free_agent_role(guild)
        gm_role = await utils.get_gm_role(guild)
        former_gm_role = await utils.get_former_gm_role(guild)
        frole = await utils.franchise_role_from_name(guild, fdata.name)

        # Transaction Channel
        tchan = await self._trans_channel(guild)

        # Edit GM
        gm = guild.get_member(fdata.gm.discord_id)
        if gm:
            await gm.remove_roles(gm_role)
            await gm.add_roles(former_gm_role)

        # Edit roles and prefix
        for t in fdata.teams:
            tier = t.tier
            tier_fa_role = await utils.get_tier_fa_role(guild, tier)
            for p in t.players:
                m = guild.get_member(p.discord_id)
                if not m:
                    continue

                await utils.give_fa_prefix(gm)
                await m.add_roles(fa_role, tier_fa_role)
                if tchan:
                    await tchan.send(
                        f"{p.mention} has been released to Free Agency ({tier})",
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )

        # Check if GM wasn't a league player
        if gm and not gm.display_name.startswith("FA |"):
            new_nick = await utils.remove_prefix(gm)
            await gm.edit(nick=new_nick)

        # Delete role
        if frole:
            log.debug(f"Deleting franchise role: {frole.name}")
            await frole.delete(reason="Franchise has been deleted")
        else:
            log.error(f"Unable to find franchise role: {fdata.name}", guild=guild)

        # Send result
        await interaction.edit_original_response(
            embed=SuccessEmbed(
                description=f"**{franchise}** has been successfully deleted. All players have been sent to free agency."
            ),
            view=None,
        )

    @_franchise.command(  # type: ignore
        name="create", description="Create a new franchise in the league"
    )
    @app_commands.describe(
        name="Franchise name",
        prefix='Franchise prefix (Ex: "TG")',
        gm="General Manager",
    )
    async def _franchise_create(
        self,
        interaction: discord.Interaction,
        name: str,
        prefix: str,
        gm: discord.Member,
    ):
        guild = interaction.guild
        if not guild:
            return

        create_view = CreateFranchiseView(interaction, name, gm)
        await create_view.prompt()
        await create_view.wait()

        if not create_view.result:
            return

        try:
            log.debug(f"Creating franchise: {name}")
            f: Franchise = await self.create_franchise(guild, name, prefix, gm)
        except RscException as exc:
            await interaction.edit_original_response(
                embed=ApiExceptionErrorEmbed(exc),
                view=None,
            )
            return

        # Create franchise role
        frole = await guild.create_role(
            name=f"{name} ({f.gm.rsc_name})", reason="New franchise created"
        )

        # GM role
        gm_role = discord.utils.get(guild.roles, name=const.GM_ROLE)

        await gm.add_roles(frole, gm_role)

        # Update GM Prefix
        gm_name = await utils.remove_prefix(gm)
        await gm.edit(nick=f"{prefix} | {gm_name}")

        embed = SuccessEmbed(description="Franchise has been created.")
        embed.add_field(name="Name", value=name, inline=True)
        embed.add_field(name="GM", value=gm.mention, inline=True)
        await interaction.edit_original_response(embed=embed, view=None)

    @_franchise.command(  # type: ignore
        name="transfer", description="Transfer ownership of a franchise"
    )
    @app_commands.describe(franchise="Franchise name", gm="General Manager")
    @app_commands.autocomplete(franchise=FranchiseMixIn.franchise_autocomplete)  # type: ignore
    async def _franchise_transfer(
        self,
        interaction: discord.Interaction,
        franchise: str,
        gm: discord.Member,
    ):
        guild = interaction.guild
        if not guild:
            return

        transfer_view = TransferFranchiseView(interaction, franchise=franchise, gm=gm)
        await transfer_view.prompt()
        # Fetch franchise data during view
        fl = await self.franchises(guild, name=franchise)
        await transfer_view.wait()

        if not fl:
            await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description="No franchises found with the name **{franchise}**"
                )
            )
            return
        if len(fl) > 1:
            await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description="Multiple franchises found with the name **{franchise}**"
                )
            )
            return

        fdata = fl.pop()

        if not transfer_view.result:
            return

        try:
            log.debug(f"Transfering {franchise} to {gm.id}")
            f: Franchise = await self.transfer_franchise(guild, fdata.id, gm)
        except RscException as exc:
            await interaction.edit_original_response(
                embed=ApiExceptionErrorEmbed(exc),
                view=None,
            )
            return

        # Remove old franchise role if it exists
        old_frole = await utils.franchise_role_from_disord_member(gm)
        if old_frole:
            log.debug(f"Removing old franchise role: {old_frole.name}")
            await gm.remove_roles(old_frole)

        # Update franchise role
        frole = await utils.franchise_role_from_name(guild, franchise)
        if not frole:
            await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description=f"Franchise was trasnferred to {gm.mention} but franchise role was not found."
                )
            )
            return

        await frole.edit(name=f"{f.name} ({f.gm.rsc_name})")
        await gm.add_roles(frole)

        await interaction.edit_original_response(
            embed=SuccessEmbed(
                description=f"**{franchise}** has been transferred to {gm.mention}"
            )
        )

    # Other Group Commands

    @_admin.command(name="dates", description="Configure the dates command output")  # type: ignore
    async def _admin_set_dates(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        dates_modal = LeagueDatesModal()
        await interaction.response.send_modal(dates_modal)
        await dates_modal.wait()

        await self._set_dates(interaction.guild, value=dates_modal.date_input.value)

    # Config

    async def _set_dates(self, guild: discord.Guild, value: str):
        await self.config.custom("Admin", str(guild.id)).Dates.set(value)

    async def _get_dates(self, guild: discord.Guild) -> str:
        return await self.config.custom("Admin", str(guild.id)).Dates()
