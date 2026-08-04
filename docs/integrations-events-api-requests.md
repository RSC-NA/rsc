# `/integrations/events/` — consumer requests from the Discord bot

> **Status: all requests below have landed.** `ordering`, `id__gt`, `id__lte`,
> `category__in`/`action__in` and `max_limit` are all live, `rsc-api-client` has
> been regenerated, and the bot has been simplified onto them. This is kept as a
> record of what was asked for and why, and as context for the next consumer.

Hand-off document for the **web-rsc-website** project (`~/dev/web-rsc-website`).
Self-contained; assumes no context from the bot repo.

## Context

The RSC Discord bot (`~/dev/rsc`, `rsc/events/`) polls `GET /api/v1/integrations/events/`
on a per-guild timer, mirrors events into a configurable Discord channel, and
re-broadcasts each one internally so other bot features can react.

**The bot tracks its own cursor and always will.** A server-side
`processed`/`acked` flag is explicitly *not* wanted — the feed is designed for
multiple independent consumers, and a per-row flag would mark an event consumed
for everyone the moment any one integration read it. Everything below is about
making a *consumer-owned* cursor cheap and correct, not about server-side state.

### How the bot consumes the feed

1. Persists a **confirmed watermark** (`ConfirmedId`) plus a small **dedup set**
   of ids above it that were already handled.
2. Polls `?league=<id>&id__gte=<ConfirmedId + 1>&created_at__gte=<floor>`.
3. Advances the watermark only to an id first observed **≥ 5 minutes ago**.

Step 3 exists because Postgres allocates sequence values *before* commit. A
transaction holding ids 500-600 can commit *after* id 601 is already visible, so
a naive `max(id)` cursor jumps to 601 and loses 500-600 permanently. This is not
theoretical for draft night or bulk waiver resolution. The lag plus dedup set is
the consumer-side mitigation and it works — no server change is required for it.

---

## Already landed — these solved most of the original problem

Since the bot's design was written, the following appeared and are all working
as needed. No action required, listed so nothing gets reverted:

- `RSCLimitPagination` on the viewset (was previously unpaginated, returning the
  entire table)
- `Meta.indexes` including `(league, id)`, which covers the bot's exact poll
- `Meta.ordering = ["-created_at", "-id"]` — the `-id` tie-break is genuinely
  important and the reasoning in that comment is correct
- `severity` + `EventSeverity`, the `SYS` category, and the system actions
- Nullable `league` for global events, with `guild_id` / `include_global`
- `severity__in`

---

## Requests

### 1. Ascending ordering by `id` — **highest value**

**Ask:** add `OrderingFilter` with `ordering_fields = ["id", "created_at"]`,
keeping the existing default ordering unchanged.

**Why this is the important one.** The endpoint now paginates, but ordering is
still fixed at `-created_at, -id` (newest first). Offset pagination over a
*descending, actively-growing* list drifts: a consumer reading `offset=0`,
then `offset=100`, will have new rows inserted at the front between requests,
which pushes unread rows across the page boundary. Those events are silently
skipped — the consumer never sees them and its cursor moves past them.

Ascending-by-`id` has the opposite property: new rows always append at the
*end*, so a forward walk can never skip. Combined with an `id__gt` cursor it
needs no offset at all, and paging becomes drift-free by construction.

```python
# website/integrations/views/__init__.py
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters as drf_filters


class LeagueEventViewSet(MultiSerializerViewSetMixin, viewsets.ReadOnlyModelViewSet):
    ...
    # DEFAULT_FILTER_BACKENDS is only DjangoFilterBackend, and setting this
    # attribute replaces rather than extends it — so it must be repeated here.
    filter_backends = [DjangoFilterBackend, drf_filters.OrderingFilter]
    ordering_fields = ["id", "created_at"]
    # Preserve the current newest-first default for existing callers.
    ordering = ["-created_at", "-id"]
```

The bot would then poll `?ordering=id&id__gt=<cursor>&limit=100` and drop its
client-side sort entirely.

Also add the matching `OpenApiParameter` to `league_event_list_filter_parameters`
so it shows up in the schema and the generated client:

```python
OpenApiParameter(
    "ordering",
    location=OpenApiParameter.QUERY,
    description="Field to order by. Prefix with `-` for descending. One of: `id`, `created_at`.",
    required=False,
    type=str,
),
```

### 2. `id__gt` — medium

`id__gte` works today via `cursor + 1`, but that arithmetic is a footgun in
every consumer that ever writes it, and `id__gt` is the natural cursor
primitive. Mirrors the existing filter style:

```python
# website/integrations/filters/__init__.py
id__gt = filters.NumberFilter(
    field_name="id",
    lookup_expr="gt",
    help_text="Event ID strictly greater than this value. Preferred cursor filter.",
)
```

Add `"id__gt"` to `Meta.fields` and a matching `OpenApiParameter`.

### 3. Cap `max_limit` on `RSCLimitPagination` — medium, safety

`LimitOffsetPagination.max_limit` defaults to `None`, so
`?limit=100000` is currently honoured and will pull the whole table with
payload blobs into memory. The pagination class fixed the default case; this
closes the explicit-override case.

```python
# website/api_rest/mixins/pagination.py
class RSCLimitPagination(pagination.LimitOffsetPagination):
    default_limit = 100
    max_limit = 500
```

**Check before applying:** this class is shared with other viewsets. Worth a
quick grep for any caller that deliberately requests a very large `limit`; if
one exists, subclass for integrations rather than changing the shared class.

### 4. `id__lte` — lower priority

Now that pagination bounds the response size this is no longer load-critical,
but it makes a bounded backfill window expressible in one request
(`id__gt=X&id__lte=Y`), which is useful for replaying a specific range after an
incident without walking the whole tail.

```python
id__lte = filters.NumberFilter(
    field_name="id",
    lookup_expr="lte",
    help_text="Event ID less than or equal to this value.",
)
```

### 5. `category__in` / `action__in` — lower priority

`severity__in` already exists; `category` and `action` are still single-value.
Multi-value versions would mirror it:

```python
category__in = filters.BaseInFilter(
    field_name="category",
    lookup_expr="in",
    help_text="Comma separated list of category codes, e.g. `TRN,ANN`.",
)
action__in = filters.BaseInFilter(
    field_name="action",
    lookup_expr="in",
    help_text="Comma separated list of action codes, e.g. `WCW,WCL`.",
)
```

**Note the bot will not use these for polling.** Its category/action filters are
display-only — it processes and dispatches every event internally and only
filters what gets *posted* to Discord. These are for ad-hoc queries, the admin
UI, and other consumers.

### 6. Document the pre-commit visibility gap — documentation only

Worth a note in the endpoint description so the next consumer does not have to
rediscover it:

> Event ids are allocated before their transaction commits, so a lower id may
> become visible after a higher one. Consumers polling by id should not treat
> the highest id seen as fully processed immediately; trail it by a few minutes
> and keep a short-lived set of already-handled ids above the watermark.

**Optional, only if you want to remove the caveat rather than document it:** add
a `published_at` column set via `transaction.on_commit(...)`, and expose
ordering/filtering on it. That yields true commit-order and lets consumers drop
the lag window. It is a real schema + backfill + service-layer change though,
and the consumer-side lag already works, so I would not do this unless another
consumer appears that cannot implement a watermark.

---

## Not requested

- **A `processed`/`acked`/`delivered` flag.** Wrong for a multi-consumer feed,
  per the context above.
- **Removing the `-created_at, -id` default ordering.** Request 1 adds an
  *option*; existing callers should keep the current default.

---

## What the bot ended up doing

For reference, and because it constrains what can change server-side without
breaking the consumer. Per tick, per guild:

```
GET /integrations/events/?ordering=id&id__gt=<watermark>&limit=<n>&league=<id>&is_public=true
```

One request. `count` on the envelope reports the whole backlog above the cursor,
so an oversized one is skipped without downloading it. Bootstrap and the backlog
skip use `?ordering=-id&limit=1` for a constant-cost newest-id lookup.

Two server-side behaviours the bot now depends on:

1. **`ordering=id` must keep working.** If `id` were dropped from
   `ordering_fields` the request would silently fall back to the default
   `-created_at, -id`. The poller would then process newest-first while
   advancing an ascending cursor, which **skips events rather than erroring**.
   `tests/test_events_api.py` asserts `ordering` is still in the schema.
2. **`id__gt` is exclusive.** The cursor stores the last confirmed id and asks
   for everything strictly above it.

The bot deliberately does *not* use `category__in`/`action__in`/`severity__in`
on the poll, even though it has display filters for all three. Every event is
re-dispatched internally for other bot features to react to, so the poller has
to see all of them; narrowing happens client-side, at the point of posting.

The watermark still lags by five minutes with a persisted dedup set, because
`ordering=id` fixes page drift but not pre-commit id visibility — a transaction
holding lower ids can still commit after a higher id is already readable. That
is a consumer-side concern and needs nothing from the API.

## Tests worth adding in this repo

`website/integrations/tests/test_views.py` already covers visibility. Additions
that would have caught the issues above:

- `?ordering=id` returns ascending, and paging forward across two pages while
  inserting a new event in between does not skip or repeat a row
- `?id__gt=N` excludes exactly `N`, where `?id__gte=N` includes it
- `?limit=100000` is clamped to `max_limit`
- `?category__in=TRN,ANN` returns the union, and an unknown code is rejected
  rather than silently matching nothing
