"""Maintenance for the in-memory name caches that back autocomplete."""

from collections.abc import Iterable, Sequence


def merge_name_cache(cached: Sequence[str], names: Iterable[str], *, full_refresh: bool) -> list[str]:
    """Return the new contents of an autocomplete name cache.

    An unfiltered API query is authoritative and replaces the cache. A filtered
    one can only add, since it says nothing about the names it did not ask for.

    Either way the result is deduplicated. Nothing guarantees the names are
    unique: two teams may share a name, and every path that patches a cache in
    place is one missed guard away from appending a name that is already there.
    Autocomplete renders each entry as its own choice, so a duplicate shows up
    as a repeated option the user cannot tell apart.

    `dict.fromkeys` keeps first seen order, which the tier cache relies on to
    stay in tier position order.
    """
    return list(dict.fromkeys(names if full_refresh else [*cached, *names]))
