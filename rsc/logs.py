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

        parts.append(msg)
        msg = " ".join(parts)

        return msg, kwargs
