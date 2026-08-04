"""Tests for the real `EventMixIn` API layer.

`test_events_poller.py` fakes these out to test the poll flow. Here they run
against a stubbed `IntegrationsApi`, so the request shape and the lenient
fallback are pinned down.
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rsc.events.events import EventMixIn
from rsc.events.models import EventPollState
from rsc.exceptions import RscException

GUILD_ID = 1
LEAGUE_ID = 7


class FakePage:
    def __init__(self, count: int, results: list):
        self.count = count
        self.results = results


class FakeEvent:
    """Mimics the generated `LeagueEventList` closely enough for `from_api`."""

    def __init__(self, event_id: int, league: int | None = LEAGUE_ID):
        self.id = event_id
        self.league = league
        self.category = "TRN"
        self.action = "PSG"
        self.severity = "INF"
        self.actor = None
        self.object_id = None
        self.payload = {"n": event_id}
        self.is_public = True
        self.created_at = datetime.now(UTC)


class FakeApi:
    """Serves a fixed corpus honouring `ordering`, `id__gt` and `limit`."""

    def __init__(self, total: int, *, fail_typed: bool = False):
        self.corpus = [FakeEvent(i) for i in range(1, total + 1)]
        self.calls: list[dict] = []
        self.fail_typed = fail_typed

    def _window(self, kwargs: dict) -> tuple[int, list[FakeEvent]]:
        matched = [e for e in self.corpus if kwargs.get("id__gt") is None or e.id > kwargs["id__gt"]]
        ordered = sorted(matched, key=lambda e: e.id, reverse=kwargs.get("ordering") == "-id")
        return len(matched), ordered[: kwargs.get("limit") or len(ordered)]

    async def integrations_events_list(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_typed:
            raise ValidationError.from_exception_data("LeagueEventList", [])
        count, window = self._window(kwargs)
        return FakePage(count=count, results=window)

    async def integrations_events_list_without_preload_content(self, **kwargs):
        self.calls.append(kwargs)
        count, window = self._window(kwargs)
        body = json.dumps(
            {
                "count": count,
                "next": None,
                "previous": None,
                "results": [
                    {
                        "id": e.id,
                        "league": e.league,
                        "category": e.category,
                        # An action the installed client does not know about.
                        "action": "BRAND_NEW_ACTION",
                        "severity": e.severity,
                        "payload": e.payload,
                        "is_public": True,
                        "created_at": e.created_at.isoformat(),
                    }
                    for e in window
                ],
            }
        )
        response = MagicMock()
        response.status = 200

        async def read():
            return body.encode()

        response.read = read
        return response


class Fetcher(EventMixIn):
    def __init__(self):
        self.config = MagicMock()
        self.bot = MagicMock()
        self._api_conf = {GUILD_ID: object()}
        self._league = {GUILD_ID: LEAGUE_ID}
        self._event_state: dict[int, EventPollState] = {}


Fetcher.__abstractmethods__ = frozenset()


@pytest.fixture
def guild() -> MagicMock:
    g = MagicMock()
    g.id = GUILD_ID
    g.name = "Test Guild"
    return g


def stub_api(api: FakeApi):
    """Patch `ApiClient`/`IntegrationsApi` in the module under test."""
    client_patch = patch("rsc.events.events.ApiClient")
    api_patch = patch("rsc.events.events.IntegrationsApi", return_value=api)
    return client_patch, api_patch


async def run_fetch(api: FakeApi, guild, **kwargs):
    client_patch, api_patch = stub_api(api)
    with client_patch as client_cls, api_patch:
        client_cls.return_value.__aenter__.return_value = MagicMock()
        client_cls.return_value.__aexit__.return_value = False
        kwargs.setdefault("id__gt", 0)
        kwargs.setdefault("limit", 25)
        return await Fetcher().fetch_league_events(guild, **kwargs)


async def run_newest(api: FakeApi, guild, **kwargs):
    client_patch, api_patch = stub_api(api)
    with client_patch as client_cls, api_patch:
        client_cls.return_value.__aenter__.return_value = MagicMock()
        client_cls.return_value.__aexit__.return_value = False
        return await Fetcher().newest_league_event(guild, **kwargs)


class TestFetchWindow:
    async def test_single_request_returns_the_oldest_slice(self, guild):
        """`ordering=id` means one request gets exactly what to process next."""
        api = FakeApi(total=100)
        page = await run_fetch(api, guild, id__gt=0, limit=25)

        assert len(api.calls) == 1
        assert [e.id for e in page.events] == list(range(1, 26))

    async def test_count_reports_the_whole_backlog_not_the_slice(self, guild):
        """`count` is what makes an oversized backlog detectable without
        downloading it."""
        api = FakeApi(total=100)
        page = await run_fetch(api, guild, id__gt=0, limit=25)

        assert page.count == 100
        assert len(page.events) == 25

    async def test_cursor_is_exclusive(self, guild):
        """`id__gt`, not `id__gte`, so no off-by-one arithmetic at call sites."""
        api = FakeApi(total=10)
        page = await run_fetch(api, guild, id__gt=5, limit=25)

        assert [e.id for e in page.events] == [6, 7, 8, 9, 10]

    async def test_empty_window(self, guild):
        api = FakeApi(total=5)
        page = await run_fetch(api, guild, id__gt=5, limit=25)

        assert page.count == 0
        assert page.events == []


class TestRequestShape:
    async def test_requests_ascending_order(self, guild):
        """Ascending plus an exclusive cursor is what makes paging drift-free:
        new events append past the window rather than shifting it."""
        api = FakeApi(total=10)
        await run_fetch(api, guild)

        assert api.calls[0]["ordering"] == "id"

    async def test_league_scope_by_default(self, guild):
        api = FakeApi(total=1)
        await run_fetch(api, guild)

        call = api.calls[0]
        assert call["league"] == LEAGUE_ID
        assert call["guild_id"] is None
        assert call["include_global"] is None

    async def test_global_scope_switches_to_guild_id(self, guild):
        """`league=` is an inner join and cannot return null-league events."""
        api = FakeApi(total=1)
        await run_fetch(api, guild, include_global=True)

        call = api.calls[0]
        assert call["league"] is None
        assert call["guild_id"] == GUILD_ID
        assert call["include_global"] is True

    async def test_is_public_is_explicit_by_default(self, guild):
        """Omitting it makes the visible id set depend on key privilege."""
        api = FakeApi(total=1)
        await run_fetch(api, guild)

        assert api.calls[0]["is_public"] is True

    async def test_include_private_drops_the_constraint(self, guild):
        api = FakeApi(total=1)
        await run_fetch(api, guild, include_private=True)

        assert api.calls[0]["is_public"] is None

    async def test_never_narrows_by_category_action_or_severity(self, guild):
        """The API supports `__in` for all three, but every event must still be
        dispatched internally, so the poller has to see all of them."""
        api = FakeApi(total=1)
        await run_fetch(api, guild)

        for param in ("category", "category__in", "action", "action__in", "severity", "severity__in"):
            assert param not in api.calls[0]

    async def test_request_timeout_is_set(self, guild):
        """A hung call would otherwise stall every guild, since ticks are serial."""
        api = FakeApi(total=1)
        await run_fetch(api, guild)

        assert api.calls[0]["_request_timeout"] is not None


class TestNewestEvent:
    async def test_returns_the_highest_id_in_one_request(self, guild):
        api = FakeApi(total=5000)
        newest = await run_newest(api, guild)

        assert newest is not None
        assert newest.id == 5000
        assert len(api.calls) == 1

    async def test_uses_descending_order_and_a_limit_of_one(self, guild):
        """Constant cost regardless of feed size - this is what makes bootstrap
        and the backlog skip cheap."""
        api = FakeApi(total=5000)
        await run_newest(api, guild)

        call = api.calls[0]
        assert call["ordering"] == "-id"
        assert call["limit"] == 1
        assert call["id__gt"] is None

    async def test_returns_none_on_an_empty_feed(self, guild):
        api = FakeApi(total=0)
        assert await run_newest(api, guild) is None


class TestLenientFallback:
    async def test_unknown_enum_falls_back_to_raw_parsing(self, guild):
        """One unknown value fails validation for the whole page, not one row."""
        api = FakeApi(total=5, fail_typed=True)
        page = await run_fetch(api, guild)

        assert page.count == 5
        assert len(page.events) == 5
        assert page.events[0].action == "BRAND_NEW_ACTION"
        assert page.events[0].event_action is None, "unknown action must degrade, not raise"

    async def test_fallback_preserves_the_request_shape(self, guild):
        api = FakeApi(total=5, fail_typed=True)
        await run_fetch(api, guild, id__gt=2, limit=10)

        fallback_call = api.calls[-1]
        assert fallback_call["ordering"] == "id"
        assert fallback_call["id__gt"] == 2
        assert fallback_call["limit"] == 10

    async def test_fallback_raises_on_an_http_error(self, guild):
        """`_without_preload_content` never raises ApiException itself, so the
        status has to be checked by hand."""
        api = FakeApi(total=5, fail_typed=True)

        async def erroring(**kwargs):
            response = MagicMock()
            response.status = 500

            async def read():
                return b"<html>Internal Server Error</html>"

            response.read = read
            return response

        api.integrations_events_list_without_preload_content = erroring

        with pytest.raises(RscException):
            await run_fetch(api, guild)

    async def test_fallback_rejects_a_bare_list(self, guild):
        """A bare array would mean the server dropped pagination unexpectedly."""
        api = FakeApi(total=5, fail_typed=True)

        async def bare_list(**kwargs):
            response = MagicMock()
            response.status = 200

            async def read():
                return b'[{"id": 1}]'

            response.read = read
            return response

        api.integrations_events_list_without_preload_content = bare_list

        with pytest.raises(RscException):
            await run_fetch(api, guild)

    async def test_fallback_rejects_malformed_json(self, guild):
        api = FakeApi(total=5, fail_typed=True)

        async def garbage(**kwargs):
            response = MagicMock()
            response.status = 200

            async def read():
                return b"not json at all"

            response.read = read
            return response

        api.integrations_events_list_without_preload_content = garbage

        with pytest.raises(RscException):
            await run_fetch(api, guild)
