from functools import wraps

import discord

from rsc.abc import RSCMixIn


def apicall(f):
    @wraps(f)
    def wrapper(self: RSCMixIn, guild: discord.Guild, *args, **kwargs):
        if not self._league.get(guild.id):
            raise ValueError(f"[{guild.name}] Guild does not have a league ID.")

        if not self._api_conf.get(guild.id):
            raise ValueError(f"[{guild.name}] Guild has not configured API settings.")

        return f(self, *args, **kwargs)

    return wrapper
