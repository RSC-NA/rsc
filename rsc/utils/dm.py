import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import UTC, datetime

import discord

logger = logging.getLogger("red.rsc.utils.dm")

DEFAULT_RATE = 1.5  # base seconds between DMs
MAX_RETRIES = 5  # max retry attempts on rate limit
SCHEDULE_POLL_INTERVAL = 30.0  # seconds between checks for scheduled messages


@dataclass
class DMTask:
    """A queued direct message to send."""

    member: discord.Member
    content: str | None = None
    embed: discord.Embed | None = None
    send_at: datetime | None = None


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

    def _jittered_rate(self) -> float:
        """Return a randomized delay around the base rate (±50%)."""
        return self._rate * random.uniform(0.5, 1.5)  # noqa: S311

    def start(self) -> None:
        """Start the background consumer loop and scheduler."""
        if self._task is None or self._task.done():
            self._success = 0
            self._failed = 0
            self._total = 0
            self._task = asyncio.create_task(self._consumer())
        if self._scheduler_task is None or self._scheduler_task.done():
            self._scheduler_task = asyncio.create_task(self._schedule_loop())

    async def stop(self) -> None:
        """Signal the consumer to drain remaining items and stop."""
        # Stop scheduler
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            self._scheduler_task = None
        # Sentinel to signal consumer shutdown
        await self._queue.put(None)
        if self._task:
            await self._task
            self._task = None

    async def enqueue(
        self,
        member: discord.Member,
        content: str | None = None,
        embed: discord.Embed | None = None,
        send_at: datetime | None = None,
    ) -> None:
        """Add a DM to the send queue.

        If ``send_at`` is provided (timezone-aware UTC datetime), the message
        is held until that time before entering the send queue.
        """
        self._total += 1
        task = DMTask(member=member, content=content, embed=embed, send_at=send_at)
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
        kwargs: dict = {}
        if task.content:
            kwargs["content"] = task.content
        if task.embed:
            kwargs["embed"] = task.embed

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
                self._failed += 1
                logger.debug(f"Cannot DM {task.member} ({task.member.id}): DMs disabled")
                return
            except discord.HTTPException as exc:
                self._failed += 1
                logger.debug(f"Failed to DM {task.member} ({task.member.id}): {exc}")
                return

        # Exhausted all retries
        self._failed += 1
        logger.warning(f"Exhausted {MAX_RETRIES} retries for DM to {task.member} ({task.member.id})")
