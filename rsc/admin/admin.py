import logging
import tempfile
from typing import MutableMapping, cast

import discord
from redbot.core import app_commands
from rscapi.models.franchise import Franchise
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.member import Member as RSCMember
from rscapi.models.rebrand_a_franchise import RebrandAFranchise
from rscapi.models.team_details import TeamDetails
from rscapi.models.tier import Tier

from rsc import const
from rsc.abc import RSCMixIn
from rsc.admin.modals import (
    AgmMessageModal,
    FranchiseRebrandModal,
    IntentMissingModal,
    LeagueDatesModal,
)
from rsc.admin.views import (
    ConfirmSyncView,
    CreateFranchiseView,
    DeleteFranchiseView,
    InactiveCheckView,
    RebrandFranchiseView,
    TransferFranchiseView,
)
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    BlueEmbed,
    ErrorEmbed,
    GreenEmbed,
    LoadingEmbed,
    SuccessEmbed,
    YellowEmbed,
)
from rsc.enums import ActivityCheckStatus, Status
from rsc.exceptions import LeagueNotConfigured, RscException
from rsc.franchises import FranchiseMixIn
from rsc.logs import GuildLogAdapter
from rsc.teams import TeamMixIn
from rsc.tiers import TierMixIn
from rsc.transactions.roles import (
    update_draft_eligible_discord,
    update_free_agent_discord,
    update_nonplaying_discord,
    update_rostered_discord,
)
from rsc.types import AdminSettings, RebrandTeamDict
from rsc.utils import images, utils
from rsc.views import CancelView, LinkButton

logger = logging.getLogger("red.rsc.admin")
log = GuildLogAdapter(logger)

defaults_guild = AdminSettings(
    ActivityCheckMsgId=None,
    AgmMessage=None,
    Dates=None,
    IntentChannel=None,
    IntentMissingRole=None,
    IntentMissingMsg=None,
)


class AdminMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing AdminMixIn")

        self.config.init_custom("Admin", 1)
        self.config.register_custom("Admin", **defaults_guild)
        super().__init__()

    async def setup_persistent_activity_check(self, guild: discord.Guild):
        # Check if inactivity check is present
        msg_id = await self._get_activity_check_msg_id(guild)
        log.debug(f"Inactive Message ID: {msg_id}")
        if not msg_id:
            return

        # Get API configuration since view is independent of RscMixIn
        conf = self._api_conf[guild.id]
        if not conf:
            log.error(f"{guild.name} has an inactivity check but no API configuration")

        league_id = self._league[guild.id]
        if not league_id:
            log.error(f"{guild.name} has an inactivity check but no league ID")

        inactive_channel = discord.utils.get(guild.channels, name="inactivity-check")
        if not inactive_channel:
            log.warning(
                "Inactive check channel does not exist but is turned on. Resetting..."
            )
            await self._set_actvity_check_msg_id(guild, None)
            return

        log.debug(f"[{guild.name}] Making activity check persistent: {msg_id}")
        # Create and attach view to persistent message ID
        inactive_view = InactiveCheckView(
            guild=guild, league_id=league_id, api_conf=conf
        )
        self.bot.add_view(inactive_view, message_id=msg_id)

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
    _agm = app_commands.Group(
        name="agm",
        description="Manage franchise AGMs",
        parent=_admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )
    _stats = app_commands.Group(
        name="stats",
        description="RSC League Stats",
        parent=_admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )
    _inactive = app_commands.Group(
        name="inactivecheck",
        description="Begin or end an activity check for players.",
        parent=_admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )
    _intents = app_commands.Group(
        name="intents",
        description="Manage player Intent to Play settings",
        parent=_admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # Settings
    @_admin.command(name="settings", description="Display RSC Admin settings.")  # type: ignore
    async def _admin_settings_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        intent_role = await self._get_intent_missing_role(guild)
        intent_channel = await self._get_intent_channel(guild)
        intent_missing_msg = await self._get_intent_missing_message(guild)
        dates = await self._get_dates(guild)
        agm_msg = await self._get_agm_message(guild)

        intent_role_fmt = intent_role.mention if intent_role else "None"
        intent_channel_fmt = intent_channel.mention if intent_channel else "None"

        intent_embed = BlueEmbed(
            title="Admin Settings",
            description="Displaying configured settings for RSC Admins",
        )
        intent_embed.add_field(
            name="Intent Missing Channel", value=intent_channel_fmt, inline=False
        )
        intent_embed.add_field(
            name="Intent Missing Role", value=intent_role_fmt, inline=False
        )
        intent_embed.add_field(
            name="Intent Missing Message", value=intent_missing_msg, inline=False
        )

        agm_msg_embed = BlueEmbed(title="Admin Dates Setting", description=dates)
        dates_embed = BlueEmbed(title="Admin AGM Message", description=agm_msg)

        await interaction.response.send_message(
            embeds=[intent_embed, agm_msg_embed, dates_embed], ephemeral=True
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
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=False)

        try:
            if tracker:
                await self.add_tracker(guild, member, tracker)
            mdata = await self.change_member_name(guild, id=member.id, name=name)
        except RscException as exc:
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=False
            )
            return

        # Update nickname in RSC
        accolades = await utils.member_accolades(member)
        pfx = await utils.get_prefix(member)

        if pfx:
            new_nick = f"{pfx} | {name} {accolades}".strip()
        else:
            new_nick = f"{name} {accolades}".strip()

        try:
            await member.edit(nick=new_nick)
        except discord.Forbidden as exc:
            await interaction.followup.send(
                content=f"Unable to update nickname {member.mention}: {exc}"
            )

        # Update franchise role if player is GM
        if mdata.elevated_roles:
            for elevated in mdata.elevated_roles:
                if elevated.gm and elevated.league.id == self._league[guild.id]:
                    frole = await utils.franchise_role_from_disord_member(member)
                    if not frole:
                        return await interaction.followup.send(
                            embed=ErrorEmbed(
                                description=f"Name change was successful but could not find {member.mention} franchise role. Unable to update GM name in role, Please open a modmail ticket."
                            )
                        )

                    fsplit = frole.name.split("(", maxsplit=1)
                    if len(fsplit) != 2:
                        return await interaction.followup.send(
                            embed=ErrorEmbed(
                                description=f"Error updating franchise role {frole.mention}. Unable to parse name and GM."
                            )
                        )

                    log.debug("Updating Franchise Role")
                    fname = fsplit[0].strip()
                    await frole.edit(name=f"{fname} ({name})")

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

        # Validate response tier data
        if any(not t.name for t in tiers):
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API returned malformed tier data. One or more tiers have no name."
                ),
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
                s_overwrites: MutableMapping[
                    discord.Member | discord.Role, discord.PermissionOverwrite
                ] = {
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
                        overwrites=s_overwrites,
                        reason="Syncing tier channels from API",
                    )
                elif isinstance(schannel, discord.TextChannel):
                    await schannel.edit(overwrites=s_overwrites)  # type: ignore

            if chatcategory:
                # Tier Chat Permissions
                t_overwrites: MutableMapping[
                    discord.Member | discord.Role, discord.PermissionOverwrite
                ] = {
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
                        overwrites=t_overwrites,
                        reason="Syncing tier channels from API",
                    )
                elif isinstance(tchannel, discord.TextChannel):
                    await tchannel.edit(overwrites=t_overwrites)  # type: ignore

            # Store roles for response
            roles[t.name] = [trole, farole]

        embed = BlueEmbed(
            title="Tiers Roles Synced",
            description="Synced all tier roles and created associated channels",
        )
        embed.add_field(
            name="Name", value="\n".join([t.name for t in tiers]), inline=True  # type: ignore
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
            embed.add_field(
                name="Created", value="\n".join([r.mention for r in added]), inline=True
            )

        await interaction.edit_original_response(embed=embed)

    @_sync.command(  # type: ignore
        name="nonplaying",
        description="Sync all non playing discord members. (Long Execution Time)",
    )
    @app_commands.describe(dryrun="Do not modify any users.")
    async def _sync_nonplaying_cmd(
        self, interaction: discord.Interaction, dryrun: bool = False
    ):
        guild = interaction.guild
        if not guild:
            return

        sync_view = ConfirmSyncView(interaction)
        await sync_view.prompt()

        try:
            log.debug("Fetching tiers", guild=guild)
            tiers: list[Tier] = await self.tiers(guild)
        except RscException as exc:
            return await interaction.edit_original_response(
                embed=ApiExceptionErrorEmbed(exc)
            )

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

            log.debug(
                f"Syncing non-playing member: {m.display_name} ({m.id})", guild=guild
            )

            if not dryrun:
                try:
                    await update_nonplaying_discord(
                        guild=guild, member=m, tiers=tiers, default_roles=default_roles
                    )
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

    @_sync.command(  # type: ignore
        name="players",
        description="Sync all players in discord members. (Long Execution Time)",
    )
    @app_commands.describe(dryrun="Do not modify any users.")
    async def _sync_players_cmd(
        self, interaction: discord.Interaction, dryrun: bool = False
    ):
        guild = interaction.guild
        if not guild:
            return

        sync_view = ConfirmSyncView(interaction)
        await sync_view.prompt()

        try:
            log.debug("Fetching tiers", guild=guild)
            tiers: list[Tier] = await self.tiers(guild)
        except RscException as exc:
            return await interaction.edit_original_response(
                embed=ApiExceptionErrorEmbed(exc)
            )

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
                    await update_rostered_discord(
                        guild=guild, player=m, league_player=api_player, tiers=tiers
                    )
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
                    await update_rostered_discord(
                        guild=guild, player=m, league_player=api_player, tiers=tiers
                    )
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

    @_sync.command(  # type: ignore
        name="freeagent",
        description="Sync all free agent players in discord",
    )
    @app_commands.describe(dryrun="Do not modify any users.")
    async def _sync_freeagent_cmd(
        self, interaction: discord.Interaction, dryrun: bool = False
    ):
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
        await interaction.edit_original_response(
            embed=loading_embed, attachments=[dFile], view=progress_view
        )

        idx = 0
        player: LeaguePlayer
        async for player in self.paged_players(guild, status=Status.FREE_AGENT):
            # Check if cancelled
            if progress_view.cancelled:
                loading_embed.title = "Sync Cancelled"
                loading_embed.description = (
                    "Cancelled synchronizing all free agent players."
                )
                loading_embed.colour = discord.Color.red()
                return await interaction.edit_original_response(
                    embed=loading_embed, attachments=[dFile], view=None
                )

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
                    await update_free_agent_discord(
                        guild=guild, player=m, league_player=player, tiers=tiers
                    )
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
                    await interaction.edit_original_response(
                        embed=loading_embed, attachments=[dFile], view=progress_view
                    )
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
        loading_embed.description = (
            "Permanent Free Agent player synchronziation in progress"
        )

        # Reset progress bar for PermFA
        dFile = images.getProgressBar(
            x=10,
            y=10,
            w=225,
            h=30,
            progress=0.0,
            progress_bounds=(0, total_players),
        )
        await interaction.edit_original_response(
            embed=loading_embed, attachments=[dFile], view=progress_view
        )

        async for player in self.paged_players(guild, status=Status.PERM_FA):
            # Check if cancelled
            if progress_view.cancelled:
                loading_embed.title = "Sync Cancelled"
                loading_embed.description = (
                    "Cancelled synchronizing all free agent players."
                )
                loading_embed.colour = discord.Color.red()
                return await interaction.edit_original_response(
                    embed=loading_embed, attachments=[dFile], view=None
                )

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
                    await update_free_agent_discord(
                        guild=guild, player=m, league_player=player, tiers=tiers
                    )
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
                    await interaction.edit_original_response(
                        embed=loading_embed, attachments=[dFile], view=progress_view
                    )
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
        await interaction.edit_original_response(
            embed=loading_embed, attachments=[dFile], view=None
        )

    @_sync.command(  # type: ignore
        name="drafteligible",
        description="Sync all draft eligibile players in discord",
    )
    @app_commands.describe(dryrun="Do not modify any users.")
    async def _sync_drafteligible_cmd(
        self, interaction: discord.Interaction, dryrun: bool = False
    ):
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
        await interaction.edit_original_response(
            embed=loading_embed, attachments=[dFile], view=progress_view
        )

        for idx, player in enumerate(plist):
            # Check if cancelled
            if progress_view.cancelled:
                loading_embed.title = "Sync Cancelled"
                loading_embed.description = (
                    "Cancelled synchronizing all draft eligible players."
                )
                loading_embed.colour = discord.Color.red()
                return await interaction.edit_original_response(
                    embed=loading_embed, attachments=[dFile], view=None
                )

            idx += 1

            if not (player.player and player.player.discord_id):
                continue

            m = guild.get_member(player.player.discord_id)
            if not m:
                log.warning(
                    f"Couldn't find DE in guild: {player.player.name} ({player.player.discord_id})"
                )
                continue
            log.debug(f"Updating DE: {m.display_name}")

            if not dryrun:
                try:
                    await update_draft_eligible_discord(
                        guild=guild, player=m, league_player=player, tiers=tiers
                    )
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

                await interaction.edit_original_response(
                    embed=loading_embed, attachments=[dFile]
                )

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
        loading_embed.description = (
            "Successfully synchronized all draft eligible players."
        )
        await interaction.edit_original_response(
            embed=loading_embed, attachments=[dFile], view=None
        )

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
            if not (f.name and f.gm):
                return await interaction.edit_original_response(
                    embed=ErrorEmbed(
                        description=f"API returned no franchise name or GM name for ID: {f.id}"
                    )
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

    @_franchise.command(name="addteam", description="Add a new team to a franchise")  # type: ignore
    @app_commands.describe(
        franchise="Franchise name", tier="Team Tier", name="Team Name"
    )
    @app_commands.autocomplete(
        franchise=FranchiseMixIn.franchise_autocomplete,
        tier=TierMixIn.tier_autocomplete,
    )
    async def _franchise_addteam_cmd(
        self, interaction: discord.Interaction, franchise: str, tier: str, name: str
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        tier = tier.capitalize()

        try:
            result = await self.create_team(
                guild, franchise=franchise, tier=tier, name=name
            )
            log.debug(f"Result: {result}")
        except RscException as exc:
            return await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )

        # Update team cache
        if name not in self._team_cache[guild.id]:
            self._team_cache[guild.id].append(name)

        embed = GreenEmbed(title="Team Created", description="Team has been created.")
        embed.add_field(name="Name", value=result.name, inline=True)
        embed.add_field(name="Franchise", value=result.franchise.name, inline=True)
        if result.tier:
            embed.add_field(name="Tier", value=result.tier.name, inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @_franchise.command(name="delteam", description="Remove a team from a franchise")  # type: ignore
    @app_commands.describe(
        franchise="Franchise name", tier="Team Tier", team="Team to delete"
    )
    @app_commands.autocomplete(
        franchise=FranchiseMixIn.franchise_autocomplete,
        tier=TierMixIn.tier_autocomplete,
        team=TeamMixIn.teams_autocomplete,
    )
    async def _franchise_rmteam_cmd(
        self, interaction: discord.Interaction, franchise: str, tier: str, team: str
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        tier = tier.capitalize()

        fteams = await self.teams(guild, franchise=franchise, tier=tier, name=team)
        if not fteams:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Unable to find a matching team in API."),
                ephemeral=True,
            )

        if len(fteams) > 1:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API returned multiple results for that team."
                ),
                ephemeral=True,
            )

        fteam = fteams.pop(0)

        if not fteam.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="API returned a team without an ID."),
                ephemeral=True,
            )

        try:
            await self.delete_team(guild, team_id=fteam.id)
        except RscException as exc:
            return await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )

        # Update team cache
        if team in self._team_cache[guild.id]:
            self._team_cache[guild.id].append(team)

        embed = GreenEmbed(title="Team Deleted", description="Team has been deleted.")
        embed.add_field(name="Name", value=team, inline=True)
        embed.add_field(name="Franchise", value=franchise, inline=True)
        embed.add_field(name="Tier", value=tier, inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

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
        else:
            await interaction.followup.send(
                content=f"Unable to find franchise emoji ({fdata.prefix}). It has not been removed."
            )

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
            return await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(description="No franchise found with that name."),
                ephemeral=True,
            )
        if len(fl) > 1:
            return await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Found multiple franchises matching that name... Please be more specific."
                ),
                ephemeral=True,
            )

        fdata = fl.pop()

        if not fdata.id:
            return await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(
                    description="API returned franchise without an ID attached."
                ),
                ephemeral=True,
            )

        if not (fdata.gm and fdata.gm.rsc_name):
            return await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(
                    description="API returned franchise without a GM or GM name."
                ),
                ephemeral=True,
            )

        # Validate type but allow empty tier list
        if not isinstance(fdata.tiers, list):
            return await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(
                    description=f"API returned non-list type for franchise tiers. Franchise ID: {fdata.id}"
                ),
                ephemeral=True,
            )

        # Number of rebranded teams must match number of franchise tiers
        if len(rebrand_modal.teams) != len(fdata.tiers):
            return await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(
                    description=(
                        "Number of team names does not match number of tiers in franchise.\n\n"
                        f"**Tiers:** {len(fdata.tiers)}\n"
                        f"**Team Names:** {len(rebrand_modal.teams)}"
                    )
                ),
                ephemeral=True,
            )

        # Match teams to tiers
        rebrands = []
        fdata.tiers.sort(key=lambda x: cast(int, x.id))
        for t in fdata.tiers:
            if t.name and t.id:
                rebrands.append(
                    RebrandTeamDict(
                        name=rebrand_modal.teams.pop(0), tier=t.name, tier_id=t.id
                    )
                )
            else:
                raise RuntimeError("Franchise team has no name or ID.")

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

        await rebrand_modal.interaction.edit_original_response(
            embed=LoadingEmbed(), view=None
        )

        # Get franchise role
        frole = await utils.franchise_role_from_name(guild, franchise)
        if not frole:
            log.error(
                f"Unable to find franchise role for rebrand: {franchise}", guild=guild
            )
            return await rebrand_modal.interaction.edit_original_response(
                embed=ErrorEmbed(
                    description="Franchise was rebranded but franchise role was not found."
                )
            )

        # Populate TeamDetails list with new names and team IDs
        tdetails: list[TeamDetails] = []
        for r in rebrands:
            tdetails.append(TeamDetails(tier=r["tier_id"], name=r["name"]))

        # Rebrand Franchise
        log.debug(f"Rebranding {franchise} to {rebrand_modal.name}")
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
            return await rebrand_modal.interaction.edit_original_response(
                embed=ApiExceptionErrorEmbed(exc), view=None
            )

        # Update franchise cache
        if franchise in self._franchise_cache[guild.id]:
            self._franchise_cache[guild.id].remove(franchise)

        if rebrand_modal.name not in self._franchise_cache[guild.id]:
            self._franchise_cache[guild.id].append(rebrand_modal.name)
            self._franchise_cache[guild.id].sort()

        # Update transaction channel
        trans_channel = discord.utils.get(
            guild.channels, name=f"{franchise.lower().replace(' ', '-')}-transactions"
        )
        if trans_channel:
            log.debug(f"Before position: {trans_channel.position}")
            trans_channel = await trans_channel.edit(
                name=f"{rebrand_modal.name.lower().replace(' ','-')}-transactions"
            )
            if trans_channel.category:
                # Debug print
                log.debug(
                    f"Category Channel Count: {len(trans_channel.category.channels)}"
                )
                for c in trans_channel.category.channels:
                    log.debug(f"Channel: {c.name} Position: {c.position}")

                channels = sorted(trans_channel.category.channels, key=lambda x: x.name)
                min_idx = min(c.position for c in trans_channel.category.channels)
                log.debug(f"Min Index: {min_idx}")
                idx = channels.index(trans_channel) + 1
                log.debug(f"Transaction Channel Index: {idx} ({min_idx+idx})")
                await trans_channel.edit(position=min_idx + idx)
        else:
            await interaction.followup.send(
                content="Unable to find franchise transaction channel. Must be manually updated.",
                ephemeral=True,
            )

        # Update franchise role
        await frole.edit(name=f"{rebrand_modal.name} ({new_fdata.gm.rsc_name})")

        # Update emoji
        if fdata.prefix:
            emoji = await utils.emoji_from_prefix(guild, prefix=fdata.prefix)
            if emoji:
                await emoji.edit(name=new_fdata.prefix)
            else:
                await interaction.followup.send(
                    content=f"Unable to update franchise emoji. `{fdata.prefix}` not found.",
                    ephemeral=True,
                )

        # Update all prefix
        try:
            for m in frole.members:
                name = await utils.remove_prefix(m)
                await m.edit(nick=f"{rebrand_modal.prefix} | {name}")
        except discord.Forbidden as exc:
            await interaction.followup.send(
                content=f"Unable to update nickname {m.mention}: `{exc}`",
                ephemeral=True,
            )

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
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"**{franchise}** does not exist."),
                ephemeral=True,
            )
        if len(fl) > 1:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"**{franchise}** matches more than one franchise name."
                ),
                ephemeral=True,
            )

        delete_view = DeleteFranchiseView(interaction, name=franchise)
        await delete_view.prompt()

        if not fl[0].id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API did not return a franchise ID attached to franchise data."
                ),
                ephemeral=True,
            )

        # Get detailed information on players
        fdata = await self.franchise_by_id(guild, fl[0].id)
        await delete_view.wait()

        if not delete_view.result:
            return

        if not fdata:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"No franchise data returned for ID: {fl[0].id}"
                ),
                ephemeral=True,
            )

        # Validate franchise data
        if not fdata.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API did not return a franchise ID attached to franchise data."
                ),
                ephemeral=True,
            )

        if not fdata.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API did not return a franchise ID attached to franchise data."
                ),
                ephemeral=True,
            )

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
        gm = None
        if fdata.gm.discord_id:
            gm = guild.get_member(fdata.gm.discord_id)
        if gm:
            await gm.remove_roles(gm_role)
            await gm.add_roles(former_gm_role)

        # Edit roles and prefix
        if fdata.teams:
            for t in fdata.teams:
                tier = t.tier
                tier_fa_role = await utils.get_tier_fa_role(guild, tier)

                # Not sure why these types are `list[Player|None] | None`
                if not t.players:
                    continue

                for p in t.players:
                    m = guild.get_member(p.discord_id)
                    if not m:
                        continue

                    await utils.give_fa_prefix(m)
                    await m.add_roles(fa_role, tier_fa_role)
                    if tchan:
                        await tchan.send(
                            f"{m.mention} has been released to Free Agency ({tier})",
                            allowed_mentions=discord.AllowedMentions(users=True),
                        )

        # Don't give FA prefix to non-playing GM
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

        # GM role
        gm_role = discord.utils.get(guild.roles, name=const.GM_ROLE)
        if not gm_role:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(description="General Manager role not found in guild.")
            )

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
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description="No franchises found with the name **{franchise}**"
                )
            )
        if len(fl) > 1:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description="Multiple franchises found with the name **{franchise}**"
                )
            )

        if not transfer_view.result:
            return
        log.debug("GM transfer confirmed.")

        # Display working screen
        await interaction.edit_original_response(
            embed=YellowEmbed(
                title="Transferring Franchise",
                description="Please wait while the GM transfer is processed...",
            ),
            view=None,
        )

        fdata = fl.pop()
        if not fdata.id:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description="API did not return a franchise ID attached to franchise data."
                )
            )

        try:
            log.debug(f"Transferring {franchise} to {gm.id}")
            f: Franchise = await self.transfer_franchise(guild, fdata.id, gm)
        except RscException as exc:
            return await interaction.edit_original_response(
                embed=ApiExceptionErrorEmbed(exc),
                view=None,
            )

        # Get franchise role
        frole = await utils.franchise_role_from_name(guild, franchise)
        if not frole:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description=f"Franchise was transferred to {gm.mention} but franchise role was not found."
                )
            )

        # Get GM role
        gm_role = await utils.get_gm_role(guild)
        if not gm_role:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description=f"Franchise was transferred to {gm.mention} but GM role was not found."
                )
            )

        # Get FA role
        fa_role = await utils.get_free_agent_role(guild)
        if not fa_role:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description=f"Franchise was transferred to {gm.mention} but FA role was not found."
                )
            )

        # Get AGM role
        agm_role = await utils.get_agm_role(guild)
        if not agm_role:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description=f"Franchise was transferred to {gm.mention} but AGM role was not found."
                )
            )

        # Get captain role
        captain_role = await utils.get_captain_role(guild)
        if not captain_role:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description=f"Franchise was transferred to {gm.mention} but Captain role was not found."
                )
            )

        # Update franchise role to new GM
        log.debug("Updating Franchise Role")
        await frole.edit(name=f"{f.name} ({f.gm.rsc_name})")

        # Remove old franchise role from new GM if it exist
        new_gm_old_frole = await utils.franchise_role_from_disord_member(gm)
        if new_gm_old_frole:
            await gm.remove_roles(new_gm_old_frole)

        # Update new GM roles and name
        log.debug(f"Adding GM role to {gm.id}")
        await gm.add_roles(gm_role, frole, reason="Promoted to GM")
        await gm.remove_roles(fa_role, captain_role, agm_role, reason="Promoted to GM")
        await gm.edit(nick=await utils.format_discord_prefix(gm, prefix=f.prefix))

        # Remove TierFA role if it exists on new GM
        for role in gm.roles:
            log.debug(f"GM Role: {role.name}")
            if role.name.endswith("FA"):
                log.debug(f"Removing new GM tier FA role: {role}")
                await gm.remove_roles(role, reason="Promoted to GM")
                break

        # Get old gm discord reference
        old_gm = None
        if fdata.gm and fdata.gm.discord_id:
            old_gm = guild.get_member(fdata.gm.discord_id)

        # Update old GM roles and name
        if old_gm:
            former_gm_role = await utils.get_former_gm_role(guild)
            if former_gm_role and former_gm_role not in old_gm.roles:
                await old_gm.add_roles(former_gm_role)

            await old_gm.remove_roles(
                frole, gm_role, captain_role, reason="Removed from GM"
            )
            await old_gm.edit(
                nick=f"FA | {await utils.remove_prefix(old_gm)}",
                reason="Removed from GM",
            )

            # Fetch tier and add tier FA roles
            old_gm_plist = await self.players(guild, discord_id=old_gm.id, limit=1)
            if old_gm_plist:
                old_gm_lp = old_gm_plist.pop(0)
                if old_gm_lp.tier and old_gm_lp.tier.name:
                    await old_gm.add_roles(fa_role, reason="Removed from GM")
                    old_gm_tier = old_gm_lp.tier.name
                    log.debug(f"Old GM Tier: {old_gm_tier}")
                    old_gm_tierfa_role = await utils.get_tier_fa_role(
                        guild, old_gm_tier
                    )
                    log.debug(f"Old GM Tier Role: {old_gm_tierfa_role}")
                    await old_gm.add_roles(old_gm_tierfa_role, reason="Removed from GM")

        await interaction.edit_original_response(
            embed=SuccessEmbed(
                description=f"**{franchise}** has been transferred to {gm.mention}"
            ),
            view=None,
        )

    @_agm.command(name="message", description="Configure the AGM promotion message")  # type: ignore
    async def _agm_set_message_cmd(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        agm_msg_modal = AgmMessageModal()
        await interaction.response.send_modal(agm_msg_modal)
        await agm_msg_modal.wait()

        await self._set_agm_message(
            interaction.guild, value=agm_msg_modal.agm_msg.value
        )

    @_agm.command(  # type: ignore
        name="add", description="Add an Assistant GM to a franchise."
    )
    @app_commands.describe(franchise="Franchise name", agm="Player to promote to AGM")
    @app_commands.autocomplete(franchise=FranchiseMixIn.franchise_autocomplete)  # type: ignore
    async def _franchise_promote_agm_cmd(
        self,
        interaction: discord.Interaction,
        franchise: str,
        agm: discord.Member,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        # Get AGM promotion message
        agm_msg = await self._get_agm_message(guild)
        if not agm_msg:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="AGM promotion message is not configured.")
            )

        # Get AGM role
        agm_role = await utils.get_agm_role(guild)

        # Find transaction channel
        franchise_fmt = franchise.lower().replace(" ", "-")
        tchannel_name = f"{franchise_fmt}-transactions"
        log.debug(f"Searching for transaction channel: {tchannel_name}")

        tchannel = discord.utils.get(guild.channels, name=tchannel_name)
        if not tchannel:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"Unable to find transaction channel: **{tchannel_name}**"
                )
            )

        if not isinstance(tchannel, discord.TextChannel):
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"Transaction channel is not a text channel: **{tchannel.mention}**"
                )
            )

        # Add AGM role to player
        await agm.add_roles(agm_role)

        # Add AGM permissions to transaction channel
        agm_overwrite = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            add_reactions=True,
            use_external_emojis=False,
            read_message_history=True,
            read_messages=True,
            use_application_commands=True,
        )

        await tchannel.set_permissions(
            agm, overwrite=agm_overwrite, reason="Player was promoted to AGM"
        )

        # Send promotion message
        await tchannel.send(
            content=f"{agm.mention}\n\n{agm_msg}",
            allowed_mentions=discord.AllowedMentions(users=True),
        )

        embed = BlueEmbed(
            title="AGM Promoted",
            description=f"{agm.mention} has been promoted to an AGM.",
        )

        embed.add_field(name="Franchise", value=franchise, inline=False)
        embed.add_field(
            name="Transaction Channel", value=tchannel.mention, inline=False
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @_agm.command(  # type: ignore
        name="remove", description="Remove an Assistant GM to a franchise."
    )
    @app_commands.describe(franchise="Franchise name", agm="Player to remove from AGM")
    @app_commands.autocomplete(franchise=FranchiseMixIn.franchise_autocomplete)  # type: ignore
    async def _franchise_remove_agm_cmd(
        self,
        interaction: discord.Interaction,
        franchise: str,
        agm: discord.Member,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        # Get AGM role
        agm_role = await utils.get_agm_role(guild)

        # Find transaction channel
        franchise_fmt = franchise.lower().replace(" ", "-")
        tchannel_name = f"{franchise_fmt}-transactions"
        log.debug(f"Searching for transaction channel: {tchannel_name}")

        tchannel = discord.utils.get(guild.channels, name=tchannel_name)
        if not tchannel:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"Unable to find transaction channel: **{tchannel_name}**"
                )
            )

        # Add AGM role to player
        await agm.remove_roles(agm_role)

        await tchannel.set_permissions(
            agm, overwrite=None, reason="Player was removed from AGM"
        )

        embed = BlueEmbed(
            title="AGM Removed", description=f"{agm.mention} has been removed as AGM."
        )

        embed.add_field(name="Franchise", value=franchise, inline=False)
        embed.add_field(
            name="Transaction Channel", value=tchannel.mention, inline=False
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @_stats.command(name="intents", description="Intent to Play statistics")  # type: ignore
    async def _intent_stats_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return
        if not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)

        try:
            next_season = await self.next_season(guild)
        except LeagueNotConfigured:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Not Configured",
                    description="League ID has not been configured for this guild.",
                )
            )
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc))

        if not next_season:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Intent To Play Statistics",
                    description="The next season of RSC has not started yet.",
                )
            )

        if not next_season.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API returned a Season without an ID. Please open a modmail ticket."
                )
            )

        intents = await self.player_intents(guild, season_id=next_season.id)

        log.debug(f"Intent Count: {len(intents)}")
        if not intents:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Intent Statistics",
                    description="There are no intents declared for next season.",
                )
            )

        intent_dict = {
            "Returning": 0,
            "Not Returning": 0,
            "Missing": 0,
        }
        for i in intents:
            if i.returning:
                intent_dict["Returning"] += 1
            elif not i.returning and not i.missing:
                intent_dict["Not Returning"] += 1
            elif i.missing:
                intent_dict["Missing"] += 1
            else:
                log.warning(
                    f"Unknown value in intent data. Player: {i.player.player.discord_id}"
                )

        embed = BlueEmbed(
            title="Intent to Play Statistics",
            description="Next season intent to play statistics",
        )
        embed.add_field(name="Status", value="\n".join(intent_dict.keys()), inline=True)
        embed.add_field(
            name="Count",
            value="\n".join([str(v) for v in intent_dict.values()]),
            inline=True,
        )

        await interaction.followup.send(embed=embed)

    @_stats.command(name="current", description="Current season statistics")  # type: ignore
    async def _current_season_stats_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return
        if not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)

        try:
            season = await self.current_season(guild)
        except LeagueNotConfigured:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Not Configured",
                    description="League ID has not been configured for this guild.",
                )
            )
        except RscException as exc:
            return await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc),
            )

        if not season:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Current Season Stats",
                    description="A season has not been started in this guild.",
                )
            )

        if not season:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API returned a Season without an ID. Please open a modmail ticket."
                )
            )

        lplayers = await self.players(guild, season=season.id, limit=10000)

        total_des = len(lplayers)
        log.debug(f"DE Player Length: {total_des}")
        if not lplayers:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Current Season Stats",
                    description=f"No league players found for season {season.number}",
                )
            )

        status_dict = {}
        for s in Status:
            status_dict[s.full_name] = sum(1 for p in lplayers if p.status == s)

        from pprint import pformat

        log.debug(f"Final Results:\n\n{pformat(status_dict)}")

        embed = BlueEmbed(
            title="Current Season Stats",
            description="RSC stats for next season sign-ups",
        )
        embed.add_field(name="Status", value="\n".join(status_dict.keys()), inline=True)
        embed.add_field(
            name="Count",
            value="\n".join([str(v) for v in status_dict.values()]),
            inline=True,
        )

        await interaction.followup.send(embed=embed)

    @_stats.command(name="signups", description="RSC sign-up statistics")  # type: ignore
    async def _signups_stats_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return
        if not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)

        try:
            next_season = await self.next_season(guild)
        except LeagueNotConfigured:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Not Configured",
                    description="League ID has not been configured for this guild.",
                )
            )
        except RscException as exc:
            return await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc),
            )

        if not next_season:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Sign-up Stats",
                    description="The next season of RSC has not started yet.",
                )
            )

        if not next_season.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API returned a Season without an ID. Please open a modmail ticket."
                )
            )

        lplayers = await self.players(guild, season=next_season.id)

        total_des = len(lplayers)
        log.debug(f"DE Player Length: {total_des}")
        if not lplayers:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="RSC Sign-up Stats",
                    description=f"No league players found for season {next_season.number}",
                )
            )

        status_dict = {}
        for s in Status:
            status_dict[s.full_name] = sum(1 for p in lplayers if p.status == s)

        from pprint import pformat

        log.debug(f"Final Results:\n\n{pformat(status_dict)}")

        embed = BlueEmbed(
            title="Sign-up Stats", description="RSC stats for next season sign-ups"
        )
        embed.add_field(name="Status", value="\n".join(status_dict.keys()), inline=True)
        embed.add_field(
            name="Count",
            value="\n".join([str(v) for v in status_dict.values()]),
            inline=True,
        )

        await interaction.followup.send(embed=embed)

    @_intents.command(name="missingrole", description="Configure the Intent to Play missing discord role")  # type: ignore
    async def _intents_set_missing_role_cmd(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        guild = interaction.guild
        if not guild:
            return

        await self._set_intent_missing_role(guild, role)
        await interaction.response.send_message(
            embed=BlueEmbed(
                title="Intent Missing Role",
                description=f"Intent to Play response missing role has been set to {role.mention}",
            ),
            ephemeral=True,
        )

    @_intents.command(name="missingchannel", description="Configure the Intent to Play missing channel")  # type: ignore
    async def _intents_set_missing_channel_cmd(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        guild = interaction.guild
        if not guild:
            return

        await self._set_intent_channel(guild, channel)
        await interaction.response.send_message(
            embed=BlueEmbed(
                title="Intent Missing Channel",
                description=f"Intent to Play response missing channel has been set to {channel.mention}",
            ),
            ephemeral=True,
        )

    @_intents.command(name="missingmsg", description="Configure the Intent to Play missing message on ping")  # type: ignore
    async def _intents_set_missing_msg_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        intent_modal = IntentMissingModal()
        await interaction.response.send_modal(intent_modal)
        await intent_modal.wait()

        await self._set_intent_missing_message(guild, intent_modal.intent_msg.value)

    @_intents.command(name="populate", description="Apply Intent Missing role to applicable players")  # type: ignore
    async def _intents_populate_role_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        # Check for intent missing role
        intent_role = await self._get_intent_missing_role(guild)
        if not intent_role:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Intent missing role has not been configured."
                )
            )

        # Loading embed
        await interaction.response.send_message(
            embed=YellowEmbed(
                title="Intent Role Sync",
                description="Fetching Intent to Play data and applying roles... This can take some time.",
            ),
            ephemeral=True,
        )

        try:
            next_season = await self.next_season(guild)
            if not next_season:
                return await interaction.edit_original_response(
                    embed=ErrorEmbed(
                        description="The next season of RSC has not started yet.",
                    )
                )

            if not next_season.id:
                return await interaction.edit_original_response(
                    embed=ErrorEmbed(
                        description="API returned a Season without an ID. Please open a modmail ticket."
                    )
                )

            intents = await self.player_intents(
                guild, season_id=next_season.id, missing=True
            )
        except LeagueNotConfigured:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Not Configured",
                    description="League ID has not been configured for this guild.",
                )
            )
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc))

        if not intents:
            return await interaction.edit_original_response(
                embed=GreenEmbed(
                    title="Intent Role Sync",
                    description="There are current no missing intent to play responses.",
                )
            )

        # Clear out original users in role so we don't ping them again
        for rmember in intent_role.members:
            await rmember.remove_roles(intent_role)

        # Loop through intents and add roles
        count = 0
        for i in intents:
            if not (i.player and i.player.player):
                continue

            pid = i.player.player.discord_id
            if not pid:
                continue

            m = guild.get_member(pid)
            if not m:
                continue

            await m.add_roles(intent_role)
            count += 1

        await interaction.edit_original_response(
            embed=BlueEmbed(
                title="Intent Role Sync",
                description=f"Added {intent_role.mention} to {count}/{len(intents)} players",
            )
        )

    @_intents.command(name="ping", description="Send a ping to all players with missing intents")  # type: ignore
    async def _intents_missing_ping_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        intent_msg = await self._get_intent_missing_message(guild)
        if not intent_msg:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Intent missing message has not been configured."
                )
            )

        intent_role = await self._get_intent_missing_role(guild)
        if not intent_role:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Intent missing role has not been configured."
                )
            )

        intent_channel = await self._get_intent_channel(guild)
        if not intent_channel:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Intent missing channel has not been configured."
                )
            )

        await intent_channel.send(
            content=f"{intent_role.mention} {intent_msg}",
            allowed_mentions=discord.AllowedMentions(roles=True, users=True),
        )

    @_inactive.command(name="start", description="Create a channel and ping for inactive check. (FA/DE players only)")  # type: ignore
    async def _admin_inactive_check_start_cmd(
        self, interaction: discord.Interaction, category: discord.CategoryChannel
    ):
        guild = interaction.guild
        if not guild:
            return

        de_role = await utils.get_draft_eligible_role(guild)
        fa_role = await utils.get_free_agent_role(guild)
        gm_role = await utils.get_gm_role(guild)
        agm_role = await utils.get_agm_role(guild)

        if not (de_role and fa_role and gm_role and agm_role):
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Draft Eligible, Free Agent, General Manager, or Assistant GM role does not exist in guild."
                ),
                ephemeral=True,
            )

        conf = self._api_conf[guild.id]
        league_id = self._league[guild.id]

        if not (conf and league_id):
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="This guild does has not configured the API or set a league.",
                ),
                ephemeral=True,
            )

        inactive_channel = discord.utils.get(category.channels, name="inactivity-check")
        if inactive_channel:
            # Already started
            return await interaction.response.send_message(
                embed=YellowEmbed(
                    title="Activity Check",
                    description=f"Activity check has already been started in {inactive_channel.mention}",
                ),
                ephemeral=True,
            )

        # Lock down channel. Only show to DE/FA
        view_perms = discord.PermissionOverwrite(
            view_channel=True,
            read_messages=True,
            send_messages=False,
            add_reactions=False,
            send_messages_in_threads=False,
            create_private_threads=False,
            create_public_threads=False,
        )

        activity_overwrites: MutableMapping[
            discord.Member | discord.Role, discord.PermissionOverwrite
        ] = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
                send_messages=False,
                add_reactions=False,
            ),
            de_role: view_perms,
            fa_role: view_perms,
            gm_role: view_perms,
            agm_role: view_perms,
        }

        # Create channel
        inactive_channel = await category.create_text_channel(
            name="inactivity-check",
            overwrites=activity_overwrites,
            reason="Starting an activity check",
        )

        # Send persistent embed
        ping_fmt = f"{de_role.mention} {fa_role.mention}"
        embed = BlueEmbed(
            title="Activity Check",
            description=(
                "This is an activity check for all draft eligible and free agent players. **This MUST be completed to continue playing in RSC.**\n\n"
                "**Declare your activity with the buttons below.**"
            ),
        )

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        inactive_view = InactiveCheckView(
            guild=guild, league_id=league_id, api_conf=conf
        )

        msg = await inactive_channel.send(
            content=ping_fmt,
            embed=embed,
            view=inactive_view,
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
        log.debug(f"Saving inactive check message ID: {msg.id}")

        # Store message
        await self._set_actvity_check_msg_id(guild, msg_id=msg.id)

        # Make persistent
        self.bot.add_view(inactive_view, message_id=msg.id)

        await interaction.response.send_message(
            embed=GreenEmbed(
                title="Activity Check Started",
                description=f"An activity check has been started: {msg.jump_url}",
            ),
            ephemeral=True,
        )

    @_inactive.command(name="stop", description="End inactivity check and delete channel.")  # type: ignore
    async def _admin_inactive_check_stop_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        msg_id = await self._get_activity_check_msg_id(guild)
        if not msg_id:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="The activity check has not been started."
                ),
                ephemeral=True,
            )

        # Remove channel
        inactive_channel = discord.utils.get(guild.channels, name="inactivity-check")
        if inactive_channel:
            await inactive_channel.delete(reason="Activity check ended")

        # Reset message ID
        await self._set_actvity_check_msg_id(guild, None)

        await interaction.response.send_message(
            embed=GreenEmbed(
                title="Activity Check Ended",
                description="The activity check has ended and the channel was deleted",
            ),
            ephemeral=True,
        )

    @_inactive.command(name="manual", description="Manually change a players activity check status")  # type: ignore
    @app_commands.describe(player="RSC discord member", status="Active or Not Active")
    async def _admin_inactive_check_manual_cmd(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        status: ActivityCheckStatus,
        override: bool = False,
    ):
        guild = interaction.guild
        if not guild:
            return

        if not isinstance(interaction.user, discord.Member):
            return

        if override and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Only admins can process an override.")
            )
            return

        returning = bool(status)
        log.debug(f"Manual Activity Status: {returning}")

        await interaction.response.defer()
        try:
            result = await self.activity_check(
                guild,
                player,
                returning_status=returning,
                executor=interaction.user,
                override=override,
            )
            log.debug(f"Active Result: {result}")
        except RscException as exc:
            return await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )

        if result.missing:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="Player activity check was completed but the API returned **missing**"
                )
            )

        if not result.completed:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="Player activity check was completed but the API returned **not completed**"
                )
            )

        if result.returning_status != returning:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"Player activity check was completed but API returning status does not match submitted status.\n\nSubmitted: {returning}\nReceived: {result.returning_status}"
                )
            )

        if result.returning_status:
            status_fmt = "**returning**"
        else:
            status_fmt = "**not returning**"

        await interaction.followup.send(
            embed=GreenEmbed(
                title="Active Status Updated",
                description=f"{player.mention} has been marked as {status_fmt}",
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

    async def _set_agm_message(self, guild: discord.Guild, value: str):
        await self.config.custom("Admin", str(guild.id)).AgmMessage.set(value)

    async def _get_agm_message(self, guild: discord.Guild) -> str:
        return await self.config.custom("Admin", str(guild.id)).AgmMessage()

    async def _set_dates(self, guild: discord.Guild, value: str):
        await self.config.custom("Admin", str(guild.id)).Dates.set(value)

    async def _get_dates(self, guild: discord.Guild) -> str:
        return await self.config.custom("Admin", str(guild.id)).Dates()

    async def _set_intent_channel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ):
        await self.config.custom("Admin", str(guild.id)).IntentChannel.set(channel.id)

    async def _get_intent_channel(
        self, guild: discord.Guild
    ) -> discord.TextChannel | None:
        channel_id = await self.config.custom("Admin", str(guild.id)).IntentChannel()
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return None
        log.debug(f"Intent Channel: {channel}")
        return channel

    async def _set_intent_missing_role(self, guild: discord.Guild, role: discord.Role):
        await self.config.custom("Admin", str(guild.id)).IntentMissingRole.set(role.id)

    async def _get_intent_missing_role(
        self, guild: discord.Guild
    ) -> discord.Role | None:
        role_id = await self.config.custom("Admin", str(guild.id)).IntentMissingRole()
        role = guild.get_role(role_id)
        log.debug(f"Intent Missing Role: {role}")
        return role

    async def _set_intent_missing_message(self, guild: discord.Guild, msg: str):
        await self.config.custom("Admin", str(guild.id)).IntentMissingMsg.set(msg)

    async def _get_intent_missing_message(self, guild: discord.Guild) -> str | None:
        return await self.config.custom("Admin", str(guild.id)).IntentMissingMsg()

    async def _set_actvity_check_msg_id(self, guild: discord.Guild, msg_id: int | None):
        await self.config.custom("Admin", str(guild.id)).ActivityCheckMsgId.set(msg_id)

    async def _get_activity_check_msg_id(self, guild: discord.Guild) -> int | None:
        return await self.config.custom("Admin", str(guild.id)).ActivityCheckMsgId()
