import logging
from functools import wraps
from typing import TYPE_CHECKING

import discord

from rsc.embeds import ErrorEmbed
from rsc.enums import StaffPositions
from rsc.exceptions import RscException

if TYPE_CHECKING:
    from rsc.abc import RSCMixIn

log = logging.getLogger("red.rsc.checks")


def bot_owner_required():
    """Restrict an app command to the bot owner(s).

    `manage_guild` controls whether a command is *visible*, but some settings
    (API credentials, the event cursor) are destructive enough that guild
    managers should not be able to change them. This gates on Red's owner list,
    which is the bot operator rather than any guild role.
    """

    def decorator(f):  # noqa: ANN001
        @wraps(f)
        async def bot_owner_wrapper(cls: "RSCMixIn", interaction: discord.Interaction, *args, **kwargs):
            if not await cls.bot.is_owner(interaction.user):
                return await interaction.response.send_message(
                    embed=ErrorEmbed(description="This command is restricted to the bot owner."),
                    ephemeral=True,
                )
            return await f(cls, interaction, *args, **kwargs)

        # Marker so the gate is introspectable. `wraps` copies `__name__` from the
        # wrapped command, so there is otherwise no way to tell a gated command apart.
        bot_owner_wrapper.__rsc_owner_only__ = True  # ty: ignore[unresolved-attribute]
        return bot_owner_wrapper

    return decorator


def elevated_role_required(*positions: StaffPositions):
    """Restrict an app command to guild managers or holders of an API elevated role.

    A member passes if they have the Discord `manage_guild` permission, or if the
    RSC API reports they hold one of `positions` in the guild's league.

    `manage_guild` is checked first so server admins keep working without an API
    round trip. Any API failure is treated as "no roles held", so the check fails
    closed rather than granting access on an outage.
    """
    allowed = {p.value for p in positions}

    def decorator(f):  # noqa: ANN001
        @wraps(f)
        async def elevated_role_wrapper(cls: "RSCMixIn", interaction: discord.Interaction, *args, **kwargs):
            guild = interaction.guild
            if not (guild and isinstance(interaction.user, discord.Member)):
                return None

            # Guild managers always pass. No API call needed.
            if interaction.user.guild_permissions.manage_guild:
                return await f(cls, interaction, *args, **kwargs)

            try:
                held = await cls.elevated_positions(guild, interaction.user.id)
            except RscException as exc:
                log.warning(f"Unable to fetch elevated roles for {interaction.user.id}, denying access: {exc}")
                held = frozenset()

            if not (held & allowed):
                return await interaction.response.send_message(
                    embed=ErrorEmbed(description="You do not have permission to run this command."),
                    ephemeral=True,
                )

            return await f(cls, interaction, *args, **kwargs)

        # Marker so the gate is introspectable. `wraps` copies `__name__` from the
        # wrapped command, so there is otherwise no way to tell a gated command apart.
        elevated_role_wrapper.__rsc_elevated_positions__ = frozenset(allowed)  # ty: ignore[unresolved-attribute]
        return elevated_role_wrapper

    return decorator
