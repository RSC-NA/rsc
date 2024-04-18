from functools import wraps

import discord

from rsc.abc import RSCMixIn
from rsc.embeds import ErrorEmbed


def apicall(f):
    @wraps(f)
    def wrapper(self: RSCMixIn, guild: discord.Guild, *args, **kwargs):
        if not self._league.get(guild.id):
            raise ValueError(f"[{guild.name}] Guild does not have a league ID.")

        if not self._api_conf.get(guild.id):
            raise ValueError(f"[{guild.name}] Guild has not configured API settings.")

        return f(self, *args, **kwargs)

    return wrapper


def active_combines(f):
    @wraps(f)
    async def combine_wrapper(
        cls: RSCMixIn, interaction: discord.Interaction, *args, **kwargs
    ):
        if not interaction.guild:
            return

        active = await cls._get_combines_active(interaction.guild)
        if not active:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines are not currently active."),
                ephemeral=True,
            )

        api_url = await cls._get_combines_api(interaction.guild)
        if not api_url:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines API has not been configured."),
                ephemeral=True,
            )

        return await f(cls, interaction, *args, **kwargs)

    return combine_wrapper
