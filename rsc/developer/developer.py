import io
import logging
import os
import re
import time
from datetime import UTC, datetime

import aiofiles
import discord
from redbot.core import app_commands
from redbot.logging import RotatingFileHandler

from rsc.abc import RSCMixIn
from rsc.developer.recorder import ExceptionRecorder
from rsc.embeds import BlueEmbed, ErrorEmbed

log = logging.getLogger("red.rsc.developer")

BUFMAX = 1984
MESSAGE_MAX = 2000
CHOICE_NAME_MAX = 100
TRACEBACK_MESSAGE_MAX = 300


def tail_code_block(text: str, limit: int, lang: str = "") -> tuple[str, bool]:
    """Wrap the end of `text` in a code block of at most `limit` characters.

    Keeps the last lines, since they hold the newest log lines and a
    traceback's raise site. Returns the block and whether anything was cut.
    """
    # A zero-width space between backticks stops the text closing the block early.
    body = re.sub(r"`(?=`)", "`\u200b", text.rstrip("\n"))
    budget = limit - len(f"```{lang}\n\n```")
    cut = len(body) > budget
    if cut:
        body = body[-budget:]
        _, newline, rest = body.partition("\n")
        if newline:
            body = rest
    return f"```{lang}\n{body}\n```", cut


def _age(seconds: float) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{int(seconds // size)}{unit} ago"
    return f"{int(seconds)}s ago"


class DeveloperMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing DeveloperMixIn")
        # On the root logger, so it sees task loop, view and listener errors that
        # Red's `[p]traceback` misses. Removed again in cog_unload().
        self._exception_recorder = ExceptionRecorder()
        logging.getLogger().addHandler(self._exception_recorder)
        super().__init__()

    # Groups

    _log_group = app_commands.Group(
        name="logs",
        description="Display information from bot log files",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # Test Development Function
    @app_commands.command(
        name="devtest",
        description="Test command for development purposes",
    )
    @app_commands.guild_only
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _dev_test_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_message(content="Developer test successful!", ephemeral=True)

    # Group Commands

    @_log_group.command(
        name="tail",
        description=f"Tail the latest log file (Max {BUFMAX} bytes)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _logs_tail_cmd(
        self,
        interaction: discord.Interaction,
    ):
        log_file = await self.get_latest_log_file()
        if not log_file:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Unable to find valid logging RotatingFileHandler."), ephemeral=True
            )
            return

        async with aiofiles.open(log_file, mode="rb") as fd:
            # A freshly rotated log can be shorter than BUFMAX, so clamp the
            # offset instead of seeking to a negative absolute position. The one
            # extra byte shows whether the window starts on a line boundary.
            size = await fd.seek(0, os.SEEK_END)
            start = max(0, size - BUFMAX - 1)
            await fd.seek(start)
            data = await fd.read(BUFMAX + 1)

        if start:
            _, newline, rest = data.partition(b"\n")
            if newline and rest:
                data = rest

        if not data:
            await interaction.response.send_message(embed=ErrorEmbed(description=f"Log file is empty: {log_file}"), ephemeral=True)
            return

        # The offset can land mid-character, so don't let a partial UTF-8
        # sequence at the head of the buffer blow up the whole command.
        block, _ = tail_code_block(data.decode("utf-8", errors="replace"), MESSAGE_MAX)
        await interaction.response.send_message(content=block, ephemeral=True)

    async def _traceback_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        # Autocomplete skips the command's checks, and server admins can widen
        # who sees the command, so gate it the same way the command is gated.
        if not interaction.permissions.manage_guild:
            return []
        now = time.time()
        choices = [
            app_commands.Choice(name=f"{_age(now - e.created)} · {e.logger} · {e.summary}"[:CHOICE_NAME_MAX], value=str(e.id))
            for e in self._exception_recorder.entries()
        ]
        if current:
            choices = [c for c in choices if current.lower() in c.name.lower()]
        return choices[:25]

    @_log_group.command(
        name="traceback",
        description="Show a recent exception the bot logged",
    )
    @app_commands.describe(exception="A recent exception (default: the newest)")
    @app_commands.autocomplete(exception=_traceback_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _logs_traceback_cmd(
        self,
        interaction: discord.Interaction,
        exception: str | None = None,
    ):
        recorder = self._exception_recorder
        if exception is None:
            entries = recorder.entries()
            if not entries:
                await interaction.response.send_message(
                    embed=BlueEmbed(description=f"No exceptions logged since <t:{int(recorder.started)}:R>."), ephemeral=True
                )
                return
            entry = entries[0]
        else:
            try:
                entry = recorder.get(int(exception))
            except ValueError:
                entry = None
            if entry is None:
                await interaction.response.send_message(
                    embed=ErrorEmbed(description="That exception is no longer stored. Only the last 25 are kept."), ephemeral=True
                )
                return

        message = entry.message
        if len(message) > TRACEBACK_MESSAGE_MAX:
            message = f"{message[: TRACEBACK_MESSAGE_MAX - 1]}…"
        header = f"**{discord.utils.escape_markdown(entry.logger)}** · <t:{int(entry.created)}:R>\n"
        if message:
            header += f"{discord.utils.escape_markdown(message)}\n"

        block, cut = tail_code_block(entry.traceback, MESSAGE_MAX - len(header), lang="py")
        if not cut:
            await interaction.response.send_message(content=header + block, ephemeral=True)
            return

        logged_at = datetime.fromtimestamp(entry.created, UTC).isoformat(timespec="seconds")
        full = f"{entry.logger} at {logged_at}\n{entry.message}\n\n{entry.traceback}"
        attachment = discord.File(io.BytesIO(full.encode()), filename=f"traceback-{entry.id}.txt")
        await interaction.response.send_message(content=header + block, file=attachment, ephemeral=True)

    # Functions

    async def get_latest_log_file(self) -> str | None:
        """Return path to latest log handler file"""
        latest_log_path = None
        root_logger = logging.getLogger()
        for fh in root_logger.handlers:
            # Red's subclass, not the stdlib one. Only it defines `baseStem`.
            if not isinstance(fh, RotatingFileHandler):
                continue
            if fh.baseStem == "latest":
                latest_log_path = fh.baseFilename
                break

        log.debug(f"Latest log file: {latest_log_path}")
        return latest_log_path
