import logging
import os

import aiofiles
import discord
from redbot.core import app_commands

from rsc.abc import RSCMixIn
from rsc.embeds import ErrorEmbed

log = logging.getLogger("red.rsc.developer")

BUFMAX = 1984


class DeveloperMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing DeveloperMixIn")
        super().__init__()

    # Groups

    _log_group = app_commands.Group(
        name="logs",
        description="Display information from bot log files",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # Commands

    @_log_group.command(  # type: ignore
        name="tail",
        description=f"Tail the latest log file (Max {BUFMAX} bytes)",
    )
    @app_commands.guild_only
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _logs_tail_cmd(
        self,
        interaction: discord.Interaction,
    ):
        log_file = await self.get_latest_log_file()
        if not log_file:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Unable to find valid logging RotatingFileHandler."
                )
            )
            return

        async with aiofiles.open(log_file, mode="rb") as fd:
            await fd.seek((-1 * BUFMAX), os.SEEK_END)
            data = await fd.read(BUFMAX)

        await interaction.response.send_message(
            content=f"```\n{data.decode('utf-8')}\n```", ephemeral=True
        )

    # Functions

    async def get_latest_log_file(self) -> str | None:
        """Return path to latest log handler file"""
        latest_log_path = None
        root_logger = logging.getLogger()
        for fh in root_logger.handlers:
            if not isinstance(fh, logging.handlers.RotatingFileHandler):  # type: ignore
                log.debug("Not a file handler...")
                continue
            if fh.baseStem == "latest":
                latest_log_path = fh.baseFilename
                break

        log.debug(f"Latest log file: {latest_log_path}")
        return latest_log_path
