import logging

import discord


class GuildLogAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        guild = kwargs.pop("guild", None)
        if guild and isinstance(guild, discord.Guild):
            return "[%s] %s" % (guild.name, msg), kwargs

        return msg, kwargs
