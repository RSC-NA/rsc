# Emit a league event when a league player changes

## Why

The Discord bot applies roles and nicknames from league player rows. When a row changes on the website, the bot does not know until its nightly sync at 07:00 UTC. A member can wait most of a day for the right roles. The bot already polls `GET /api/v1/integrations/events/` every 60 seconds, so an event per change lets it sync that one member within about a minute.

## What exists today

- `LeagueEvent` rows and `create_event` in `integrations/services/__init__.py`.
- `EventAction` already declares `PSG`, `PCT`, `PRS`, `PDR`, `NCH`, `TRF`, and `UPD`. Nothing creates events with these actions.
- Events are created today for web trades (`PTR`), waiver claims (`WCW`, `WCL`), activity checks (`ACO`, `ACC`, `PIA`, `PIR`), and errors.

## What the bot needs

One event each time a league player's Discord-visible state changes. That state is the status, tier, team, captain flag, `sub_status`, and the member's RSC name. A created row and a deleted row count as changes.

The payload needs these fields.

| Field | Why |
|---|---|
| `league_player_id` | Identifies the row |
| `discord_id` | The bot resolves the server member from it |
| `season` | The bot decides which season's row applies |
| `status` | For the event log |
| `changed` | The list of changed fields, when known |

Reusing the declared actions avoids an API client release. A new action needs a release of `rsc-api-client` before the bot can read it.

The bot's handler is idempotent. A duplicate event, or an event for a change the bot made itself, costs one API read and no Discord write. So the website can emit on every path without tracking who made the change.

## Paths that change a league player

A `post_save` signal on `LeaguePlayer` covers the `.save()` paths. It misses the queryset paths, which need an explicit `create_event` call.

Queryset `.update()` and `bulk_create` paths, which skip signals.

- Waivers to free agent in `transactions/services/waiver_resolver.py:100` and `tasks/tasks/waivers.py:59`.
- Waiver release to rostered in `tasks/tasks/players.py:23`.
- Removing a team from its franchise in `teams/views/__init__.py:135`.
- The captain flag in `players/views/__init__.py:225` and `players/services/__init__.py:306`.
- `sub_status` in `transactions/services/substitute.py:116`.
- Member transfer in `members/services/member.py:498`.

`.save()` and delete paths.

- Django admin for `LeaguePlayer` and `Member`.
- Staff pages. Patch player, retire inactive, activity check rounds, PermFA approve and adjust, and web trades.
- Member pages. Sign-up and intent to play, which create or delete rows.
- Celery tasks. Waiver claim sign and cut, activity check settle and retire, sub expiry, and PermFA conversion.
- API services. Sign, cut, draft, IR, retire, waiver release, sub, GM changes, and league drop.
- Name changes in `members/services/member.py:435` and `:522`, `members/services/signup.py:153`, and `members/views/admin.py:546`.

## Done when

- Each path above creates one event inside the same database transaction as the change.
- A test per queryset path asserts the event.
- On staging, changing a player's status, tier, team, and name each produces an event that `GET /api/v1/integrations/events/?ordering=id&id__gt=<cursor>` returns.
- The API description states which actions carry a league player payload.

## Context

This unblocks PR G of the bot's sync rework plan, `docs/plans/sync-rework.md` in `RSC-NA/rsc`. The bot keeps its nightly sync as the fallback for any path this issue misses.
