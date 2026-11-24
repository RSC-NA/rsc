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
    EDIT = "edit"


class NicknameRefusedError(Exception):
    """A member's nickname was not written. The role changes sent with it were."""


@dataclass
class SyncStats:
    """What one sync run did.

    `changed` holds the members the run sent at least one request for.
    `failed` holds the members a request raised for, and the members whose
    nickname was left out because Discord would refuse it. Both hold member
    ids, so a member written twice counts once.
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


class _Edit(TypedDict, total=False):
    roles: list[discord.Role]
    nick: str
    reason: str


async def apply_member_changes(
    member: discord.Member,
    *,
    remove: Sequence[discord.Role] = (),
    add: Sequence[discord.Role] = (),
    nick: str | None = None,
    reason: str | None = None,
) -> None:
    """Send a member's role changes and nickname as one request, or none when nothing changes.

    Discord replaces the member's roles with the list in the request. The list
    is the roles the guild cache holds for the member now, or the member's own
    when the cache does not hold them, without `remove` and with `add`. Every
    other role the member holds is sent back unchanged.

    A nickname the bot may not write never costs the role changes. They are
    sent without it, in a second request when Discord refused the first, and
    `NicknameRefusedError` is raised afterwards.
    """
    guild = member.guild
    held = [role for role in (guild.get_member(member.id) or member).roles if role != guild.default_role]
    kept = [role for role in held if role not in remove]
    roles = kept + [role for role in dict.fromkeys(add) if role not in kept]

    edit: _Edit = {}
    if set(roles) != set(held):
        edit["roles"] = roles
    if reason is not None:
        edit["reason"] = reason

    if nick is not None and _may_rename(member):
        try:
            await _send(member, _Edit(**edit, nick=nick))
        except discord.Forbidden as exc:
            if "roles" in edit:
                await _send(member, edit)
            raise NicknameRefusedError(str(exc)) from exc
        return

    if "roles" in edit:
        await _send(member, edit)
    if nick is not None:
        _nickname_failed(member)
        raise NicknameRefusedError("The member owns the server or holds a role that is not below the bot's top role.")


async def write_nickname(member: discord.Member, nick: str) -> None:
    """Send a nickname on its own. A refusal from Discord reaches the caller."""
    await _send(member, _Edit(nick=nick))


def _may_rename(member: discord.Member) -> bool:
    guild = member.guild
    if member.id == guild.owner_id:
        return False
    # The cache holds no bot member without a gateway connection, as in scripts/sync_lab.py. Discord's answer decides then.
    me: discord.Member | None = guild.me
    return me is None or member.top_role < me.top_role


def _nickname_failed(member: discord.Member) -> None:
    stats = _run.get()
    if stats is not None:
        stats.failed.add(member.id)


async def _send(member: discord.Member, edit: _Edit) -> None:
    log.debug(f"Editing member ({member.id}): {edit}", guild=member.guild)
    stats = _run.get()
    if stats is None:
        await member.edit(**edit)
        return

    stats.changed.add(member.id)
    stats.requests[Request.EDIT] += 1
    started = time.perf_counter()
    try:
        await member.edit(**edit)
    except Exception:
        stats.failed.add(member.id)
        raise
    finally:
        stats.discord_s += time.perf_counter() - started
