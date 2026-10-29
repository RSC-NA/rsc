import logging
from typing import Any
from urllib.parse import urljoin

import discord

from rsc.combines import models
from rsc.lobbies.api import get_json, json_object

log = logging.getLogger("red.rsc.combines.api")

# Every call raises rsc.exceptions.SiteUnavailable when the combines site can't answer


def _params(member: discord.Member) -> dict[str, int]:
    return {"discord_id": member.id, "guild_id": member.guild.id}


def _is_status(data: dict[str, Any]) -> bool:
    return bool(data.get("status") and data.get("message"))


async def combines_active(url: str, player: discord.Member) -> list[models.CombinesLobby] | models.CombinesStatus:
    def parse(reply: object) -> list[models.CombinesLobby] | models.CombinesStatus:
        if not reply:
            return []
        data = json_object(reply)
        if _is_status(data):
            return models.CombinesStatus.model_validate(data)
        return [models.CombinesLobby.model_validate(v) for v in data.values()]

    url = urljoin(url, "active")
    log.debug(f"URL: {url}")
    return await get_json(url, _params(player), parse)


async def combines_lobby(url: str, executor: discord.Member, lobby_id: int | None = None) -> models.CombinesLobby | models.CombinesStatus:
    def parse(reply: object) -> models.CombinesLobby | models.CombinesStatus:
        data = json_object(reply)
        if _is_status(data):
            return models.CombinesStatus.model_validate(data)
        lobby = next(iter(data.values()), None)
        if not lobby:
            raise ValueError("Combine API did not return a valid JSON object.")
        return models.CombinesLobby.model_validate(lobby)

    url = urljoin(url, "lobby/")
    if lobby_id:
        url = urljoin(url, str(lobby_id))
    log.debug(f"URL: {url}")
    return await get_json(url, _params(executor), parse)


async def combines_check_in(url: str, player: discord.Member) -> models.CombinesStatus:
    url = urljoin(url, "check_in")
    log.debug(f"URL: {url}")
    return await get_json(url, _params(player), models.CombinesStatus.model_validate)


async def combines_check_out(url: str, player: discord.Member) -> models.CombinesStatus:
    url = urljoin(url, "check_out")
    log.debug(f"URL: {url}")
    return await get_json(url, _params(player), models.CombinesStatus.model_validate)
