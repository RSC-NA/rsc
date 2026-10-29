# Leagues

**Package:** [rsc/leagues/](../../rsc/leagues/) · **Mixin(s):** `LeagueMixIn` · **Details:** [package README](../../rsc/leagues/README.md)

General league information commands: the list of RSC leagues, the current season, the important dates admins post, and the draft eligible players in a tier. The module is also the bot's main wrapper for the RSC API's league player endpoints. Nearly every module that needs to know a player's status, tier or team goes through `players()` or `paged_players()` here.

## Using it

- **Anyone:** `/season` shows the current season number. `/dates` shows the important league dates. `/leagues` lists the RSC leagues and their game modes. `/drafteligible tier` lists who is draft eligible in a tier, privately.
- **Admins:** the text shown by `/dates` is set with `/admin dates` in the [admin](./admin.md) module.

## Commands

| Command | Who can run it | What it does |
|---|---|---|
| `/leagues` | Anyone | Public list of RSC leagues and their game modes. |
| `/leagueinfo` | Anyone | Not implemented. Replies with a "not implemented" message. |
| `/drafteligible tier [season] [limit]` | Anyone | Private list of draft eligible players in `tier`. `limit` is 1 to 100 (default 50). |
| `/season` | Anyone | Public "The current season is S<number>". |
| `/dates` | Anyone | Public embed with the dates text set by `/admin dates`, or "No league dates have been posted." |

## Configuration

No Config keys of its own. `/dates` reads the `Dates` key in the admin module's `Admin` Config group. The API calls use the guild's league ID (see [../configuration.md](../configuration.md)).

## Background work

- **Web route `POST /league_player_update`.** Registered on the bot's local web app (`localhost:8008`, set up in `rsc/core.py`). The handler is a placeholder that always returns `501 Not Implemented`. League player changes reach the bot through the [events](./events.md) poller instead.

## How it works

- [leagues.py](../../rsc/leagues/leagues.py): `LeagueMixIn`, the commands, the web handler, and the API wrappers.

| Helper | API call | Notes |
|---|---|---|
| `leagues(guild)` | `LeaguesApi.leagues_list` | |
| `league(guild)`, `league_by_id(guild, id)` | `leagues_retrieve` | |
| `current_season(guild)` | `leagues_current_season_retrieve` | |
| `league_seasons(guild)` | `leagues_seasons_list` | |
| `players(guild, ...)` | `LeaguePlayersApi.league_players_list` | One page. `limit=0` means the API default of 100 rows, and the API caps a page at 500. |
| `paged_players(guild, ...)` | `league_players_list` | Every page, as an async iterator. Use this when you need the full set. |
| `player_count(...)`, `total_players(...)` | `league_players_list` with `limit=1` | Both return the result `count`; they are duplicates. |
| `update_league_player(guild, player_id, executor, ...)` | `league_players_partial_update` | Patch MMR, tier, status, team, contract length (0 to 2) or waiver period. |

All filters are scoped to the guild's league. `update_league_player` sets a waiver period with no timezone to noon in the guild's timezone.

`/drafteligible` capitalises the tier name, asks for players with status Draft Eligible, and shows member mentions in an embed colored by the tier. If the list would pass Discord's 1024-character field limit, it sends display names in code-block pages instead.

## Gotchas

- `/drafteligible`'s `season` option is sent to the API as the `season` filter, which is a season ID, not the season number players know. With no value, no season filter is sent.
- `/leagueinfo` sends its "not implemented" reply and then still calls the API. If the league has no current season it tries to reply a second time and errors.
- `players()` silently truncates large result sets. Raising `limit` does not help; use `paged_players()`.
- `update_league_player` skips any value that is falsy, so it cannot set MMR or tier to `0`, or clear the team.
