import logging

import discord


class GuildLogAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):  # noqa: ANN001
        guild = kwargs.pop("guild", None)
        if guild and isinstance(guild, discord.Guild):
            return f"[{guild.name}] {msg}", kwargs

        return msg, kwargs
