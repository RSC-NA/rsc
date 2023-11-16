import discord

from discord.app_commands import Transformer, TransformerError
from discord import AppCommandOptionType
from datetime import datetime

from typing import List


class MemberTransformer(Transformer):
    """Transform space delimited string of Discord IDs into List[discord.Member] (Guild Only)"""

    async def transform(
        self, interaction: discord.Interaction, value: str
    ) -> List[discord.Member]:
        members = []
        mlist = value.split(" ")

        for m in mlist:
            # Validate string is int
            if not m.isdigit():
                raise TransformerError(m, AppCommandOptionType.user, self)

            member = interaction.guild.get_member(int(m))
            if not member:
                raise TransformerError(m, AppCommandOptionType.user, self)
            members.append(member)
        return members

class DateTransformer(Transformer):
    """Transform a string into a datetime object (ISO 8601 format)"""

    async def transform(
        self, interaction: discord.Interaction, value: str
    ) -> datetime:
        try:
            return datetime.fromisoformat(value)
        except:
            raise TransformerError(value, AppCommandOptionType.string, self)