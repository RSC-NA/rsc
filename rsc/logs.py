import logging

import discord

from rscapi.models.match import Match


class GuildLogAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):  # noqa: ANN001
        guild = kwargs.pop("guild", None)
        parts = []
        if guild and isinstance(guild, discord.Guild):
            parts.append(f"[{guild.name}]")

        match = kwargs.pop("match", None)
        if match and isinstance(match, Match):
            parts.append(f"[Match {match.id}]")

        if isinstance(msg, str) or hasattr(msg, "__str__"):
            parts.append(msg)
            msg = " ".join(parts)
        else:
            msg = f"Log message is not a string or does not have __str__ method. Type: {type(msg)}"

        return msg, kwargs
