import logging
from urllib.parse import urljoin

import aiohttp
import discord

from rsc.combines import models
from rsc.exceptions import BadGateway

log = logging.getLogger("red.rsc.combines.api")


async def combines_active(
    url: str, player: discord.Member | None
) -> list[models.CombinesLobby]:
    async with aiohttp.ClientSession(trust_env=True) as session:
        url = urljoin(url, "active")
        log.debug(f"URL: {url}")

        params = {}
        if player:
            params = {"discord_id": player.id}

        async with session.get(url, params=params) as resp:
            log.debug(f"Server Response: {resp.status}")
            if resp.status == 502:
                raise BadGateway("Unable to reach combines API. Bad gateway")

            data = await resp.json()
            if not data:
                return []

            lobbies = []
            for v in data.values():
                lobbies.append(models.CombinesLobby(**v))
            return lobbies


async def combines_lobby(
    url: str, player: discord.Member
) -> models.CombinesLobby | models.CombinesStatus:
    async with aiohttp.ClientSession(trust_env=True) as session:
        url = urljoin(url, "lobby")
        log.debug(f"URL: {url}")
        params = {"discord_id": player.id}
        async with session.get(url, params=params) as resp:
            log.debug(f"Server Response: {resp.status}")
            if resp.status == 502:
                raise BadGateway("Unable to reach combines API. Bad gateway")

            data = await resp.json()
            if data.get("status") and data.get("message"):
                return models.CombinesStatus(**data)
            else:
                return models.CombinesLobby(**data)


async def combines_check_in(url, player: discord.Member) -> models.CombinesStatus:
    async with aiohttp.ClientSession(trust_env=True) as session:
        url = urljoin(url, "check_in")
        log.debug(f"URL: {url}")
        params = {"discord_id": player.id}
        async with session.get(url, params=params) as resp:
            log.debug(f"Server Response: {resp.status}")
            if resp.status == 502:
                raise BadGateway("Unable to reach combines API. Bad gateway")
            data = await resp.json()
            return models.CombinesStatus(**data)


async def combines_check_out(url, player: discord.Member) -> models.CombinesStatus:
    async with aiohttp.ClientSession(trust_env=True) as session:
        url = urljoin(url, "check_out")
        log.debug(f"URL: {url}")
        params = {"discord_id": player.id}
        async with session.get(url, params=params) as resp:
            log.debug(f"Server Response: {resp.status}")
            if resp.status == 502:
                raise BadGateway("Unable to reach combines API. Bad gateway")
            data = await resp.json()
            return models.CombinesStatus(**data)
