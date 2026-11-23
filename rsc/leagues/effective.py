"""Which league player row a sync applies while two seasons overlap.

The API's default listing holds one season. Around a season change a member can
have a row in the season that is ending, a row in the season taking sign-ups, or
both, and a member who has not answered the intent prompt has only the older one.
"""

from collections.abc import Collection, Iterable
from datetime import datetime
from typing import NamedTuple

from rscapi.models.league_player import LeaguePlayer
from rscapi.models.season import Season

from rsc.enums import Status

ROSTERED = frozenset({Status.ROSTERED, Status.RENEWED, Status.IR, Status.AGMIR, Status.UNSIGNED_GM})
NOT_PLAYING = frozenset({Status.DROPPED, Status.FORMER, Status.BANNED})


class SyncSeasons(NamedTuple):
    """The seasons one sync reads, and what the open sign-up season says about them."""

    seasons: list[Season]
    signups_open: bool
    not_returning: frozenset[int]
    """Discord ids of members who declared "not returning" for the sign-up season."""


def pick_effective_row(
    rows: Iterable[LeaguePlayer],
    seasons: Collection[Season],
    now: datetime,
    signups_open: bool,
    not_returning: bool = False,
) -> LeaguePlayer | None:
    """The one row a sync applies to a member, or None when the member is non-playing.

    `rows` are one member's rows, at most one per season in `seasons`. A row's
    `season` is the season number.

    1. A rostered row in a season that has not ended wins. The older one wins
       when two qualify, because its season is still being played.
    2. Otherwise the row in the newest season wins.
    3. Otherwise the member's older row holds while sign-ups are open, unless the
       member declared "not returning".
    """
    by_age = sorted(rows, key=lambda row: row.season)
    if not by_age:
        return None

    ended = {s.number for s in seasons if s.end_date and s.end_date < now}
    for row in by_age:
        if row.status in ROSTERED and row.season not in ended:
            return row

    latest = by_age[-1]
    if latest.season == max((s.number or 0 for s in seasons), default=0):
        return latest
    if signups_open and not not_returning:
        return latest
    return None


def is_playing(row: LeaguePlayer | None) -> bool:
    """Whether a member's effective row keeps them out of the non-playing sync."""
    return row is not None and row.status not in NOT_PLAYING
