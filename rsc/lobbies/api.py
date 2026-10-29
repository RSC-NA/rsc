"""Requests to the combines and Dev League site, shared by both API clients."""

import logging
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

import aiohttp

from rsc.exceptions import SiteUnavailable

log = logging.getLogger("red.rsc.lobbies.api")

T = TypeVar("T")

# Well inside the time a player waits on a deferred command
TIMEOUT = aiohttp.ClientTimeout(total=10)


async def get_json(url: str, params: Mapping[str, int], parse: Callable[[object], T]) -> T:
    """GET `url` and `parse` its JSON reply.

    Raises `SiteUnavailable` for every way the site can fail us: no connection,
    a timeout, a 5xx, a reply that isn't JSON, or one `parse` rejects with a ValueError.
    """
    try:
        async with aiohttp.ClientSession(trust_env=True, timeout=TIMEOUT) as session, session.get(url, params=params) as resp:
            log.debug(f"Server Response: {resp.status}")
            if resp.status >= 500:
                raise SiteUnavailable(f"{url} returned {resp.status}")
            data = await resp.json()
        # pydantic's ValidationError is a ValueError, as is a JSON decode error
        return parse(data)
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise SiteUnavailable(f"Unable to read {url}: {exc!r}") from exc


def json_object(data: object) -> dict[str, Any]:
    """`data` when it's a JSON object. A ValueError otherwise, so `get_json` reports it."""
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object, got {type(data).__name__}")
    return data
