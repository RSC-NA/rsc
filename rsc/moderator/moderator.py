import logging

import discord
from redbot.core import app_commands

from rsc.abc import RSCMixIn
from rsc.enums import ModActionType
from rsc.utils import utils

log = logging.getLogger("red.rsc.moderator")


class ModeratorMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing ModeratorMixIn")
        super().__init__()

    # Top Level Group

    _mod = app_commands.Group(
        name="mod",
        description="Moderator commands and configuration",
        guild_only=True,
        default_permissions=discord.Permissions(
            kick_members=True, ban_members=True, manage_roles=True
        ),
    )

    # Mod Commands

    @_mod.command(name="notify", description="Notify a user via direct message")  # type: ignore
    @app_commands.describe(member="Discord member to notify")
    async def _mod_notify(
        self, interaction: discord.Interaction, member: discord.Member
    ):
        await utils.not_implemented(interaction)

    @_mod.command(  # type: ignore
        name="mute",
        description="Mute a player for a period of time (Default: 30 minutes)",
    )
    @app_commands.describe(
        member="Discord member to mute",
        days="Number of days",
        hours="Number of hours",
        minutes="Number of minutes",
    )
    async def _mod_mute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
    ):
        await utils.not_implemented(interaction)

    @_mod.command(name="kick", description="Kick a player from the RSC discord server")  # type: ignore
    @app_commands.describe(member="Discord member to kick from server")
    async def _mod_kick(self, interaction: discord.Interaction, member: discord.Member):
        await utils.not_implemented(interaction)

    @_mod.command(name="ban", description="Ban a player from the RSC discord server")  # type: ignore
    @app_commands.describe(
        member="Discord member to ban from server",
        days="Number of days",
        hours="Number of hours",
        minutes="Number of minutes",
    )
    async def _mod_ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
    ):
        await utils.not_implemented(interaction)

    @_mod.command(name="strike", description="Issue a strike to a player")  # type: ignore
    @app_commands.describe(
        member="Discord member to strike",
        rule="Strike rule #",
        action="Perform a optional moderator action afterwards (Ex: Mute)",
        days="Number of days",
        hours="Number of hours",
        minutes="Number of minutes",
    )
    async def _mod_strike(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        rule: str,
        action: ModActionType | None = None,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
    ):
        await utils.not_implemented(interaction)

    @_mod.command(  # type: ignore
        name="history",
        description="Display mod action history for a player (Default: Last 90 days)",
    )
    @app_commands.describe(
        member="Discord member to fetch history for",
        days="Past number of days to display history for",
    )
    async def _mod_history(
        self, interaction: discord.Interaction, member: discord.Member, days: int = 90
    ):
        await utils.not_implemented(interaction)

    @_mod.command(  # type: ignore
        name="recent",
        description="Display all recent moderator actions (Default: Last 30 days)",
    )
    @app_commands.describe(days="Past number of days to display history for")
    async def _mod_recent(self, interaction: discord.Interaction, days: int = 30):
        await utils.not_implemented(interaction)

    @_mod.command(name="rules", description="Display list of RSC rules")  # type: ignore
    async def _mod_rules(self, interaction: discord.Interaction):
        await utils.not_implemented(interaction)
