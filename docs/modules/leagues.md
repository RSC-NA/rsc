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
- [effective.py](../../rsc/leagues/effective.py): `pick_effective_row`, the rule that picks one league player row for a member while two seasons overlap. It makes no API call.

| Helper | API call | Notes |
|---|---|---|
| `leagues(guild)` | `LeaguesApi.leagues_list` | |
| `league(guild)`, `league_by_id(guild, id)` | `leagues_retrieve` | |
| `current_season(guild)` | `leagues_current_season_retrieve` | |
| `league_seasons(guild)` | `leagues_seasons_list` | |
| `players(guild, ...)` | `LeaguePlayersApi.league_players_list` | One page. `limit=0` means the API default of 100 rows, and the API caps a page at 500. |
| `paged_players(guild, ...)` | `league_players_list` | Every page, as an async iterator. Use this when you need the full set. |
| `effective_players(guild)` | `league_players_list` for each season read, `seasons_player_intents_list` | One row per member, as an async iterator. The syncs in [admin](./admin.md) use it. |
| `effective_player(guild, discord_id)` | The same calls, filtered to one member | The row `effective_players` yields for that member, or `None` for a non-playing member. |
| `player_count(...)`, `total_players(...)` | `league_players_list` with `limit=1` | Both return the result `count`; they are duplicates. |
| `update_league_player(guild, player_id, executor, ...)` | `league_players_partial_update` | Patch MMR, tier, status, team, contract length (0 to 2) or waiver period. |

All filters are scoped to the guild's league. `update_league_player` sets a waiver period with no timezone to noon in the guild's timezone.

`effective_players` and `effective_player` read the default season. While `next_signup_season` returns a season, they also read that season and the season numbered one below it, and the "not returning" declarations for the sign-up season. A 404 from the sign-up season lookup means no season is taking sign-ups only when its error code is `no_signup_season`. Any other 404, such as the one for an unknown league id, stops the read with an API error. `pick_effective_row` then picks one row for each member. A rostered row holds until its season's end date. Otherwise the row in the newest season applies. Otherwise the older row holds until its season's end date, whatever the member declared for the next season. After that end date it holds only while sign-ups are open, and not after the member declared "not returning".

`/drafteligible` capitalises the tier name, asks for players with status Draft Eligible, and shows member mentions in an embed colored by the tier. If the list would pass Discord's 1024-character field limit, it sends display names in code-block pages instead.

## Gotchas

- `/drafteligible`'s `season` option is sent to the API as the `season` filter, which is a season ID, not the season number players know. With no value, no season filter is sent.
- `/leagueinfo` sends its "not implemented" reply and then still calls the API. If the league has no current season it tries to reply a second time and errors.
- `players()` silently truncates large result sets. Raising `limit` does not help; use `paged_players()`.
- `players()` and `paged_players()` with no season return the API's default season only. Around a season change that leaves out every member whose only row is in the season that just ended. A sync must use `effective_players()`.
- A league player's `season` field is the season number, while the `season` filter takes a season ID.
- An intent row with `missing` true is an unanswered prompt. The API stores it with `returning` false, so a declared "not returning" is a row with `missing` false and `returning` false.
- `update_league_player` skips any value that is falsy, so it cannot set MMR or tier to `0`, or clear the team.
