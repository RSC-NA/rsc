import logging

import discord

log = logging.getLogger("red.rsc.ballchasing.validation")


async def is_replay_file(replay: discord.Attachment) -> bool:
    """Check if file provided is a replay file"""
    return bool(replay.filename.endswith(".replay"))
