import asyncio
import logging
import random
from dataclasses import dataclass

import discord

logger = logging.getLogger("red.rsc.utils.dm")

DEFAULT_RATE = 1.5  # base seconds between DMs
MAX_RETRIES = 5  # max retry attempts on rate limit


@dataclass
class DMTask:
    """A queued direct message to send."""

    member: discord.Member
    content: str | None = None
    embed: discord.Embed | None = None


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
        self._success: int = 0
        self._failed: int = 0
        self._total: int = 0

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def total(self) -> int:
        return self._total

    @property
    def pending(self) -> int:
        return self._queue.qsize()

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
        """Start the background consumer loop."""
        if self._task is None or self._task.done():
            self._success = 0
            self._failed = 0
            self._total = 0
            self._task = asyncio.create_task(self._consumer())

    async def stop(self) -> None:
        """Signal the consumer to drain remaining items and stop."""
        # Sentinel to signal shutdown
        await self._queue.put(None)
        if self._task:
            await self._task
            self._task = None

    async def enqueue(
        self,
        member: discord.Member,
        content: str | None = None,
        embed: discord.Embed | None = None,
    ) -> None:
        """Add a DM to the send queue."""
        self._total += 1
        await self._queue.put(DMTask(member=member, content=content, embed=embed))

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
