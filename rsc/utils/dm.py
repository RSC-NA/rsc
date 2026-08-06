import asyncio
import logging
import random
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import discord

logger = logging.getLogger("red.rsc.utils.dm")

DEFAULT_RATE = 1.5  # base seconds between DMs
MAX_RETRIES = 5  # max retry attempts on rate limit
SCHEDULE_POLL_INTERVAL = 30.0  # seconds between checks for scheduled messages
# The helper is a long lived singleton, so undeliverable recipients are kept in a
# bounded ring rather than a list that grows for the lifetime of the process.
MAX_FAILED_MEMBERS = 200


@dataclass
class DMTask:
    """A queued direct message to send."""

    member: discord.Member | discord.User
    content: str | None = None
    embed: discord.Embed | None = None
    view: discord.ui.View | None = None
    send_at: datetime | None = None
    # Evaluated immediately before sending. Returning False drops the message.
    # Lets a batch queued minutes ago skip recipients who are no longer relevant.
    # Fails open: if the check itself raises, the DM is still sent.
    precheck: Callable[[], Awaitable[bool]] | None = None


class DMHelper:
    """A rate-limited queue for sending Discord direct messages.

    Sends one DM at a time with a configurable delay between each to avoid
    being flagged by Discord for mass-DMing users.

    Usage:
        helper = DMHelper(rate=1.5)
        helper.start()
        await helper.enqueue(member, content="Hello!")
        # ... later ...
        await helper.stop()
    """

    def __init__(self, rate: float = DEFAULT_RATE):
        self._rate = rate
        self._queue: asyncio.Queue[DMTask | None] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._scheduler_task: asyncio.Task | None = None
        self._scheduled: list[DMTask] = []
        self._scheduled_lock: asyncio.Lock = asyncio.Lock()
        self._success: int = 0
        self._failed: int = 0
        self._total: int = 0
        self._cancelled: int = 0
        self._skipped: int = 0
        self._failed_members: deque[discord.Member | discord.User] = deque(maxlen=MAX_FAILED_MEMBERS)

    @property
    def is_running(self) -> bool:
        consumer_running = self._task is not None and not self._task.done()
        scheduler_running = self._scheduler_task is not None and not self._scheduler_task.done()
        return consumer_running or scheduler_running

    @property
    def total(self) -> int:
        return self._total

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    @property
    def scheduled(self) -> int:
        return len(self._scheduled)

    @property
    def success(self) -> int:
        return self._success

    @property
    def failed(self) -> int:
        return self._failed

    @property
    def cancelled(self) -> int:
        """DMs dropped by `purge()` without being sent."""
        return self._cancelled

    @property
    def skipped(self) -> int:
        """DMs dropped because their `precheck` said they were no longer needed."""
        return self._skipped

    @property
    def failed_members(self) -> list[discord.Member | discord.User]:
        """Recipients whose DM could not be delivered, oldest first.

        Bounded at `MAX_FAILED_MEMBERS`. This queue is shared by every feature that
        sends DMs, so the list is not scoped to any single batch - see the caveat
        on `/admin dmstatus`.
        """
        return list(self._failed_members)

    def _jittered_rate(self) -> float:
        """Return a randomized delay around the base rate (±50%)."""
        return self._rate * random.uniform(0.5, 1.5)  # noqa: S311

    def start(self) -> None:
        """Start the background consumer loop and scheduler."""
        if self._task is None or self._task.done():
            self._success = 0
            self._failed = 0
            self._total = 0
            self._cancelled = 0
            self._skipped = 0
            self._failed_members.clear()
            self._task = asyncio.create_task(self._consumer())
        if self._scheduler_task is None or self._scheduler_task.done():
            self._scheduler_task = asyncio.create_task(self._schedule_loop())

    async def purge(self) -> int:
        """Drop every pending and scheduled DM without sending. Returns the count.

        This is the abort path for a mass DM batch that should not have gone out.
        A message already handed to `_send` when purge runs will still be
        delivered - at most one DM escapes.
        """
        dropped = 0
        requeue_sentinel = False

        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item is None:
                # Shutdown sentinel. Put it back and stop; anything behind it is
                # post-shutdown work the consumer will handle on its own terms.
                requeue_sentinel = True
                break
            dropped += 1

        if requeue_sentinel:
            await self._queue.put(None)

        async with self._scheduled_lock:
            dropped += len(self._scheduled)
            self._scheduled.clear()

        self._cancelled += dropped
        logger.warning(f"Purged {dropped} pending DM(s) from the queue")
        return dropped

    async def stop(self, drain: bool = True) -> None:
        """Stop the consumer and scheduler.

        `drain=True` sends everything still queued before stopping, which can take
        `rate` seconds per message. Pass `drain=False` to discard the backlog
        instead - appropriate on unload, where blocking a reload for minutes is
        worse than losing queued reminders.
        """
        # Stop the scheduler before purging, otherwise a due task could be released
        # into the queue after the purge and get sent on the way out.
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            self._scheduler_task = None

        if not drain:
            await self.purge()

        # Sentinel to signal consumer shutdown
        await self._queue.put(None)
        if self._task:
            await self._task
            self._task = None

    async def enqueue(
        self,
        member: discord.Member | discord.User,
        content: str | None = None,
        embed: discord.Embed | None = None,
        view: discord.ui.View | None = None,
        send_at: datetime | None = None,
        precheck: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        """Add a DM to the send queue.

        If ``send_at`` is provided (timezone-aware UTC datetime), the message
        is held until that time before entering the send queue. If ``precheck``
        is provided it is awaited just before sending; a False result drops the
        message.
        """
        self._total += 1
        task = DMTask(member=member, content=content, embed=embed, view=view, send_at=send_at, precheck=precheck)
        if send_at and send_at > datetime.now(UTC):
            async with self._scheduled_lock:
                self._scheduled.append(task)
            logger.debug(f"Scheduled DM to {member} ({member.id}) at {send_at.isoformat()}")
        else:
            await self._queue.put(task)

    async def _consumer(self) -> None:
        """Process queued DMs one at a time with rate limiting."""
        logger.debug("DM consumer started")
        while True:
            item = await self._queue.get()
            if item is None:
                # Drain remaining
                while not self._queue.empty():
                    remaining = self._queue.get_nowait()
                    if remaining is not None:
                        await self._send(remaining)
                        await asyncio.sleep(self._jittered_rate())
                break

            await self._send(item)
            # Rate limit after each message
            await asyncio.sleep(self._jittered_rate())
        logger.debug(f"DM consumer finished. Sent: {self._success}, Failed: {self._failed}")

    async def _schedule_loop(self) -> None:
        """Periodically move scheduled tasks that are due into the send queue."""
        logger.debug("DM scheduler started")
        while True:
            now = datetime.now(UTC)
            ready: list[DMTask] = []
            async with self._scheduled_lock:
                remaining: list[DMTask] = []
                for task in self._scheduled:
                    if task.send_at and task.send_at <= now:
                        ready.append(task)
                    else:
                        remaining.append(task)
                self._scheduled = remaining

            for task in ready:
                logger.debug(f"Releasing scheduled DM to {task.member} ({task.member.id})")
                await self._queue.put(task)

            await asyncio.sleep(SCHEDULE_POLL_INTERVAL)

    async def _send(self, task: DMTask) -> None:
        """Send a single DM with exponential backoff on rate limits."""
        if task.precheck and not await self._should_still_send(task):
            return

        kwargs: dict = {}
        if task.content:
            kwargs["content"] = task.content
        if task.embed:
            kwargs["embed"] = task.embed
        if task.view:
            kwargs["view"] = task.view

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                await task.member.send(**kwargs)
                self._success += 1
                return
            except discord.RateLimited as exc:
                backoff = exc.retry_after + (2**attempt)
                logger.warning(
                    f"Rate limited sending DM to {task.member} ({task.member.id}). Attempt {attempt}/{MAX_RETRIES}, sleeping {backoff:.1f}s"
                )
                await asyncio.sleep(backoff)
            except discord.Forbidden:
                self._record_failure(task.member)
                logger.debug(f"Cannot DM {task.member} ({task.member.id}): DMs disabled")
                return
            except discord.HTTPException as exc:
                self._record_failure(task.member)
                logger.debug(f"Failed to DM {task.member} ({task.member.id}): {exc}")
                return

        # Exhausted all retries
        self._record_failure(task.member)
        logger.warning(f"Exhausted {MAX_RETRIES} retries for DM to {task.member} ({task.member.id})")

    async def _should_still_send(self, task: DMTask) -> bool:
        """Run a task's precheck, failing open.

        A batch can sit in the queue for many minutes, so a recipient may no
        longer need the message by the time it reaches the front. If the check
        itself errors we send anyway - a redundant DM beats a dropped one.
        """
        if task.precheck is None:
            return True
        try:
            if await task.precheck():
                return True
        except Exception as exc:
            logger.warning(f"Precheck failed for DM to {task.member} ({task.member.id}), sending anyway: {exc}")
            return True

        self._skipped += 1
        logger.debug(f"Skipping DM to {task.member} ({task.member.id}): no longer required")
        return False

    def _record_failure(self, member: discord.Member | discord.User) -> None:
        """Count an undelivered DM and remember who it was for admin follow up."""
        self._failed += 1
        self._failed_members.append(member)
