from __future__ import annotations

from functools import wraps
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import discord
    from rsc.protocols import RSCProtocol


def apicall(f):  # noqa: ANN001
    @wraps(f)
    def wrapper(self: RSCProtocol, guild: discord.Guild, *args, **kwargs):
        if not self._league.get(guild.id):
            raise ValueError(f"[{guild.name}] Guild does not have a league ID.")

        if not self._api_conf.get(guild.id):
            raise ValueError(f"[{guild.name}] Guild has not configured API settings.")

        return f(self, *args, **kwargs)

    return wrapper
