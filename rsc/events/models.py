"""Local models for the league event poller.

The dataclasses here are deliberately independent of the generated `rscapi`
models. `LeagueEventData` is what gets dispatched to listeners, so regenerating
the API client does not change the shape consumers see.

`category`/`action`/`severity` are stored as plain strings with enum accessors
rather than enum members. That keeps the dispatched payload decoupled from the
generated client, and means an event whose enum this bot does not recognise still
renders as a generic embed instead of raising.
"""

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from rsc.enums import EventAction, EventCategory, EventSeverity

if TYPE_CHECKING:
    from rscapi.models.league_event_detail import LeagueEventDetail
    from rscapi.models.league_event_list import LeagueEventList

log = logging.getLogger("red.rsc.events.models")

# Base tick of the poll loop. Per guild intervals are enforced on top of this.
EVENT_LOOP_TICK = 30
# How long an observed id must sit before it is trusted as a watermark. Covers
# the window where a transaction that took lower ids commits after a higher id
# already became visible.
WATERMARK_LAG = 300
# Events processed and posted to Discord per guild per tick.
MAX_EVENTS_PER_TICK = 25
# Discord allows 10 embeds per message.
MAX_EMBEDS_PER_MESSAGE = 10
# Above this many events waiting above the cursor, skip the backlog and post a
# summary rather than grinding through it 25 at a time.
MAX_BACKLOG = 500
# Ceiling on rows requested in one poll. The window has to cover the ids awaiting
# watermark confirmation plus a fresh batch, and `MAX_BACKLOG` bounds how large
# that can get, so this only guards against a pathological dedup set.
MAX_WINDOW_LIMIT = 1000
# Consecutive poll failures before a single alert is posted.
FAILURE_ALERT_THRESHOLD = 5
# Ceiling on the backoff between retries after failures.
MAX_BACKOFF = 900
# Soft warning threshold for the dedup set. It is bounded by the lag window in
# steady state, and by the backlog size while draining.
SEEN_IDS_WARN = 10_000

#: Actions with a dedicated announcer of their own. Their handler already posts a
#: richer, human-facing message elsewhere - `PTR` goes to the transaction channel
#: via `rsc.transactions.trade_announce` - so a log embed would only duplicate it.
#: Suppression is display only, exactly like the user filters: these events are
#: still fetched, dispatched, handled and counted toward the cursor. `/rsc events
#: replay` deliberately bypasses it so an operator can still inspect one.
SUPPRESSED_ACTIONS = frozenset({EventAction.PLAYER_TRADED})


def _enum_value(value: object) -> str | None:
    """Normalize a generated enum member to its plain string value.

    `CategoryEnum`/`ActionEnum` are `(str, Enum)`, not `StrEnum`, so `str()` on a
    member yields `"CategoryEnum.TRN"` rather than `"TRN"`. Filters compare
    against config values, so the wrong form silently never matches.
    """
    if value is None:
        return None
    return str(getattr(value, "value", value))


@dataclass(frozen=True)
class LeagueEventData:
    """A single `/integrations/events/` league event.

    `category` and `action` are raw strings. Use `event_category` /
    `event_action` for the parsed enum, which is `None` when the API sends a
    value this bot does not know about yet.
    """

    id: int
    #: None for global events that are not scoped to a single league, such as a
    #: failure in the nightly MMR pull which runs across every league at once.
    league: int | None = None
    category: str | None = None
    action: str | None = None
    severity: str | None = None
    actor_name: str | None = None
    actor_discord_id: int | None = None
    object_id: int | None = None
    payload: Any = None
    is_public: bool = True
    created_at: datetime | None = None

    @property
    def event_category(self) -> EventCategory | None:
        if self.category is None:
            return None
        try:
            return EventCategory(self.category)
        except ValueError:
            return None

    @property
    def event_action(self) -> EventAction | None:
        if self.action is None:
            return None
        try:
            return EventAction(self.action)
        except ValueError:
            return None

    @property
    def event_severity(self) -> EventSeverity | None:
        if self.severity is None:
            return None
        try:
            return EventSeverity(self.severity)
        except ValueError:
            return None

    @property
    def is_global(self) -> bool:
        return self.league is None

    @classmethod
    def from_api(cls, event: "LeagueEventList | LeagueEventDetail") -> "LeagueEventData | None":
        """Build from a generated `LeagueEventList` or `LeagueEventDetail`.

        Returns `None` for an event with no id. Every field on the generated
        model is `Optional`, and an event without an id cannot be tracked by the
        cursor, so it is unprocessable rather than merely incomplete.

        Note this reads attributes directly. Do not use the generated
        `to_dict()`/`to_json()` on these models: every field is marked
        `readOnly` so both return `{"actor": None}`.
        """
        if event.id is None:
            return None

        actor = getattr(event, "actor", None)

        return cls(
            id=event.id,
            league=event.league,
            category=_enum_value(event.category),
            action=_enum_value(event.action),
            severity=_enum_value(event.severity),
            actor_name=getattr(actor, "name", None),
            actor_discord_id=getattr(actor, "discord_id", None),
            object_id=event.object_id,
            payload=event.payload,
            is_public=bool(event.is_public),
            created_at=event.created_at,
        )


@dataclass
class EventPollState:
    """Per guild runtime state. Not persisted.

    Losing this on a cog reload costs at most a duplicate health alert, which is
    cheaper than writing to Config on every tick.
    """

    next_due: float = 0.0
    next_retry: float = 0.0
    last_poll: datetime | None = None
    last_success: datetime | None = None
    consecutive_failures: int = 0
    last_error: str | None = None
    processed_since_start: int = 0
    alerted: bool = False
    # (monotonic timestamp, frontier id) observations awaiting maturity.
    watermark_history: list[tuple[float, int]] = field(default_factory=list)


@dataclass
class EventPage:
    """One poll's worth of fetched events plus the server's total for the window.

    `count` comes from the paginated envelope, so an oversized backlog is
    detectable from the first page without downloading the rest of it.
    """

    events: list[LeagueEventData]
    count: int


@dataclass
class BatchPlan:
    """Result of `plan_batch`. Everything needed to act on and persist a poll."""

    to_process: list[LeagueEventData]
    confirmed_id: int
    seen_ids: set[int]
    watermark_history: list[tuple[float, int]]
    #: Eligible-but-unprocessed events left over after the per tick cap.
    remaining: int

    @property
    def advanced(self) -> bool:
        return bool(self.to_process) or self.remaining > 0


def plan_batch(
    events: Iterable[LeagueEventData],
    *,
    confirmed_id: int,
    seen_ids: set[int],
    watermark_history: Sequence[tuple[float, int]],
    now: float,
    lag: float = WATERMARK_LAG,
    max_events: int = MAX_EVENTS_PER_TICK,
) -> BatchPlan:
    """Decide what to process from one poll response, and how far to advance.

    Pure so the ordering and out-of-order-commit cases are testable without a
    live API. `now` is a `time.monotonic()` reading, matching the timestamps in
    `watermark_history`.

    The watermark only advances to a frontier that was first observed at least
    `lag` seconds ago. Postgres allocates sequence values before commit, so a
    transaction holding ids 500-600 can commit *after* id 601 is already
    visible. Advancing straight to the highest id seen would make 500-600
    permanently invisible. The lag plus `seen_ids` trades a re-read of the lag
    window for not losing those events.
    """
    # Events with no id are dropped at conversion (`LeagueEventData.from_api`
    # returns None) since the id *is* the cursor and cannot be substituted.
    # The API orders by -created_at and offers no `ordering` param, so sort here.
    eligible = sorted((e for e in events if e.id > confirmed_id), key=lambda e: e.id)
    fresh = [e for e in eligible if e.id not in seen_ids]

    to_process = fresh[:max_events]
    remaining = len(fresh) - len(to_process)

    # The frontier is the highest id below which everything is now processed.
    # Because `eligible` is ascending and the cap slices from the front, every
    # eligible id at or below the last one taken is either processed now or was
    # processed in an earlier poll.
    if remaining:
        frontier = to_process[-1].id
    elif eligible:
        frontier = eligible[-1].id
    else:
        frontier = confirmed_id

    history = list(watermark_history)
    if frontier > confirmed_id:
        history.append((now, frontier))

    # Advance only to frontiers that have had time to settle.
    matured = [fid for ts, fid in history if now - ts >= lag]
    new_confirmed = max([confirmed_id, *matured])
    history = [(ts, fid) for ts, fid in history if now - ts < lag]

    new_seen = {i for i in seen_ids if i > new_confirmed}
    new_seen.update(e.id for e in to_process if e.id > new_confirmed)

    if len(new_seen) > SEEN_IDS_WARN:
        log.warning("Event dedup set is unusually large (%d ids). Backlog draining or watermark stalled.", len(new_seen))

    return BatchPlan(
        to_process=to_process,
        confirmed_id=new_confirmed,
        seen_ids=new_seen,
        watermark_history=history,
        remaining=remaining,
    )
