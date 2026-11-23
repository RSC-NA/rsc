"""The one place a member's roles and nickname are written, and the count of what each sync run wrote."""

import logging
import time
from collections import Counter
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Generator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypedDict, TypeVar

import discord

from rsc.logs import GuildLogAdapter

logger = logging.getLogger("red.rsc.transactions.writer")
log = GuildLogAdapter(logger)

T = TypeVar("T")


class SyncKind(StrEnum):
    NIGHTLY = "nightly"
    PLAYERS = "players"
    NONPLAYING = "nonplaying"
    MEMBER = "member"
    FREE_AGENT = "freeagent"
    DRAFT_ELIGIBLE = "drafteligible"


class Request(StrEnum):
    REMOVE_ROLE = "remove_role"
    ADD_ROLE = "add_role"
    EDIT = "edit"


@dataclass
class SyncStats:
    """What one sync run did.

    `changed` holds the members the run sent at least one request for, and
    `failed` the members a request raised for. Both hold member ids, because a
    member's roles and nickname arrive in separate calls and count once.
    """

    kind: SyncKind
    visited: int = 0
    changed: set[int] = field(default_factory=set)
    requests: Counter[Request] = field(default_factory=Counter)
    failed: set[int] = field(default_factory=set)
    api_s: float = 0.0
    discord_s: float = 0.0
    staff_wait_s: float = 0.0
    elapsed_s: float = 0.0

    def summary(self) -> str:
        requests = {request.value: self.requests[request] for request in Request if self.requests[request]}
        return (
            f"Sync summary. kind={self.kind.value} visited={self.visited} changed={len(self.changed)} "
            f"requests={requests} failed={len(self.failed)} "
            f"api_s={self.api_s:.3f} discord_s={self.discord_s:.3f} elapsed_s={self.elapsed_s:.3f}"
        )


# A context variable, so two syncs running at once each count their own writes
# and the role functions need no stats argument.
_run: ContextVar[SyncStats | None] = ContextVar("sync_run", default=None)


@contextmanager
def sync_run(kind: SyncKind, guild: discord.Guild | None) -> Generator[SyncStats, None, None]:
    """Count every write made inside the block, and log one `Sync summary.` line when it ends."""
    stats = SyncStats(kind)
    token = _run.set(stats)
    started = time.perf_counter()
    try:
        yield stats
    finally:
        stats.elapsed_s = time.perf_counter() - started - stats.staff_wait_s
        _run.reset(token)
        log.info(stats.summary(), guild=guild)


def member_visited() -> None:
    stats = _run.get()
    if stats is not None:
        stats.visited += 1


@contextmanager
def waiting_for_staff() -> Generator[None, None, None]:
    """Keep the time staff take to answer a prompt out of the run's elapsed seconds."""
    started = time.perf_counter()
    try:
        yield
    finally:
        stats = _run.get()
        if stats is not None:
            stats.staff_wait_s += time.perf_counter() - started


async def api_read(read: Awaitable[T]) -> T:
    """Await an API read, adding its duration to the run's API seconds."""
    started = time.perf_counter()
    try:
        return await read
    finally:
        stats = _run.get()
        if stats is not None:
            stats.api_s += time.perf_counter() - started


async def api_pages(rows: AsyncIterable[T]) -> AsyncIterator[T]:
    """Yield the rows of a paged API read, timing only the waits for the next row."""
    pages = aiter(rows)
    while True:
        try:
            row = await api_read(anext(pages))
        except StopAsyncIteration:
            return
        yield row


class _AuditLog(TypedDict, total=False):
    reason: str


async def apply_member_changes(
    member: discord.Member,
    *,
    remove: Sequence[discord.Role] = (),
    add: Sequence[discord.Role] = (),
    nick: str | None = None,
    reason: str | None = None,
) -> None:
    """Send a member's role removals, then the role additions, then the nickname.

    discord.py sends one request per role, so the run counts one per role. A
    call that raises partway is counted in full.
    """
    audit: _AuditLog = {"reason": reason} if reason is not None else {}
    if remove:
        log.debug(f"Removing roles ({member.id}): {list(remove)}", guild=member.guild)
        await _send(member, Request.REMOVE_ROLE, len(remove), member.remove_roles(*remove, **audit))
    if add:
        log.debug(f"Adding roles ({member.id}): {list(add)}", guild=member.guild)
        await _send(member, Request.ADD_ROLE, len(add), member.add_roles(*add, **audit))
    if nick is not None:
        log.debug(f"Updating nickname ({member.id}): {nick}", guild=member.guild)
        await _send(member, Request.EDIT, 1, member.edit(nick=nick, **audit))


async def _send(member: discord.Member, request: Request, count: int, write: Awaitable[object]) -> None:
    stats = _run.get()
    if stats is None:
        await write
        return

    stats.changed.add(member.id)
    stats.requests[request] += count
    started = time.perf_counter()
    try:
        await write
    except Exception:
        stats.failed.add(member.id)
        raise
    finally:
        stats.discord_s += time.perf_counter() - started
