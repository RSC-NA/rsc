import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rsc.utils.dm import DMHelper, DMTask, SCHEDULE_POLL_INTERVAL


def _mock_member(name="TestUser", member_id=111111111):
    """Create a mock Discord member with a working async send()."""
    member = MagicMock(spec=discord.Member)
    member.id = member_id
    member.name = name
    member.__str__ = lambda self: name
    member.send = AsyncMock()
    return member


class TestDMTask:
    def test_defaults(self):
        member = _mock_member()
        task = DMTask(member=member)
        assert task.content is None
        assert task.embed is None
        assert task.send_at is None

    def test_with_all_fields(self):
        member = _mock_member()
        embed = MagicMock(spec=discord.Embed)
        when = datetime(2099, 1, 1, tzinfo=UTC)
        task = DMTask(member=member, content="hi", embed=embed, send_at=when)
        assert task.content == "hi"
        assert task.embed is embed
        assert task.send_at == when


class TestDMHelperLifecycle:
    async def test_start_sets_running(self):
        helper = DMHelper(rate=0)
        assert helper.is_running is False
        helper.start()
        assert helper.is_running is True
        await helper.stop()
        assert helper.is_running is False

    async def test_stop_is_idempotent(self):
        helper = DMHelper(rate=0)
        helper.start()
        await helper.stop()
        await helper.stop()  # should not raise

    async def test_start_resets_counters(self):
        helper = DMHelper(rate=0)
        helper._success = 5
        helper._failed = 2
        helper._total = 7
        helper.start()
        assert helper.success == 0
        assert helper.failed == 0
        assert helper.total == 0
        await helper.stop()


class TestDMHelperSend:
    async def test_sends_content(self):
        helper = DMHelper(rate=0)
        helper.start()
        member = _mock_member()
        await helper.enqueue(member, content="hello")
        await helper.stop()
        member.send.assert_awaited_once_with(content="hello")
        assert helper.success == 1
        assert helper.failed == 0
        assert helper.total == 1

    async def test_sends_embed(self):
        helper = DMHelper(rate=0)
        helper.start()
        member = _mock_member()
        embed = MagicMock(spec=discord.Embed)
        await helper.enqueue(member, embed=embed)
        await helper.stop()
        member.send.assert_awaited_once_with(embed=embed)
        assert helper.success == 1

    async def test_sends_content_and_embed(self):
        helper = DMHelper(rate=0)
        helper.start()
        member = _mock_member()
        embed = MagicMock(spec=discord.Embed)
        await helper.enqueue(member, content="hi", embed=embed)
        await helper.stop()
        member.send.assert_awaited_once_with(content="hi", embed=embed)

    async def test_multiple_messages_all_sent(self):
        helper = DMHelper(rate=0)
        helper.start()
        members = [_mock_member(f"User{i}", 100 + i) for i in range(10)]
        for m in members:
            await helper.enqueue(m, content="msg")
        await helper.stop()
        for m in members:
            m.send.assert_awaited_once_with(content="msg")
        assert helper.success == 10
        assert helper.total == 10

    async def test_forbidden_counts_as_failed(self):
        helper = DMHelper(rate=0)
        helper.start()
        member = _mock_member()
        member.send.side_effect = discord.Forbidden(MagicMock(), "Cannot DM")
        await helper.enqueue(member, content="hi")
        await helper.stop()
        assert helper.failed == 1
        assert helper.success == 0

    async def test_http_exception_counts_as_failed(self):
        helper = DMHelper(rate=0)
        helper.start()
        member = _mock_member()
        member.send.side_effect = discord.HTTPException(MagicMock(), "Server error")
        await helper.enqueue(member, content="hi")
        await helper.stop()
        assert helper.failed == 1
        assert helper.success == 0

    @patch("rsc.utils.dm.asyncio.sleep", new_callable=AsyncMock)
    async def test_rate_limited_retries_then_succeeds(self, mock_sleep):
        helper = DMHelper(rate=0)
        helper.start()
        member = _mock_member()
        exc = discord.RateLimited(0.0)
        # Fail twice with rate limit, then succeed
        member.send.side_effect = [exc, exc, None]
        await helper.enqueue(member, content="hi")
        await helper.stop()
        assert member.send.await_count == 3
        assert helper.success == 1
        assert helper.failed == 0

    @patch("rsc.utils.dm.asyncio.sleep", new_callable=AsyncMock)
    async def test_rate_limited_exhausts_retries(self, mock_sleep):
        helper = DMHelper(rate=0)
        helper.start()
        member = _mock_member()
        exc = discord.RateLimited(0.0)
        member.send.side_effect = exc  # always rate limited
        await helper.enqueue(member, content="hi")
        await helper.stop()
        assert helper.failed == 1
        assert helper.success == 0


class TestDMHelperNonBlocking:
    """Verify the DM queue does not block the event loop."""

    async def test_enqueue_returns_immediately(self):
        """enqueue() should return without waiting for the DM to be sent."""
        helper = DMHelper(rate=5)  # long rate to ensure consumer is slow
        helper.start()
        member = _mock_member()
        # enqueue should complete nearly instantly even with a slow consumer
        before = asyncio.get_event_loop().time()
        await helper.enqueue(member, content="hello")
        elapsed = asyncio.get_event_loop().time() - before
        assert elapsed < 0.5, f"enqueue blocked for {elapsed:.2f}s"
        await helper.stop()

    async def test_event_loop_responsive_during_send(self):
        """Other coroutines should be able to run while DMs are being sent."""
        helper = DMHelper(rate=0)
        helper.start()

        # Make send() take a noticeable amount of time
        slow_member = _mock_member()

        async def slow_send(**kwargs):
            await asyncio.sleep(0.3)

        slow_member.send.side_effect = slow_send

        await helper.enqueue(slow_member, content="slow")

        # Run a fast coroutine concurrently — it should not be blocked
        result = []

        async def fast_work():
            result.append("done")

        # Give the consumer a moment to pick up the task
        await asyncio.sleep(0.05)
        # fast_work should complete while slow_send is still running
        before = asyncio.get_event_loop().time()
        await fast_work()
        elapsed = asyncio.get_event_loop().time() - before
        assert elapsed < 0.1, f"Event loop blocked for {elapsed:.2f}s"
        assert result == ["done"]
        await helper.stop()

    async def test_concurrent_tasks_run_during_large_batch(self):
        """Simulate a large batch and confirm the loop stays responsive."""
        helper = DMHelper(rate=0)
        helper.start()

        members = [_mock_member(f"User{i}", 200 + i) for i in range(20)]
        for m in members:
            await helper.enqueue(m, content="batch")

        # While the batch is processing, run a separate task
        counter = 0

        async def tick():
            nonlocal counter
            for _ in range(5):
                counter += 1
                await asyncio.sleep(0.01)

        await tick()
        assert counter == 5, "Concurrent task was blocked by DM processing"
        await helper.stop()


class TestDMHelperScheduled:
    async def test_future_message_goes_to_scheduled(self):
        helper = DMHelper(rate=0)
        helper.start()
        member = _mock_member()
        future = datetime.now(UTC) + timedelta(hours=1)
        await helper.enqueue(member, content="later", send_at=future)
        assert helper.scheduled == 1
        assert helper.pending == 0
        member.send.assert_not_awaited()
        await helper.stop()

    async def test_past_send_at_goes_to_queue_immediately(self):
        helper = DMHelper(rate=0)
        helper.start()
        member = _mock_member()
        past = datetime.now(UTC) - timedelta(hours=1)
        await helper.enqueue(member, content="overdue", send_at=past)
        await helper.stop()
        member.send.assert_awaited_once_with(content="overdue")
        assert helper.success == 1
        assert helper.scheduled == 0

    async def test_schedule_loop_releases_due_tasks(self):
        """Patch SCHEDULE_POLL_INTERVAL so the loop fires quickly."""
        member = _mock_member()
        send_at = datetime.now(UTC) + timedelta(seconds=0.1)

        with patch("rsc.utils.dm.SCHEDULE_POLL_INTERVAL", 0.05):
            helper = DMHelper(rate=0)
            helper.start()
            await helper.enqueue(member, content="scheduled", send_at=send_at)
            assert helper.scheduled == 1

            # Wait for the schedule loop to fire and the consumer to send
            await asyncio.sleep(0.5)

            assert helper.scheduled == 0
            member.send.assert_awaited_once_with(content="scheduled")
            assert helper.success == 1
            await helper.stop()

    async def test_scheduled_property_decrements(self):
        """scheduled count should go down as messages are released."""
        with patch("rsc.utils.dm.SCHEDULE_POLL_INTERVAL", 0.05):
            helper = DMHelper(rate=0)
            helper.start()
            members = [_mock_member(f"U{i}", 300 + i) for i in range(3)]
            send_at = datetime.now(UTC) + timedelta(seconds=0.1)
            for m in members:
                await helper.enqueue(m, content="hi", send_at=send_at)
            assert helper.scheduled == 3
            await asyncio.sleep(0.5)
            assert helper.scheduled == 0
            assert helper.success == 3
            await helper.stop()
