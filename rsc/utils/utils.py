import discord
import logging
from discord.ext.commands import Greedy
from discord.app_commands import Transformer, Transform, TransformerError
from discord.ext.commands import MemberConverter
from discord import AppCommandOptionType
import re
from redbot.core import app_commands, checks

from rscapi.models.league_player import LeaguePlayer

from rsc.transformers import MemberTransformer
from rsc.const import (
    GM_ROLE,
    CAPTAIN_ROLE,
    FREE_AGENT_ROLE,
    SUBBED_OUT_ROLE,
    FORMER_GM_ROLE,
    TROPHY_EMOJI,
    STAR_EMOJI,
)
from rsc.abc import RSCMixIn
from rsc.embeds import ErrorEmbed, SuccessEmbed, ExceptionErrorEmbed

from typing import Optional, List, overload


log = logging.getLogger("red.rsc.utils")

FRANCHISE_ROLE_REGEX = re.compile(r"^\w[\w\s]+?\(\w[\w\s]+?\)$")


async def not_implemented(interaction: discord.Interaction):
    await interaction.response.send_message("**Not Implemented**", ephemeral=True)


async def get_captain_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=CAPTAIN_ROLE)
    if not r:
        log.error(f"[{guild.name}] Expected role does not exist: {CAPTAIN_ROLE}")
        raise ValueError(f"[{guild.name}] Expected role does not exist: {CAPTAIN_ROLE}")
    return r


async def get_free_agent_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=FREE_AGENT_ROLE)
    if not r:
        log.error(f"[{guild.name}] Expected role does not exist: {FREE_AGENT_ROLE}")
        raise ValueError(
            f"[{guild.name}] Expected role does not exist: {FREE_AGENT_ROLE}"
        )
    return r


async def get_gm_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=GM_ROLE)
    if not r:
        log.error(f"[{guild.name}] Expected role does not exist: {GM_ROLE}")
        raise ValueError(f"[{guild.name}] Expected role does not exist: {GM_ROLE}")
    return r


async def get_subbed_out_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=SUBBED_OUT_ROLE)
    if not r:
        log.error(f"[{guild.name}] Expected role does not exist: {SUBBED_OUT_ROLE}")
        raise ValueError(
            f"[{guild.name}] Expected role does not exist: {SUBBED_OUT_ROLE}"
        )
    return r


async def get_former_gm_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=FORMER_GM_ROLE)
    if not r:
        log.error(f"[{guild.name}] Expected role does not exist: {FORMER_GM_ROLE}")
        raise ValueError(
            f"[{guild.name}] Expected role does not exist: {FORMER_GM_ROLE}"
        )
    return r


async def remove_prefix(member: discord.Member) -> str:
    """Remove team prefix from guild members display name"""
    result = member.display_name.split(" | ")

    if len(result) == 2:
        return result[1]
    elif len(result) == 1:
        return result[0]  # Assume no prefix for some reason

    raise ValueError(f"Unable to remove prefix from {member.display_name}")

async def give_fa_prefix(member: discord.Member): 
    new_nick = f"FA | {await remove_prefix(member)}"
    await member.edit(nick=new_nick)

async def has_gm_role(member: discord.Member) -> bool:
    """Check if user has General Manager role in guild"""
    for role in member.roles:
        if role.name == GM_ROLE:
            return True
    return False


async def member_from_rsc_name(
    guild: discord.Guild, name: str
) -> Optional[discord.Member]:
    """Get guild member by rsc name ("nickm"). Not recommended."""
    for m in guild.members:
        try:
            n = await remove_prefix(m)
            if n.startswith(name):
                return m
        except ValueError:
            """Handle former player or spectator"""
            if n.startswith(name):
                return m
            continue
    return None


async def get_gm_by_role(franchise_role: discord.Role) -> Optional[discord.Member]:
    """Get GM from guild franchise role"""
    for member in franchise_role.members:
        if has_gm_role(member):
            return member
    return None


async def role_by_name(guild: discord.Guild, name: str) -> Optional[discord.Role]:
    """Get a guild discord role by name"""
    return discord.utils.get(guild.roles, name=name)


async def franchise_role_from_name(
    guild: discord.Guild, franchise_name: str
) -> Optional[discord.Role]:
    """Get guild franchise role from franchise name (Ex: "The Garden")"""
    for role in guild.roles:
        if role.name.lower().startswith(franchise_name.lower()):
            return role
    return None


async def franchise_role_from_league_player(
    guild: discord.Guild, player: LeaguePlayer
) -> discord.Role:
    """Return a franchise discord.Role from `LeaguePlayer` object"""
    rname = f"{player.team.franchise.name} ({player.team.franchise.gm.rsc_name})"
    r = discord.utils.get(guild.roles, name=rname)
    if not r:
        log.error(f"[{guild.name}] Expected franchise role does not exist: {rname}")
        raise ValueError(
            f"[{guild.name}] Expected franchise role does not exist: {rname}"
        )
    return r


async def tier_color_by_name(guild: discord.Guild, name: str) -> discord.Color:
    """Return tier color from role (Defaults to blue if not found)"""
    tier_role = discord.utils.get(guild.roles, name=name)
    if tier_role:
        return tier_role.color
    return discord.Color.blue()


async def is_guild_interaction(interaction: discord.Interaction) -> bool:
    """Check if interaction was sent from guild. Mostly for type issues since guild_only() exists"""
    if interaction.guild:
        return True
    return False


async def update_prefix_for_franchise_role(role: discord.Role, prefix: str):
    """Update the prefix for all role members"""
    for m in role.members:
        name = await remove_prefix(m)
        await m.edit(nick=f"{prefix} | {name}")


async def get_tier_role(guild: discord.Guild, name: str) -> discord.Role:
    """Return discord.Role for a tier"""
    r = discord.utils.get(guild.roles, name=name)
    if not r:
        log.error(f"[{guild.name}] Expected tier role does not exist: {name}")
        raise ValueError(f"[{guild.name}] Expected tier role does not exist: {name}")
    return r


async def get_tier_fa_role(guild: discord.Guild, name: str) -> discord.Role:
    """Return FA discord.Role for a tier"""
    r = discord.utils.get(guild.roles, name=f"{name}FA")
    if not r:
        log.error(f"[{guild.name}] Expected tier FA role does not exist: {name}FA")
        raise ValueError(
            f"[{guild.name}] Expected tier FA role does not exist: {name}FA"
        )
    return r

async def franchise_role_from_disord_member(member: discord.Member) -> Optional[discord.Role]:
    for r in member.roles:
        if FRANCHISE_ROLE_REGEX.match(r.name):
            return r
    return None

async def emoji_from_prefix(guild: discord.Guild, prefix: str) -> Optional[discord.Emoji]:
    return discord.utils.get(guild.emojis, name=prefix)

async def trophy_count(member: discord.Member) -> int:
    return member.display_name.count(TROPHY_EMOJI)

async def star_count(member: discord.Member) -> int:
    return member.display_name.count(STAR_EMOJI)


class UtilsMixIn(RSCMixIn):
    @app_commands.command(
        name="getid",
        description='Get the discord ID of a user. (Return: "name:username:id")',
    )
    @app_commands.guild_only()
    async def _getid(self, interaction: discord.Interaction, member: discord.Member):
        """Get the discord ID of a user"""
        await interaction.response.send_message(
            content=f"`{member.display_name}:{member.name}:{member.id}`",
            ephemeral=True,
        )

    @app_commands.command(
        name="getallwithrole",
        description="Get all users with the specified role(s). (Max 3 roles)",
    )
    @app_commands.guild_only()
    async def _getallwithrole(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        role2: Optional[discord.Role],
        role3: Optional[discord.Role],
    ):
        desc = f"Role(s): {role.mention}"
        if not (role2 or role3):
            results = role.members
        else:
            members = set(role.members)
            if role2:
                members = members.intersection(role2.members)
                desc += f", {role2.mention}"
            if role3:
                members = members.intersection(role3.members)
                desc += f", {role3.mention}"
            results = sorted(members, key=lambda x: x.display_name)

        # Check for character max being exceeded (6000 total in embed or 1024 per field)
        nicks = "\n".join([r.display_name for r in results])
        usernames = ("\n".join([r.name for r in results]),)
        ids = "\n".join(str(r.id) for r in results)

        if len(nicks) > 1024 or len(usernames) > 1024 or len(ids) > 1024:
            msg = "\n".join([f"{p.display_name}:{p.name}:{p.id}" for p in members])
            if len(msg) > 6000:
                await interaction.response.send_message(
                    content="Total results exceed 6000 characters. Please be more specific.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(f"```msg```")
        else:
            embed = discord.Embed(
                title="Matching Players",
                description=desc,
                color=discord.Color.blue(),
            )
            embed.add_field(
                name="Player", value="\n".join(r.mention for r in results), inline=True
            )
            embed.add_field(
                name="Username", value="\n".join(r.name for r in results), inline=True
            )
            embed.add_field(
                name="ID", value="\n".join(str(r.id) for r in results), inline=True
            )

            embed.set_footer(text=f"Found {len(results)} matching player(s).")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="addrole", description="Add a role to the specified user"
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def _addrole(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        member: discord.Member,
    ):
        try:
            await member.add_roles(role)
            await interaction.response.send_message(
                embed=SuccessEmbed(
                    description=f"Added {role.mention} role to {member.mention}"
                ),
                ephemeral=True,
            )
        except discord.Forbidden as exc:
            await interaction.response.send_message(
                embed=ExceptionErrorEmbed(
                    description=f"Unable to add {role.mention} role to {member.mention}",
                    exc_message=exc.text,
                ),
                ephemeral=True,
            )

    @app_commands.command(
        name="bulkaddrole", description="Add a role a list of user(s)"
    )
    @app_commands.describe(
        members='Space delimited discord IDs to apply role. (Example: "138778232802508801 352600418062303244 207266416355835904")'
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def _bulkaddrole(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        members: Transform[List[discord.Member], MemberTransformer],
    ):
        log.debug(members)

        # Avoid discord field limits (1024 max)
        if len(members) >= 1024:
            await interaction.response.send_message(
                content=f"Unable to process more than 1024 users at a time. (Total: {len(members)})",
                ephemeral=True,
            )
            return

        success: List[discord.Member] = []
        failed: List[discord.Member] = []
        for m in members:
            try:
                await m.add_roles(role)
                success.append(m)
            except:
                failed.append(m)

        embed = discord.Embed(
            title="Bulk Role Add",
            description=f"Added {role.mention} to the following user(s).",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Succeeded",
            value="\n".join(f"{s.mention}" for s in success),
            inline=True,
        )
        embed.add_field(
            name="Failed", value="\n".join(f"{f.mention}" for f in failed), inline=True
        )
        embed.set_footer(text=f"Applied role to {len(success)}/{len(members)} members.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="removerole", description="Remove a role to the specified user"
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def _removerole(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        member: discord.Member,
    ):
        try:
            await member.remove_roles(role)
            await interaction.response.send_message(
                embed=SuccessEmbed(
                    description=f"Removed {role.mention} role to {member.mention}"
                ),
                ephemeral=True,
            )
        except discord.Forbidden as exc:
            await interaction.response.send_message(
                embed=ExceptionErrorEmbed(
                    description=f"Unable to remove {role.mention} role to {member.mention}",
                    exc_message=exc.text,
                ),
                ephemeral=True,
            )

    @app_commands.command(
        name="bulkremoverole", description="Remove a role a list of user(s)"
    )
    @app_commands.describe(
        members='Space delimited discord IDs to remove role. (Example: "138778232802508801 352600418062303244 207266416355835904")'
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def _bulkremoverole(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        members: Transform[List[discord.Member], MemberTransformer],
    ):
        # Avoid discord field limits (1024 max)
        if len(members) >= 1024:
            await interaction.response.send_message(
                content=f"Unable to process more than 1024 users at a time. (Total: {len(members)})",
                ephemeral=True,
            )
            return

        success: List[discord.Member] = []
        failed: List[discord.Member] = []
        for m in members:
            try:
                await m.remove_roles(role)
                success.append(m)
            except:
                failed.append(m)

        embed = discord.Embed(
            title="Bulk Role Removal",
            description=f"Removed {role.mention} to the following user(s).",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Succeeded",
            value="\n".join(f"{s.mention}" for s in success),
            inline=True,
        )
        embed.add_field(
            name="Failed", value="\n".join(f"{f.mention}" for f in failed), inline=True
        )
        embed.set_footer(
            text=f"Removed role from {len(success)}/{len(members)} members."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
