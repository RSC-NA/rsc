"""Small TTL cache with single-flight, for agent tool results.

Deliberately hand-rolled rather than pulling in `cachetools`: the project has no
caching dependency today, and the requirement here is ~40 lines. The
single-flight lock matters more than the TTL -- two people mentioning the bot at
once should not both fetch the whole franchise list.
"""

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable

from rsc.llm.config import API_CACHE_MAXSIZE, API_CACHE_TTL

CacheKey = tuple[object, ...]


class ToolCache:
    def __init__(self, ttl: float = API_CACHE_TTL, maxsize: int = API_CACHE_MAXSIZE) -> None:
        self._ttl = ttl
        self._maxsize = maxsize
        self._entries: OrderedDict[CacheKey, tuple[float, str]] = OrderedDict()
        self._locks: dict[CacheKey, asyncio.Lock] = {}

    def _get(self, key: CacheKey) -> str | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires < time.monotonic():
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return value

    def _set(self, key: CacheKey, value: str) -> None:
        self._entries[key] = (time.monotonic() + self._ttl, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._maxsize:
            self._entries.popitem(last=False)

    async def get_or_fetch(self, key: CacheKey, fetch: Callable[[], Awaitable[str]]) -> str:
        cached = self._get(key)
        if cached is not None:
            return cached

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # A concurrent caller may have populated it while we waited.
            cached = self._get(key)
            if cached is not None:
                return cached
            value = await fetch()
            self._set(key, value)
        # Only the last holder clears the lock, so waiters never block on a
        # lock object that has been swapped out from under them.
        if not lock.locked():
            self._locks.pop(key, None)
        return value

    def clear(self) -> None:
        self._entries.clear()
        self._locks.clear()


def cache_key(guild_id: int, tool_name: str, kwargs: dict[str, object]) -> CacheKey:
    return (guild_id, tool_name, tuple(sorted((k, repr(v)) for k, v in kwargs.items())))
