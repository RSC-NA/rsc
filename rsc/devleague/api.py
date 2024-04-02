import logging
from urllib.parse import urljoin

import aiohttp
import discord

from rsc.devleague import models

log = logging.getLogger("red.rsc.devleague.api")

DEVLEAGUE_API_URL = "https://devleague.rscna.com"


async def dev_league_status(player: discord.Member) -> models.DevLeagueStatus:
    async with aiohttp.ClientSession(trust_env=True) as session:
        url = urljoin(DEVLEAGUE_API_URL, "/api/status")
        log.debug(f"URL: {url}")
        params = {"discord_id": player.id}
        async with session.get(url, params=params) as resp:
            data = await resp.json()
            return models.DevLeagueStatus(**data)


async def dev_league_check_in(player: discord.Member) -> models.DevLeagueCheckInOut:
    async with aiohttp.ClientSession(trust_env=True) as session:
        url = urljoin(DEVLEAGUE_API_URL, "/api/check_in")
        log.debug(f"URL: {url}")
        params = {"discord_id": player.id}
        async with session.get(url, params=params) as resp:
            data = await resp.json()
            return models.DevLeagueCheckInOut(**data)


async def dev_league_check_out(player: discord.Member) -> models.DevLeagueCheckInOut:
    async with aiohttp.ClientSession() as session:
        url = urljoin(DEVLEAGUE_API_URL, "/api/check_out")
        log.debug(f"URL: {url}")
        params = {"discord_id": player.id}
        async with session.get(url, params=params) as resp:
            data = await resp.json()
            return models.DevLeagueCheckInOut(**data)
