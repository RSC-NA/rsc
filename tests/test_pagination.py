"""`iter_pages` is what every "fetch all" path in the cog rides on.

The server clamps an oversized `limit` instead of rejecting it, so none of the
failure modes here raise. They just return fewer rows, which is why each one is
pinned down explicitly.
"""

import logging
from types import SimpleNamespace

import pytest

from rsc.pagination import API_MAX_PAGE_SIZE, check_page_limit, iter_pages


class FakeEndpoint:
    """A limit/offset endpoint over `rows`, optionally clamping like the API's `max_limit`."""

    def __init__(self, rows: list[int], *, max_limit: int | None = None):
        self.rows = rows
        self.max_limit = max_limit
        self.calls: list[tuple[int, int]] = []

    async def fetch(self, limit: int, offset: int) -> SimpleNamespace:
        self.calls.append((limit, offset))
        served = min(limit, self.max_limit) if self.max_limit else limit
        chunk = self.rows[offset : offset + served]
        has_next = offset + served < len(self.rows)
        return SimpleNamespace(results=chunk, next="http://next" if has_next else None)


async def collect(endpoint: FakeEndpoint, **kwargs) -> list[int]:
    return [row async for row in iter_pages(endpoint.fetch, **kwargs)]


async def test_yields_every_row_in_order():
    endpoint = FakeEndpoint(list(range(25)))

    assert await collect(endpoint, per_page=10) == list(range(25))
    assert endpoint.calls == [(10, 0), (10, 10), (10, 20)]


async def test_advances_by_rows_received_when_server_clamps():
    """The `max_limit` regression: asked for 10, served 4.

    Stepping the offset by the requested size would silently skip six rows a page.
    """
    endpoint = FakeEndpoint(list(range(10)), max_limit=4)

    assert await collect(endpoint, per_page=10) == list(range(10))
    assert [offset for _, offset in endpoint.calls] == [0, 4, 8]


async def test_stops_on_missing_next_without_a_trailing_request():
    endpoint = FakeEndpoint(list(range(20)))

    await collect(endpoint, per_page=10)

    assert len(endpoint.calls) == 2


async def test_empty_first_page_yields_nothing():
    endpoint = FakeEndpoint([])

    assert await collect(endpoint) == []
    assert len(endpoint.calls) == 1


async def test_none_results_is_treated_as_empty():
    async def fetch(limit: int, offset: int) -> SimpleNamespace:
        return SimpleNamespace(results=None, next=None)

    assert [row async for row in iter_pages(fetch)] == []


async def test_empty_page_with_a_next_link_does_not_loop_forever():
    calls = 0

    async def fetch(limit: int, offset: int) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(results=[], next="http://next")

    assert [row async for row in iter_pages(fetch)] == []
    assert calls == 1


@pytest.mark.parametrize(("asked", "sent"), [(5000, API_MAX_PAGE_SIZE), (API_MAX_PAGE_SIZE, API_MAX_PAGE_SIZE), (0, 1), (-3, 1)])
async def test_per_page_is_clamped_to_what_the_api_serves(asked: int, sent: int):
    endpoint = FakeEndpoint([1])

    await collect(endpoint, per_page=asked)

    assert endpoint.calls == [(sent, 0)]


async def test_defaults_to_the_largest_page():
    endpoint = FakeEndpoint([1])

    await collect(endpoint)

    assert endpoint.calls == [(API_MAX_PAGE_SIZE, 0)]


async def test_fetch_errors_propagate():
    async def fetch(limit: int, offset: int) -> SimpleNamespace:
        raise RuntimeError("api down")

    with pytest.raises(RuntimeError, match="api down"):
        _ = [row async for row in iter_pages(fetch)]


def test_check_page_limit_warns_only_above_the_cap(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING, logger="red.rsc.pagination"):
        check_page_limit(API_MAX_PAGE_SIZE, caller="players()")
        assert caplog.records == []

        check_page_limit(API_MAX_PAGE_SIZE + 1, caller="players()")

    assert len(caplog.records) == 1
    assert "players()" in caplog.records[0].getMessage()
