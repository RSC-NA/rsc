# Events

**Package:** [rsc/events/](../../rsc/events/) · **Mixin(s):** `EventMixIn`

The RSC website keeps a feed of league events: signings, cuts, trades, waiver claims, notices, and system problems such as a failed nightly MMR pull or a tracker that could not be merged. This module polls that feed for each server and posts the events as embeds in a log channel staff choose, so staff can see what happened on the website without checking it. It also passes each event to the rest of the bot, which is how a trade made on the website gets announced in the transactions channel.

It is off by default and is set up by the bot operator.

## Using it

**Bot operator, setting it up**

1. Make sure the server's RSC API key, URL and league are configured (the poller skips any server without them).
2. `/rsc events channel` to pick the log channel or thread. The reply warns if the bot lacks Send Messages or Embed Links there.
3. `/rsc events toggle` to turn polling on. On the first poll the bot starts from the newest event; nothing older is posted.
4. Optionally `/rsc events interval` (default 60 seconds), `/rsc events filter` to limit what is posted, `/rsc events private` to include non-public events (only works with an admin API key), and `/rsc events global` to include or exclude events with no league (only visible to a superuser key).

**Staff, day to day**

- Read the log channel. Warning, error and critical events are coloured yellow, orange and red; info events use the formatter's own colour (blue for the generic embed).
- `/rsc events status` shows whether the poller is healthy, where its cursor is, and the last error.
- `/rsc events replay <id>` re-renders one event privately (or posts it to the log channel with `post`), for example to see the raw payload of a truncated tracker report. It does not move the cursor.
- If the poller fails 5 times in a row a red "League Event Poller Unhealthy" embed is posted once; a green "Recovered" embed follows when it works again.

## Commands

All are under `/rsc events`. The `/rsc` group has `default_permissions` of Manage Server; some subcommands also require the bot owner (Red's owner list).

| Command | Who can run it | What it does |
|---|---|---|
| `/rsc events settings` | Manage Server | Shows enabled state, interval, private/global flags, log channel and filters. |
| `/rsc events status` | Manage Server | Shows loop state, confirmed event ID, latest event time, pending dedup IDs, lifetime and since-start counts, last poll, last success, consecutive failures and last error. |
| `/rsc events replay <id> [post]` | Manage Server | Fetches one event by ID and shows its embed privately, or posts it to the log channel with `post: True`. |
| `/rsc events toggle` | bot owner | Turns polling on or off for this server. |
| `/rsc events channel <channel>` | bot owner | Sets the log channel (text channel or thread). |
| `/rsc events interval <seconds>` | bot owner | Sets the poll interval, 30 to 3600 seconds. |
| `/rsc events private` | bot owner | Toggles including non-public events. |
| `/rsc events global` | bot owner | Toggles including events that belong to no league. |
| `/rsc events cursor <id>` | bot owner | After a confirm prompt, moves the cursor so events at or below `id` count as done. Rewinding re-processes and re-posts everything above it. |
| `/rsc events filter` | bot owner | Opens three menus (categories, actions, severities) to choose what is posted. Empty means all. Each change saves immediately. |

## Configuration

Red Config custom group `Events`, keyed by guild ID.

| Key | Default | Set by |
|---|---|---|
| `EventsEnabled` | `False` | `/rsc events toggle` |
| `EventChannel` | `None` | `/rsc events channel`; cleared automatically if the channel is deleted or the bot loses permission |
| `EventInterval` | `60` | `/rsc events interval` |
| `IncludePrivate` | `False` | `/rsc events private` |
| `IncludeGlobal` | `True` | `/rsc events global` |
| `CategoryFilter` | `[]` | `/rsc events filter` |
| `ActionFilter` | `[]` | `/rsc events filter` |
| `SeverityFilter` | `[]` | `/rsc events filter` |
| `ConfirmedId` | `0` | The poller (cursor watermark); `/rsc events cursor` |
| `ConfirmedCreatedAt` | `None` | The poller; `/rsc events cursor` |
| `SeenIds` | `[]` | The poller (IDs above the watermark already handled) |
| `TotalProcessed` | `0` | The poller |

Filters store the API's short codes, for example `TRN` or `PTR`.

## Background work

- **`rsc_events_loop`**, a `discord.ext.tasks` loop ticking every 30 seconds. Each server is polled when its own interval is due. Start times are staggered randomly at startup. A failed poll backs off exponentially (30 s × 2^failures, at most 900 s). The loop is cancelled on cog unload and restarts itself if it ever crashes.
- **Posting.** Embeds go to the log channel in messages of up to 10 embeds and 6000 characters, one second apart, with all mentions disabled. At most 25 events are processed per server per tick.
- **Backlog skip.** If more than 500 events are waiting above the cursor, the bot jumps the cursor to the newest event and posts one "League Event Backlog Skipped" embed with the ID range instead of the events.
- **Re-broadcast.** Every in-scope event is dispatched as the bot event `rsc_league_event` with `(guild, LeagueEventData)`, regardless of display filters. Listen with `@commands.Cog.listener()` `on_rsc_league_event`. No listener uses it yet.
- **Handlers.** `EVENT_HANDLERS` in [handlers.py](../../rsc/events/handlers.py) maps an action to a side effect. Today there is one: `PTR` (player traded) calls `process_trade_event` in [rsc/transactions/trade_announce.py](../../rsc/transactions/trade_announce.py), which announces the trade in the transactions channel. Because of that, `PTR` events are never posted to the log channel (`SUPPRESSED_ACTIONS`), though `/rsc events replay` still shows them.

## How it works

- [events.py](../../rsc/events/events.py): `EventMixIn`, the poll loop, cursor handling, posting, the `/rsc events` commands, and the API calls.
- [models.py](../../rsc/events/models.py): tuning constants, `LeagueEventData` (the bot's own frozen copy of an event, independent of the generated `rscapi` models), `EventPollState` (per-server runtime state, not saved), and `plan_batch`, the pure function that decides what to process and how far the cursor may move.
- [formatters.py](../../rsc/events/formatters.py): embeds. Dedicated layouts for `PTR`, `WCW`/`WCL` (waiver claim won/lost) and `TMF`/`TLC` (tracker merge failed / tracker link conflict); everything else, including actions this bot does not know, gets a generic embed with the payload as JSON (cut at 3000 characters). A formatter that throws falls back to the generic embed.
- [handlers.py](../../rsc/events/handlers.py): side effects per action, kept apart from formatters because handlers ping people and edit members while formatter output is untrusted text sent with mentions off.
- [views.py](../../rsc/events/views.py): the filter menus and the cursor confirm prompt.

**API calls** (via `rscapi.IntegrationsApi`, see [external services](../external-services.md) and [the events API requests](../integrations/events-api-requests.md)):

- Poll: `GET /api/v1/integrations/events/` with `ordering=id`, `id__gt=<ConfirmedId>`, `limit=min(len(SeenIds) + 25, 1000)`, `is_public=true` (or omitted when private events are included), and either `league=<league id>` or, when `IncludeGlobal` is on, `guild_id=<guild id>&include_global=true`.
- Newest event (bootstrap and backlog skip): same endpoint with `ordering=-id&limit=1`.
- Replay: `GET /api/v1/integrations/events/<id>/`.

**Cursor.** The cursor is the bot's own; the website keeps no "read" flag. `ConfirmedId` only advances to an ID first seen at least 5 minutes earlier (`WATERMARK_LAG`), because Postgres hands out IDs before commit and a lower ID can appear after a higher one. IDs above the watermark that were already handled sit in `SeenIds` so they are not repeated. State is saved once per tick, and only when something changed.

**Scope.** With `IncludeGlobal` on, the API returns events for any league sharing this server. `_in_scope` drops events from other leagues before dispatch or handlers run, so a sibling league's trade is never announced here. Events with no league are always in scope.

**Filters are display only.** They never go to the API: filtering server-side would hide the highest ID and stall the cursor. Every in-scope event is dispatched and handled whatever the filters say.

## Gotchas

- Turning it on never posts history. The first poll starts at the newest event. Use `/rsc events cursor` to rewind on purpose.
- `IncludeGlobal` defaults to on, and every server with it on logs its own copy of global events.
- Events are posted on the next poll, so up to one interval late. The cursor confirms them about 5 minutes later; until then they are re-read each poll and `SeenIds` (saved in Config) stops them being posted twice.
- Handlers run before state is saved, so a crash or reload mid-batch re-runs the batch's handlers. Handlers must be idempotent (the trade announcer keeps its own dedup).
- If the log channel is deleted or the bot loses permission there, the channel setting is cleared and events keep being processed without being posted. Set the channel again.
- The interval is checked on the 30 second tick, so the real interval is rounded up to a multiple of 30 seconds.
- `/rsc events private` only matters if the server's API key has admin privileges.
- `/rsc events settings`, `status` and `replay` are open to anyone with Manage Server; the rest need the bot owner.
