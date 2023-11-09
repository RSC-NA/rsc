import discord

from rsc.const import GM_ROLE


def remove_prefix(member: discord.Member) -> str:
    result = member.display_name.split(" | ")
    if len(result) != 2:
        raise ValueError(f"Unable to remove prefix from {member.display_name}")
    return result[1]


def is_gm(member: discord.Member) -> bool:
    for role in member.roles:
        if role.name == GM_ROLE:
            return True
    return False
