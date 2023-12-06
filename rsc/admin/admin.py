import discord
import logging


from redbot.core import app_commands, checks, commands

from rscapi import ApiClient, MembersApi
from rscapi.exceptions import ApiException
from rscapi.models.tier import Tier
from rscapi.models.members_list200_response import MembersList200Response
from rscapi.models.member import Member
from rscapi.models.elevated_role import ElevatedRole
from rscapi.models.franchise import Franchise
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.league_player import LeaguePlayer

from rsc.abc import RSCMixIn
from rsc.exceptions import RscException
from rsc.tiers import TierMixIn
from rsc.const import LEAGUE_ROLE, MUTED_ROLE, FRANCHISE_ROLE_PERMS
from rsc.embeds import ErrorEmbed, SuccessEmbed, ApiExceptionErrorEmbed, BlueEmbed
from rsc.enums import Status
from rsc.admin.views import ConfirmSyncView
from rsc.utils import utils

from typing import List, Dict, Tuple, TypedDict, Optional

log = logging.getLogger("red.rsc.admin")


class AdminMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing AdminMixIn")
        super().__init__()

    # Top Level Group

    _admin = app_commands.Group(
        name="admin",
        description="Admin only commands for RSC",
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

    # Member Commands

    @_members.command(name="create", description="Create an RSC member in the API")
    @app_commands.describe(
        member="Discord member being added",
        rsc_name="RSC player name (Defaults to members display name)",
    )
    async def _member_create(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        rsc_name: Optional[str] = None,
    ):
        try:
            lp = await self.create_member(
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

    @_members.command(name="delete", description="Delete an RSC member in the API")
    async def _member_delete(
        self, interaction: discord.Interaction, member: discord.Member
    ):
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

    @_members.command(
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
        rsc_name: Optional[str] = None,
        discord_username: Optional[str] = None,
        discord_id: Optional[int] = None,
        limit: app_commands.Range[int, 1, 64] = 10,
        offset: app_commands.Range[int, 0, 64] = 0,
    ):
        if not (rsc_name or discord_username or discord_id):
            await interaction.response.send_message(
                "You must specify at least one search option.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        ml = await self.members(
            interaction.guild,
            rsc_name=rsc_name,
            discord_username=discord_username,
            discord_id=discord_id,
            limit=limit,
            offset=offset,
        )

        league_id = self._league[interaction.guild.id]
        m_fmt = []
        for m in ml:
            x = interaction.guild.get_member(m.discord_id)
            l: LeaguePlayer = next(
                (i for i in m.player_leagues if i.league.id == league_id), None
            )
            m_fmt.append(
                (
                    x.mention if x else m.rsc_name,
                    m.discord_id,
                    Status(l.status).full_name() if l else "Spectator",
                )
            )

        embed = BlueEmbed(
            title="RSC Member Results",
            description="The following members matched the specified criteria",
        )
        embed.add_field(
            name="Member", value="\n".join([x[0] for x in m_fmt]), inline=True
        )
        embed.add_field(
            name="ID", value="\n".join([str(x[1]) for x in m_fmt]), inline=True
        )
        embed.add_field(
            name="Status", value="\n".join([x[2] for x in m_fmt]), inline=True
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    # Validate Commands

    @_sync.command(
        name="franchiseroles",
        description="Check if all franchise roles exist. If not, create them.",
    )
    async def _validate_franchise_roles(
        self,
        interaction: discord.Interaction,
    ):
        added: List[discord.Role] = []
        existing: List[discord.Role] = []
        fixed: List[discord.Role] = []

        sync_view = ConfirmSyncView(interaction)
        await sync_view.prompt()
        franchises = await self.franchises(interaction.guild)
        await sync_view.wait()

        if not sync_view.result:
            return

        log.debug(f"Guild Feature: {interaction.guild.features}")
        icons_allowed = "ROLE_ICONS" in interaction.guild.features
        for f in franchises:
            fname = f"{f.name} ({f.gm.rsc_name})"
            frole = await utils.franchise_role_from_name(interaction.guild, f.name)
            if frole:
                log.debug(
                    f"[{interaction.guild.name}] Found franchise role: {frole.name}"
                )
                if frole.name != fname:
                    log.info(
                        f"[{interaction.guild.name}] Changing franchise role: {frole.name}"
                    )
                    await frole.edit(name=fname)
                    fixed.append(frole)
                else:
                    existing.append(frole)
            else:
                log.info(
                    f"[{interaction.guild.name}] Creating new franchise role: {fname}"
                )
                nrole = await interaction.guild.create_role(
                    name=fname,
                    hoist=True,
                    display_icon=f.logo if icons_allowed else None,
                    permissions=FRANCHISE_ROLE_PERMS,
                    reason="Syncing franchise roles from API",
                )
                added.append(nrole)

        added.sort(key=lambda x: x.name)
        existing.sort(key=lambda x: x.name)
        fixed.sort(key=lambda x: x.name)
        embed = BlueEmbed(
            title="Franchise Role Sync",
            description=f"Successfully synced {len(franchises)} franchise roles to the RSC discord."
        )
        embed.add_field(name="Found", value="\n".join([r.mention for r in existing]), inline=True)
        embed.add_field(name="Fixed", value="\n".join([r.mention for r in fixed]), inline=True)
        embed.add_field(name="Created", value="\n".join([r.mention for r in added]), inline=True)

        await interaction.edit_original_response(embed=embed)
