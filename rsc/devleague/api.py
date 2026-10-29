import logging
from urllib.parse import urljoin

import discord

from rsc.devleague import models
from rsc.lobbies.api import get_json

log = logging.getLogger("red.rsc.devleague.api")

DEVLEAGUE_API_URL = "https://devleague.rscna.com"

# Every call raises rsc.exceptions.SiteUnavailable when the Dev League site can't answer


async def dev_league_status(player: discord.Member) -> models.DevLeagueStatus:
    url = urljoin(DEVLEAGUE_API_URL, "/api/status")
    log.debug(f"URL: {url}")
    return await get_json(url, {"discord_id": player.id}, models.DevLeagueStatus.model_validate)


async def dev_league_check_in(player: discord.Member) -> models.DevLeagueCheckInOut:
    url = urljoin(DEVLEAGUE_API_URL, "/api/check_in")
    log.debug(f"URL: {url}")
    return await get_json(url, {"discord_id": player.id}, models.DevLeagueCheckInOut.model_validate)


async def dev_league_check_out(player: discord.Member) -> models.DevLeagueCheckInOut:
    url = urljoin(DEVLEAGUE_API_URL, "/api/check_out")
    log.debug(f"URL: {url}")
    return await get_json(url, {"discord_id": player.id}, models.DevLeagueCheckInOut.model_validate)
