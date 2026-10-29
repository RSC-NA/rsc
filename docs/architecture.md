# Architecture

How the bot is put together: one Red cog, composed from feature mixins, talking to the RSC website API.

```
                 Discord gateway / interactions
                              │
                ┌─────────────▼──────────────┐
                │      Red-DiscordBot 3.5     │  owner, prefix, Config storage, slash sync
                │  ┌───────────────────────┐  │
                │  │   RSC cog (core.py)   │  │  ~35 mixins in one class
                │  │                       │  │
 website ──────►│  │  aiohttp :8008 ───────┼──┼── combines / devleague lobby webhooks
 (POST)         │  │  task loops ──────────┼──┼── nightly syncs, FA/sub expiry, event poller
                │  │  DMHelper queue ──────┼──┼── every DM the bot sends
                │  └──────────┬────────────┘  │
                └─────────────┼───────────────┘
                              │ rscapi (one ApiClient per guild)
          ┌───────────────────┼────────────────────┬───────────────────┐
          ▼                   ▼                    ▼                   ▼
   RSC website API     ballchasing.com          OpenAI           Combines / Dev League
   (per-guild URL+key)  (replays, groups)    (rules assistant)   lobby API (per guild)
```

## The cog

The whole bot is one Red cog, `RSC`, defined in [rsc/core.py](../rsc/core.py) and loaded by `setup()` in [rsc/\_\_init\_\_.py](../rsc/__init__.py).

`RSC` has no feature code of its own beyond settings and `/help`. It inherits from about 35 mixins, one or more per feature package (`AdminSyncMixIn`, `TransactionMixIn`, `CombineMixIn`, …), plus `commands.Cog`. Because discord.py's `CogMeta` and `ABCMeta` are different metaclasses, the class uses `CompositeMetaClass` from [rsc/abc.py](../rsc/abc.py), which combines them.

`CogMeta` walks the full MRO, so slash commands and listeners declared on any mixin are registered on the cog. Groups that other mixins need to nest under live on small holder mixins rather than on `RSC` itself, to avoid circular imports: `/rsc` is on `RSCSettingsMixIn` ([rsc/settings.py](../rsc/settings.py)), and `/admin` and `/sync` are on their admin mixins. A mixin adds a sub-group with `parent=RSCSettingsMixIn.rsc_settings`.

### `RSCMixIn`: the shared contract

[rsc/abc.py](../rsc/abc.py) defines `RSCMixIn`, the abstract base every mixin inherits. It declares:

- The shared state attributes (`bot`, `config`, `_league`, `_api_conf`, `_api_clients`, caches, `_dm_helper`, the two lobby runners).
- `api_client(guild)`, the one way to get an API client (below).
- An abstract method for every function one mixin calls on another, for example `franchises()`, `league_player()`, `current_season()`, `_get_combines_category()`. The concrete implementation lives in the owning mixin.

When mixin A needs something from mixin B, add an abstract declaration to `RSCMixIn` and call it on `self`. Don't import B from A.

## Lifecycle

```
RSC.__init__           register Config defaults, start DMHelper, build lobby runners
   │
cog_load() ───┐
on_ready() ───┴─► setup()   (serialised by _setup_lock; runs on load AND every on_ready/reconnect)
                    ├─ start_webapp()               bind localhost:8008 once
                    ├─ add_dynamic_items(...)       persistent buttons
                    ├─ prepare_application_emojis() upload the "live" emoji if missing
                    ├─ load_rulebooks()             parse rule Markdown for the LLM
                    └─ for every guild, concurrently: _setup_guild()
                         ├─ prepare_api()          build Configuration from Config url+key
                         ├─ prepare_league()       cache league id
                         └─ TaskGroup: FA cache, PermFA timers, ballchasing,
                                       tiers, franchises, teams, seasons, activity check
cog_unload()           cancel loops and timers, remove dynamic items, drop DM queue,
                       close ballchasing + API sessions, stop the web server
```

Things worth knowing:

- `setup()` is **idempotent** and runs more than once: on cog load, and again on every `on_ready`, which fires after gateway reconnects. Everything it does must tolerate a second run. `start_webapp()` returns early if the server is already up; `prepare_api()` keeps the existing client if the URL and key haven't changed.
- Guilds are prepared concurrently with `asyncio.gather(..., return_exceptions=True)`, so one broken guild (bad key, API down) doesn't leave the others without caches. Failures are logged with the guild name.
- A guild with no API URL/key skips every API-backed cache. A guild with an API but no league skips the league caches and logs a warning.
- `cog_unload()` **must** cancel every `tasks.loop`. `tasks.Loop` gives each cog instance its own copy, so a reloaded cog would otherwise start a second poller. If you add a loop, add its `.cancel()` there.
- The DM queue is discarded on unload, not drained, so a reload never blocks behind a large batch of DMs.

## Configuration storage

Settings are stored with Red's `Config` under identifier `6349109713`, almost all per guild (`register_guild`). Red keeps them in its data directory, so they survive restarts and code updates, and are included in Red's own backups.

Core keys (in `defaults_guild` in [rsc/core.py](../rsc/core.py)): `ApiKey`, `ApiUrl`, `League`, `ModmailBot`, `TimeZone`. Each mixin registers its own keys in its `__init__`. [Configuration](configuration.md) lists them all.

## Talking to the RSC API

The RSC website exposes a REST API, and [rsc-api-client](https://github.com/RSC-NA/rsc-api-client) (`rscapi`) is the client generated from its schema.

- Each guild has its own API URL and key, set with `/rsc url` and `/rsc key`. `prepare_api()` turns them into an `rscapi.Configuration` with an exponential retry policy (`API_RETRIES` attempts, retrying server errors and stale-socket errors; `POST` is never retried, so a transaction can't be applied twice).
- `api_client(guild)` hands out one **long-lived** `ApiClient` per guild and deliberately doesn't close it, so calls reuse the HTTP session instead of paying a TLS handshake each time. Clients are closed by `close_api_clients()` on unload, or replaced when the URL or key changes.
- The guild's league ID (`/rsc league`) is cached in `self._league[guild.id]` and passed to almost every list call.
- Errors: the generated client raises `ApiException`. Mixins catch it and raise `RscException` (or a subclass from `translate_api_error()` in [rsc/exceptions.py](../rsc/exceptions.py)), which commands turn into an error embed.
- Pagination helpers for list endpoints are in [rsc/pagination.py](../rsc/pagination.py).

The website also talks back: see [Web server](#web-server) and the [events poller](modules/events.md).

## Caches

To keep autocomplete and common lookups fast, the bot caches league data in memory per guild, filled during `_setup_guild()`:

| Cache | Filled by | Used for |
|---|---|---|
| `_league` | `prepare_league()` | League ID for every API call |
| tiers | `tiers()` | Tier autocomplete and colours |
| franchises (`_franchise_cache`) | `franchises()` | Franchise autocomplete |
| teams (`_team_cache`) | `teams()` | Team autocomplete |
| seasons | `prepare_season_cache()` | Season number ↔ ID mapping |
| free agents | `_populate_free_agent_cache()` | FA check-ins (from Config) |
| elevated roles (`_elevated_role_cache`) | on demand, with expiry | `elevated_role_required` checks |

The tier, franchise and team name caches are also updated as a side effect of any call that lists those objects: names are merged in (`merge_name_cache()`), and an unfiltered list replaces the cache outright. A restart or `[p]reload rsc` rebuilds everything.

## Permissions

Three layers, from coarse to strict:

1. **`default_permissions`** on a command or group controls who *sees* it in Discord. Server admins can override this per server in Discord's Integrations settings, so it is not security.
2. **`elevated_role_required(*positions)`** in [rsc/checks.py](../rsc/checks.py) allows members with Manage Server, or members the RSC API says hold one of the given staff positions in this league. API failures deny access.
3. **`bot_owner_required()`** restricts to Red's bot owners. Used for settings that could break the bot or leak data, such as API credentials and the event cursor.

Some features add their own role checks (for example, the ballchasing manager role, GM/AGM checks in transactions). The module pages list who can run each command.

## Background work

| Loop | Schedule (UTC) | Module |
|---|---|---|
| `sync_discord_roles` | daily 07:00, RSC 3v3 guild only (hard-coded ID) | [admin](modules/admin.md) |
| `retire_audit_loop` | daily 09:00 | [admin](modules/admin.md) |
| `expire_sub_contract_loop` | daily 17:00 | [transactions](modules/transactions.md) |
| `expire_free_agent_checkins_loop` | daily 17:00 | [freeagents](modules/freeagents.md) |
| `rsc_events_loop` | every 30 s | [events](modules/events.md) |

Other timers: PermFA polls arm one-shot close timers from Config at startup, and the DM queue checks scheduled DMs every 30 seconds.

## Web server

`start_webapp()` runs an aiohttp server bound to **`localhost:8008`**. It only listens on loopback, so whatever posts to it must run on the same host or come through a local reverse proxy.

| Route | Handler |
|---|---|
| `POST /combines_match` | Combines lobby runner: create lobby channels, announce, DM players |
| `POST /combines_event` | Combines lobby runner: game finished, tear down |
| `POST /devleague_match` | Dev League lobby runner: create |
| `POST /devleague_event` | Dev League lobby runner: tear down |
| `POST /league_player_update` | Placeholder, always `501`. League player changes arrive through the events poller instead |

If the port is taken, the bot logs `Unable to bind web app to localhost:8008` and carries on without the webhooks. See [lobbies](modules/lobbies.md), [combines](modules/combines.md) and [devleague](modules/devleague.md).

## Direct messages

[rsc/utils/dm.py](../rsc/utils/dm.py) holds `DMHelper`, the bot's single rate-limited DM queue (one DM per 1.5 seconds by default, retrying on rate limits). Every feature enqueues through `self._dm_helper`:

- `urgent=True` puts a DM ahead of everything waiting, for example a player's lobby details during a mass DM.
- `send_at` schedules a DM for later.
- `precheck` runs just before sending and can drop a DM that's no longer relevant.
- `on_result` reports the outcome per recipient.

Never create a second queue: two queues would double the send rate and trip Discord's limits.

## Persistent buttons

Buttons that must keep working after a restart (Intent to Play DMs, activity checks, PermFA polls, the `/playerinfo` card buttons, the combines replay location button) are discord.py `DynamicItem`s. Their guild, season or other state is encoded in the `custom_id` and matched by a regex, so one registration in `DYNAMIC_ITEMS` ([rsc/core.py](../rsc/core.py)) serves every message ever sent. Other views are ordinary timed views.

## Discord UI

- Shared embed classes (`BlueEmbed`, `SuccessEmbed`, `ErrorEmbed`, `ApiExceptionErrorEmbed`, …) are in [rsc/embeds.py](../rsc/embeds.py).
- Newer cards (transactions, lobby cards, player card, match results, sign-up) use **Components V2** `LayoutView`s. A V2 message can't carry `content` or `embeds`, and can never be edited back into an embed message. `ConfirmLayoutView` in [rsc/views.py](../rsc/views.py) is the V2 confirm/cancel prompt.
- Mentions only ping from message content or a V2 `TextDisplay`, never from inside an embed.
- The ongoing redesign and its rules are tracked in [plans/discord-ui-refresh.md](plans/discord-ui-refresh.md).

## Logging

Loggers are named `red.rsc.<module>` and wrapped in `GuildLogAdapter` ([rsc/logs.py](../rsc/logs.py)), which prefixes `[Guild Name]` and `[Match id]` when you pass `guild=` or `match=`. `/rsc loglevel` changes the level of `red.rsc` and `ballchasing` at runtime. Logs go wherever Red sends them; see [Operations](operations.md#logs).

## Code map

| Path | Contents |
|---|---|
| [rsc/core.py](../rsc/core.py) | The `RSC` cog: mixin list, lifecycle, web server, `/rsc` settings, `/help`, `/whatami` |
| [rsc/abc.py](../rsc/abc.py) | `RSCMixIn` contract, `CompositeMetaClass`, `api_client()` |
| [rsc/settings.py](../rsc/settings.py) | Holder for the `/rsc` group |
| [rsc/checks.py](../rsc/checks.py) | `bot_owner_required`, `elevated_role_required` |
| [rsc/const.py](../rsc/const.py) | Role names, timeouts, URLs, role permission sets, Discord copy |
| [rsc/enums.py](../rsc/enums.py) | Enums mirroring API values (status, staff positions, transaction types, …) |
| [rsc/embeds.py](../rsc/embeds.py), [rsc/views.py](../rsc/views.py) | Shared embeds and views |
| [rsc/exceptions.py](../rsc/exceptions.py) | `RscException` and API error translation |
| [rsc/logs.py](../rsc/logs.py) | `GuildLogAdapter` |
| [rsc/pagination.py](../rsc/pagination.py) | Paging over API list endpoints |
| [rsc/transformers.py](../rsc/transformers.py), [rsc/types.py](../rsc/types.py) | App command transformers and typed dicts |
| `rsc/<feature>/` | One package per feature. See [Modules](modules/README.md) |
| [rsc/resources/](../rsc/resources/) | Images, fonts, emoji, help text, and the rulebook Markdown |
| [tests/](../tests/) | pytest suite. See [Development](development.md#tests) |
| [scripts/](../scripts/) | One-off operational utilities. See [Scripts](scripts.md) |
| [data/](../data/) | Sample API and webhook payloads for tests and scripts |
