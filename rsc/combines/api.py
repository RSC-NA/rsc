import logging
from urllib.parse import urljoin

import aiohttp
import discord

from rsc.combines import models
from rsc.exceptions import BadGateway

log = logging.getLogger("red.rsc.combines.api")


async def combines_active(
    url: str, player: discord.Member
) -> list[models.CombinesLobby] | models.CombinesStatus:
    async with aiohttp.ClientSession(trust_env=True) as session:
        url = urljoin(url, "active")
        log.debug(f"URL: {url}")

        params = {"discord_id": player.id, "guild_id": player.guild.id}

        async with session.get(url, params=params) as resp:
            log.debug(f"Server Response: {resp.status}")
            if resp.status == 502:
                raise BadGateway("Unable to reach combines API. Bad gateway")

            data = await resp.json()
            if not data:
                return []

            log.debug(f"data: {data}")

            data = await resp.json()
            if data.get("status") and data.get("message"):
                return models.CombinesStatus(**data)
            else:
                lobbies = []
                for v in data.values():
                    lobbies.append(models.CombinesLobby(**v))
                return lobbies


async def combines_lobby(
    url: str, executor: discord.Member, lobby_id: int | None = None
) -> models.CombinesLobby | models.CombinesStatus:
    async with aiohttp.ClientSession(trust_env=True) as session:
        params = {"discord_id": executor.id, "guild_id": executor.guild.id}

        url = urljoin(url, "lobby/")
        if lobby_id:
            url = urljoin(url, str(lobby_id))
        log.debug(f"URL: {url}")

        async with session.get(url, params=params) as resp:
            log.debug(f"Server Response: {resp.status}")
            if resp.status == 502:
                raise BadGateway("Unable to reach combines API. Bad gateway")

            data = await resp.json()
            if data.get("status") and data.get("message"):
                return models.CombinesStatus(**data)
            else:
                lobby: dict | None = next(iter(data.values()), None)
                if not lobby:
                    raise ValueError("Combine API did not return a valid JSON object.")
                return models.CombinesLobby(**lobby)


async def combines_check_in(url: str, player: discord.Member) -> models.CombinesStatus:
    async with aiohttp.ClientSession(trust_env=True) as session:
        url = urljoin(url, "check_in")
        log.debug(f"URL: {url}")
        params = {"discord_id": player.id, "guild_id": player.guild.id}
        async with session.get(url, params=params) as resp:
            log.debug(f"Server Response: {resp.status}")
            if resp.status == 502:
                raise BadGateway("Unable to reach combines API. Bad gateway")
            data = await resp.json()
            return models.CombinesStatus(**data)


async def combines_check_out(url: str, player: discord.Member) -> models.CombinesStatus:
    async with aiohttp.ClientSession(trust_env=True) as session:
        url = urljoin(url, "check_out")
        log.debug(f"URL: {url}")
        params = {"discord_id": player.id, "guild_id": player.guild.id}
        async with session.get(url, params=params) as resp:
            log.debug(f"Server Response: {resp.status}")
            if resp.status == 502:
                raise BadGateway("Unable to reach combines API. Bad gateway")
            data = await resp.json()
            return models.CombinesStatus(**data)
