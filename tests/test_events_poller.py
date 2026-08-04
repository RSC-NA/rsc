"""Integration-shaped tests for `EventMixIn.poll_league_events`.

`plan_batch` is covered directly in `test_events.py`. These exercise the whole
poll: config reads and writes, dispatch, handler invocation, and Discord output,
with the API and Red's Config faked out.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rsc.events.events import EventMixIn, defaults_guild
from rsc.events.models import MAX_EVENTS_PER_TICK, EventPage, EventPollState, LeagueEventData


class FakeValue:
    """Stands in for a redbot Config value proxy."""

    def __init__(self, store: dict, key: str):
        self._store, self._key = store, key

    async def __call__(self):
        return self._store[self._key]

    async def set(self, value):
        self._store[self._key] = value


class FakeGroup:
    def __init__(self, store: dict):
        self._store = store

    def __getattr__(self, name: str) -> FakeValue:
        return FakeValue(self._store, name)

    async def all(self) -> dict:
        return dict(self._store)


class FakeConfig:
    def __init__(self, store: dict):
        self._store = store

    def custom(self, *_args) -> FakeGroup:
        return FakeGroup(self._store)


class Poller(EventMixIn):
    """Minimal harness: no Red bot, no task loop, no live API."""

    def __init__(self, store: dict, events: list[LeagueEventData]):
        self.config = FakeConfig(store)
        self.bot = MagicMock()
        self.bot.dispatch = MagicMock()
        self._api_conf = {1: object()}
        self._league = {1: 1}
        self._event_state = {}
        self._events = events
        self.sent: list[dict] = []
        self.fetch_calls: list[dict] = []

    async def fetch_league_events(self, guild, *, id__gt, limit, include_private=False, include_global=False):
        """Stand-in for the real request.

        Mirrors the contract that matters to the caller: ascending by id,
        exclusive cursor, `limit` bounds the slice, and `count` is the size of
        the whole backlog above the cursor rather than of the slice.
        """
        self.fetch_calls.append(
            {
                "id__gt": id__gt,
                "limit": limit,
                "include_private": include_private,
                "include_global": include_global,
            }
        )
        matched = sorted((e for e in self._events if e.id > id__gt), key=lambda e: e.id)
        return EventPage(events=matched[:limit], count=len(matched))

    async def newest_league_event(self, guild, *, include_private=False, include_global=False):
        return max(self._events, key=lambda e: e.id, default=None)

    async def _get_event_channel(self, guild):
        channel = MagicMock()
        channel.send = AsyncMock(side_effect=lambda **kwargs: self.sent.append(kwargs))
        return channel


# RSCMixIn declares ~100 abstractmethods purely for cross-mixin type hinting.
# Only the events ones matter here, and ABCMeta recomputes this set at class
# creation, so it has to be cleared afterwards.
Poller.__abstractmethods__ = frozenset()


@pytest.fixture
def guild() -> MagicMock:
    g = MagicMock()
    g.id = 1
    g.name = "Test Guild"
    return g


def evt(event_id: int, **kwargs) -> LeagueEventData:
    kwargs.setdefault("category", "TRN")
    kwargs.setdefault("action", "PSG")
    kwargs.setdefault("created_at", datetime.now(UTC) - timedelta(seconds=30))
    kwargs.setdefault("payload", {"n": event_id})
    return LeagueEventData(id=event_id, league=1, is_public=True, **kwargs)


def enabled_store(**overrides) -> dict:
    store = dict(defaults_guild)
    store["EventsEnabled"] = True
    store.update(overrides)
    return store


def primed_store(confirmed_id: int = 5, **overrides) -> dict:
    """A guild that has already bootstrapped."""
    return enabled_store(
        ConfirmedId=confirmed_id,
        ConfirmedCreatedAt=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        **overrides,
    )


class TestBootstrap:
    async def test_seeds_cursor_without_processing(self, guild):
        """A fresh guild must not dump its whole history into the channel."""
        store = enabled_store()
        poller = Poller(store, [evt(i) for i in range(1, 6)])

        await poller.poll_league_events(guild, EventPollState())

        assert store["ConfirmedId"] == 5
        assert store["ConfirmedCreatedAt"] is not None
        assert poller.sent == []
        assert poller.bot.dispatch.call_count == 0

    async def test_empty_api_still_records_a_timestamp(self, guild):
        """Otherwise it would re-bootstrap forever and never bound its fetches."""
        store = enabled_store()
        poller = Poller(store, [])

        await poller.poll_league_events(guild, EventPollState())

        assert store["ConfirmedId"] == 0
        assert store["ConfirmedCreatedAt"] is not None


class TestSteadyState:
    async def test_processes_dispatches_and_posts_new_events(self, guild):
        store = primed_store()
        poller = Poller(store, [evt(i) for i in range(1, 9)])

        await poller.poll_league_events(guild, EventPollState())

        assert poller.bot.dispatch.call_count == 3
        assert sum(len(call["embeds"]) for call in poller.sent) == 3
        assert store["SeenIds"] == [6, 7, 8]
        assert store["TotalProcessed"] == 3

    async def test_dispatches_the_local_dataclass(self, guild):
        """Consumers must not be coupled to the generated client model."""
        store = primed_store()
        poller = Poller(store, [evt(6)])

        await poller.poll_league_events(guild, EventPollState())

        event_name, _guild, event = poller.bot.dispatch.call_args.args
        assert event_name == "rsc_league_event"
        assert isinstance(event, LeagueEventData)

    async def test_watermark_lags_behind_processed_events(self, guild):
        store = primed_store()
        poller = Poller(store, [evt(i) for i in range(1, 9)])

        await poller.poll_league_events(guild, EventPollState())

        assert store["ConfirmedId"] == 5, "watermark must not jump to the newest id"

    async def test_repolling_the_same_response_does_not_duplicate(self, guild):
        """The dedup set is persisted precisely so this cannot happen."""
        store = primed_store()
        events = [evt(i) for i in range(1, 9)]
        state = EventPollState()

        await Poller(store, events).poll_league_events(guild, state)
        second = Poller(store, events)
        await second.poll_league_events(guild, state)

        assert second.bot.dispatch.call_count == 0
        assert second.sent == []


class TestDiscordOutput:
    async def test_every_send_suppresses_mentions(self, guild):
        """`payload` is untrusted API JSON and could contain @everyone."""
        store = primed_store()
        poller = Poller(store, [evt(6, payload={"msg": "@everyone"})])

        await poller.poll_league_events(guild, EventPollState())

        assert poller.sent
        for call in poller.sent:
            mentions = call["allowed_mentions"]
            assert mentions.everyone is False
            assert mentions.roles is False
            assert mentions.users is False

    async def test_filters_suppress_posting_but_not_processing(self, guild):
        store = primed_store(CategoryFilter=["ANN"])
        poller = Poller(store, [evt(6, category="TRN")])

        await poller.poll_league_events(guild, EventPollState())

        assert poller.sent == [], "filtered event must not be posted"
        assert poller.bot.dispatch.call_count == 1, "filtered event must still dispatch"
        assert store["SeenIds"] == [6], "filtered event must still advance the cursor"

    async def test_unconfigured_channel_still_advances(self, guild):
        """Configuring a channel later must not replay everything into it."""
        store = primed_store()
        poller = Poller(store, [evt(i) for i in range(1, 9)])
        poller._get_event_channel = AsyncMock(return_value=None)

        await poller.poll_league_events(guild, EventPollState())

        assert poller.bot.dispatch.call_count == 3
        assert store["SeenIds"] == [6, 7, 8]

    async def test_oversized_backlog_posts_a_summary_instead(self, guild):
        store = primed_store()
        poller = Poller(store, [evt(i) for i in range(6, 1000)])

        await poller.poll_league_events(guild, EventPollState())

        embeds = [e for call in poller.sent for e in call["embeds"]]
        assert len(embeds) == 1
        assert embeds[0].title == "League Event Backlog Skipped"

    async def test_oversized_backlog_skips_to_the_newest_id(self, guild):
        """Safe from a partial walk: the feed is newest-first, so page one
        carries the maximum id."""
        store = primed_store()
        poller = Poller(store, [evt(i) for i in range(6, 1000)])

        await poller.poll_league_events(guild, EventPollState())

        assert store["ConfirmedId"] == 999
        assert store["SeenIds"] == []
        assert poller.bot.dispatch.call_count == 0, "skipped events must not be dispatched"



class TestScope:
    """`league=` is an inner join and cannot reach global (null-league) events."""

    @staticmethod
    def scope_kwargs(poller: "Poller") -> dict:
        return poller.fetch_calls[-1]

    async def test_defaults_to_league_scope(self, guild):
        store = primed_store()
        poller = Poller(store, [evt(6)])

        await poller.poll_league_events(guild, EventPollState())

        assert self.scope_kwargs(poller)["include_global"] is False

    async def test_include_global_is_passed_through(self, guild):
        store = primed_store(IncludeGlobal=True)
        poller = Poller(store, [evt(6)])

        await poller.poll_league_events(guild, EventPollState())

        assert self.scope_kwargs(poller)["include_global"] is True

    async def test_cursor_is_the_lagged_watermark(self, guild):
        """Not the highest id seen. Re-reading the lag window is what catches a
        transaction that committed after a higher id was already visible."""
        store = primed_store(confirmed_id=5, SeenIds=[6, 7, 8])
        poller = Poller(store, [evt(i) for i in range(1, 12)])

        await poller.poll_league_events(guild, EventPollState())

        assert self.scope_kwargs(poller)["id__gt"] == 5

    async def test_window_covers_the_dedup_set_plus_a_batch(self, guild):
        """The window opens at the watermark, so its oldest rows are ids already
        handled. Requesting only a batch's worth would return nothing new and
        the poller would stall."""
        store = primed_store(confirmed_id=5, SeenIds=list(range(6, 106)))
        poller = Poller(store, [evt(i) for i in range(1, 200)])

        await poller.poll_league_events(guild, EventPollState())

        call = self.scope_kwargs(poller)
        assert call["limit"] >= 100 + MAX_EVENTS_PER_TICK

    async def test_makes_progress_with_a_large_dedup_set(self, guild):
        """The stall this guards against is silent, so assert on the outcome."""
        store = primed_store(confirmed_id=5, SeenIds=list(range(6, 106)))
        poller = Poller(store, [evt(i) for i in range(1, 200)])

        await poller.poll_league_events(guild, EventPollState())

        assert poller.bot.dispatch.call_count == MAX_EVENTS_PER_TICK
        dispatched = [c.args[2].id for c in poller.bot.dispatch.call_args_list]
        assert dispatched == list(range(106, 106 + MAX_EVENTS_PER_TICK))

    async def test_global_events_are_processed_when_returned(self, guild):
        store = primed_store(IncludeGlobal=True)
        poller = Poller(store, [LeagueEventData(id=6, league=None, category="SYS", action="MPF", severity="ERR")])

        await poller.poll_league_events(guild, EventPollState())

        assert poller.bot.dispatch.call_count == 1
        _name, _guild, event = poller.bot.dispatch.call_args.args
        assert event.is_global


class TestGating:
    async def test_disabled_guild_is_a_no_op(self, guild):
        store = dict(defaults_guild)
        poller = Poller(store, [evt(i) for i in range(1, 9)])

        await poller.poll_league_events(guild, EventPollState())

        assert poller.bot.dispatch.call_count == 0
        assert store["ConfirmedId"] == 0

    async def test_unconfigured_api_is_a_no_op(self, guild):
        store = enabled_store()
        poller = Poller(store, [evt(1)])
        poller._api_conf = {}

        await poller.poll_league_events(guild, EventPollState())

        assert store["ConfirmedId"] == 0

    async def test_unconfigured_league_is_a_no_op(self, guild):
        """`_league` is a plain dict only populated on successful setup."""
        store = enabled_store()
        poller = Poller(store, [evt(1)])
        poller._league = {}

        await poller.poll_league_events(guild, EventPollState())

        assert store["ConfirmedId"] == 0


class TestHandlers:
    async def test_a_failing_handler_does_not_block_the_cursor(self, guild, monkeypatch):
        from rsc.enums import EventAction

        async def boom(_cog, _guild, _event):
            raise RuntimeError("handler exploded")

        from rsc.events import handlers

        monkeypatch.setitem(handlers.EVENT_HANDLERS, EventAction.PLAYER_SIGNED, boom)

        store = primed_store()
        poller = Poller(store, [evt(6)])

        await poller.poll_league_events(guild, EventPollState())

        assert store["SeenIds"] == [6]
        assert poller.bot.dispatch.call_count == 1
