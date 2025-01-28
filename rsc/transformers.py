import logging
import re
from datetime import datetime

import discord
from discord import AppCommandOptionType
from discord.app_commands import Transformer, TransformerError

log = logging.getLogger("red.rsc.transformers")

_ID_REGEX = re.compile(r"([0-9]{15,20})$")


class MemberTransformer(Transformer):
    """Transform space delimited string of Discord IDs into List[discord.Member] (Guild Only)"""

    async def transform(self, interaction: discord.Interaction, value: str) -> list[discord.Member]:
        if not interaction.guild:
            return []

        members = []
        mlist = value.strip().split(" ")

        for m in mlist:
            # Validate string is int
            if not m.isdigit():
                raise TransformerError(m, AppCommandOptionType.user, self)

            member = interaction.guild.get_member(int(m))
            if not member:
                raise TransformerError(m, AppCommandOptionType.user, self)
            members.append(member)
        return members


class GreedyMemberTransformer(Transformer):
    """Converts to a :class:`~discord.Member`.

    All lookups are via the local guild. Ported from commands.MemberConverter

    The lookup strategy is as follows (in order):

    1. Lookup by ID.
    2. Lookup by mention.
    3. Lookup by username#discriminator (deprecated).
    4. Lookup by username#0 (deprecated, only gets users that migrated from their discriminator).
    5. Lookup by guild nickname.
    6. Lookup by global name.
    7. Lookup by user name.
    """

    @staticmethod
    def _get_id_match(argument: str) -> re.Match | None:
        return _ID_REGEX.match(argument)

    async def query_member_named(self, guild: discord.Guild, argument: str) -> discord.Member | None:
        cache = guild._state.member_cache_flags.joined
        username, _, discriminator = argument.rpartition("#")

        # If # isn't found then "discriminator" actually has the username
        if not username:
            discriminator, username = username, discriminator

        if discriminator == "0" or (len(discriminator) == 4 and discriminator.isdigit()):
            lookup = username
            predicate = (  # noqa: E731
                lambda m: m.name == username and m.discriminator == discriminator
            )
        else:
            lookup = argument
            predicate = (  # noqa: E731
                lambda m: argument in (m.nick, m.global_name, m.name)
            )

        members = await guild.query_members(lookup, limit=100, cache=cache)
        return discord.utils.find(predicate, members)

    async def transform(self, interaction: discord.Interaction, value: str) -> list[discord.Member]:
        guild = interaction.guild

        if not guild:
            return []

        members = []
        mlist = value.strip().split(" ")

        for m in mlist:
            result = None
            match = self._get_id_match(m) or re.match(r"<@!?([0-9]{15,20})>$", value)
            if match is None:
                # not a mention...
                result = guild.get_member_named(m)
            else:
                user_id = int(match.group(1))
                if user_id:
                    result = guild.get_member(user_id)
                    if not result and (interaction.message and isinstance(interaction.message.mentions, discord.Member | discord.User)):
                        result = discord.utils.get(interaction.message.mentions, id=user_id)

            if not isinstance(result, discord.Member):
                result = await self.query_member_named(guild, m)

            if result:
                members.append(result)
            else:
                raise TransformerError(m, AppCommandOptionType.user, self)

        return members


class DateTransformer(Transformer):
    """Transform a string into a datetime object (ISO 8601 format)"""

    async def transform(self, interaction: discord.Interaction, value: str) -> datetime:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            raise TransformerError(value, AppCommandOptionType.string, self)
