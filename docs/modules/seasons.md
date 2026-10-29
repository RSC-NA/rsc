# Seasons

**Package:** [rsc/seasons/](../../rsc/seasons/) · **Mixin(s):** `SeasonsMixIn`

This module has no commands. It is the bot's wrapper around the RSC API's seasons endpoints: which season is accepting signups, the list of seasons, intent to play records, franchise standings, and activity checks. It also keeps a small cache that maps season numbers to season IDs. Staff see its effects through other modules: `/signup` and the intent commands in [members](./members.md), the intent and inactivity tools in [admin](./admin.md), and standings in [stats](./stats.md).

## Using it

Nothing to run directly. The season that `/signup` targets is whatever the API's "signup season" endpoint returns, so opening and closing signups is done on the RSC website, not in Discord.

## Configuration

No Config keys. It uses the guild's league ID (see [../configuration.md](../configuration.md)) to filter seasons.

## Background work

- **Season ID cache.** At startup, for each guild with a league configured, `rsc/core.py` calls `prepare_season_cache()`, which builds a `season number -> season ID` map for the guild's league. A lookup that misses refetches once, which covers a season created while the bot is running. If the fetch fails it logs a warning and the next lookup tries again.

## How it works

- [seasons.py](../../rsc/seasons/seasons.py): `SeasonsMixIn`.

| Helper | API call | Notes |
|---|---|---|
| `seasons(guild, number, current)` | `SeasonsApi.seasons_list` | Filtered by the guild's league. |
| `season_by_id(guild, season_id)` | `seasons_retrieve` | |
| `next_signup_season(guild)` | `seasons_signup_season_retrieve` | Raises `RscException` with `type == "SignupsClosedException"` when signups are closed; callers check for that. |
| `next_season(guild)` | `seasons_list` | The highest-numbered season in the guild's league. Raises `LeagueNotConfigured` if there is no league ID. |
| `player_intents(guild, season_id, player, returning, missing)` | `seasons_player_intents_list` | |
| `franchise_standings(guild, season_id)` | `seasons_franchise_standings_list` | |
| `season_activity_checks(...)` | `seasons_activity_check_list` | One page only (default 50). |
| `paged_activity_checks(...)` | `seasons_activity_check_list` | Every page, as an async iterator. |
| `season_id_for_number(guild, number)` / `season_number_for_id(guild, season_id)` | via `seasons()` | Cached lookups, used by [ballchasing](./ballchasing.md) and [stats](./stats.md). |

Most API payloads, such as a match, carry only a season number, while API filters and website links need the season ID. The cache exists to convert between the two.

## Gotchas

- `season_activity_checks()` returns a single page. Code that needs every check must use `paged_activity_checks()`.
- The API's "current" season can roll over during the signup period, so sign-up code uses `next_signup_season()`, not the current season.
