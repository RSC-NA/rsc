"""Paging over the RSC API's limit/offset list endpoints.

Every paginated endpoint uses the server's `RSCLimitPagination`, which serves
`API_DEFAULT_PAGE_SIZE` rows when `limit` is absent (or 0) and silently clamps
anything above `API_MAX_PAGE_SIZE`. Neither case is an error, so a caller asking
for `limit=10000` gets a short list and no way to tell. Anything that needs the
whole set has to follow `next`, which is what `iter_pages` does.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Protocol, TypeVar

log = logging.getLogger("red.rsc.pagination")

# Mirrors `RSCLimitPagination` in the API (default_limit / max_limit).
API_DEFAULT_PAGE_SIZE = 100
API_MAX_PAGE_SIZE = 500

T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)


class Page(Protocol[T_co]):
    """Structural match for every generated `Paginated*List` model."""

    @property
    def results(self) -> Sequence[T_co] | None: ...

    @property
    def next(self) -> str | None: ...


async def iter_pages(
    fetch: Callable[[int, int], Awaitable[Page[T]]],
    *,
    per_page: int = API_MAX_PAGE_SIZE,
) -> AsyncIterator[T]:
    """Yield every row of a paginated endpoint.

    `fetch(limit, offset)` performs one request and returns the page model.

    The offset advances by the number of rows *received*, not the number asked
    for. Stepping by `per_page` skips rows whenever the server hands back a
    smaller page than requested, which is exactly what a lowered `max_limit`
    does. `next` is the stop signal, so a full sweep never costs a trailing
    empty request.
    """
    per_page = max(1, min(per_page, API_MAX_PAGE_SIZE))
    offset = 0
    while True:
        page = await fetch(per_page, offset)
        results = page.results or []
        for item in results:
            yield item

        if not results or not page.next:
            break

        offset += len(results)


def check_page_limit(limit: int, *, caller: str) -> None:
    """Warn when a single list call asks for more than the API will return.

    The API clamps rather than rejects, so without this an oversized `limit`
    just produces a quietly truncated result.
    """
    if limit > API_MAX_PAGE_SIZE:
        log.warning(
            "%s called with limit=%d, but the API caps a page at %d. Results will be truncated; use the paged_* generator instead.",
            caller,
            limit,
            API_MAX_PAGE_SIZE,
        )
