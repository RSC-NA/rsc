import discord
import re

from typing import Optional

from rsc.const import GM_ROLE

FRANCHISE_ROLE_REGEX = re.compile(r"^[\w\s]+\(\w+\)$")


async def remove_prefix(member: discord.Member) -> str:
    result = member.display_name.split(" | ")
    if len(result) != 2:
        raise ValueError(f"Unable to remove prefix from {member.display_name}")
    return result[1]


async def is_gm(member: discord.Member) -> bool:
    for role in member.roles:
        if role.name == GM_ROLE:
            return True
    return False


async def get_gm(franchise_role: discord.Role) -> Optional[discord.Member]:
    for member in franchise_role.members:
        if is_gm(member):
            return member
    return None


async def get_franchise_role_from_name(
    guild: discord.Guild, franchise_name: str
) -> Optional[discord.Role]:
    for role in guild.roles:
        if role.name.lower().startswith(franchise_name.lower()):
            return role
    return None
