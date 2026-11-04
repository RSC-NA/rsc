# Matches

**Package:** [rsc/matches/](../../rsc/matches/) · **Mixin(s):** `MatchMixIn` · **Details:** [package README](../../rsc/matches/README.md)

Match information for players and franchise management. `/schedule` lists a team's season schedule, and `/match` shows a team's next match with the lobby name and password, both rosters, and instructions for the home and away sides.

The mixin also holds the RSC API helpers for matches that other modules use. [Ballchasing](./ballchasing.md) uses them to find and report a match, [admin](./admin.md) to create matches, [free agents](./freeagents.md) to check whether today is a match night, and the [LLM](./llm.md) agent to read the league schedule.

## Using it

**Players**

- `/match` shows your team's next match as a card, visible only to you. It shows the tier, match day or playoff round, series format, start time, the lobby name and password, and each team's roster beside its franchise logo, your team first. A check-in line says what your side does:
  - **Home** creates the lobby, then pings the other team's captain in `#match-check-in` when ready.
  - **Away** waits for the home captain's ping in `#match-check-in`, then joins once the whole team is ready.
  - The captain is the opposing roster's captain if they are in the server, otherwise that team's GM. The channel is linked only if a text channel named `match-check-in` exists.
  - A footer reminds everyone to turn on crossplay, save every replay, screenshot the scoreboard, and report with `/reportmatch`.
  - Buttons open the match page on the league website and, for playoff and finals matches, the tier's playoff bracket.
  - The card names players but pings no one.
- When your next playoff series has no match yet because your opponent is the winner of a series still to be played (a bye seed), `/match` shows a "vs TBD" card instead. It names both possible opponents, says the lobby is posted once that series is reported, and says whether you are home whichever team wins. **Refresh** runs `/match` again in place: once the series is reported it becomes the full match card. **Bracket** opens the playoff bracket.
- `/match day:<n>` shows a specific regular-season match day instead of the next match.
- `/schedule` posts your team's full regular-season and playoff schedule (date, home, away) in the channel. `/schedule preseason:True` shows only the preseason matches.
- `/schedule team:<team>` shows any team's schedule. Anyone can use it.

Your team comes from your RSC player record. `/schedule` needs your status to be Rostered, IR, AGM IR or Renewed. `/match` needs you to have a team.

Roster markers in `/match`: `(C)` captain, `(GM)`, `(IR)`, `(AGM IR)`, and for free agents `(Sub)`, `(Subbed In)` or `(Subbed Out)`. Players with any other status are left out. Names are server nicknames with the accolade emoji removed, or the RSC name for a player not in the server.

**GMs, AGMs and admins**

- `/match team:<team>` shows another team's match card. It is allowed when you are the GM or AGM of either franchise in that match, or have Manage Server. Everyone else is told to run plain `/match`. A pending "vs TBD" card has no lobby, so it is shown to anyone who names the team.
- An admin who is not in the match sees the card without a side: home team first and no check-in line.

## Commands

| Command | Who can run it | What it does |
|---|---|---|
| `/schedule [team] [preseason]` | Anyone (server only) | Post a team's schedule for the current season. The default team is your own. `preseason:True` lists only preseason matches. Otherwise it lists regular season, then postseason, then finals. |
| `/match [team] [day]` | Anyone for their own team. `team:` needs GM or AGM of a franchise in that match, or Manage Server. | Show the next match (or match day `day`) for a team, privately. |

## Configuration

None. No Config keys or environment variables. The check-in channel is found by its name, `match-check-in` (`MATCH_CHECK_IN_CHANNEL` in [const.py](../../rsc/const.py)). The Match page and Bracket links are built from the guild's API URL (see [website.py](../../rsc/utils/website.py)). Tier colours come from the tier's Discord role colour.

## Background work

- **Refresh button.** Refresh on the pending "vs TBD" card is `MatchRefreshButton`, a `DynamicItem` registered once in `rsc/core.py` with `bot.add_dynamic_items()`. Its `custom_id` is `match_refresh:<team_id>:<asked>`, where `asked` is 1 when `/match` named the team, so the permission check for `team:` still applies after a restart. A click edits the same private message: the match card once the match exists, the pending card again if it doesn't, or "You do not have any upcoming matches." An error (such as the `team:` permission check) comes as a separate private message.

## How it works

### Files

- [matches.py](../../rsc/matches/matches.py): `MatchMixIn`. It holds the two commands, the role checks, the code that gathers the `/match` cards, and the RSC API wrappers.
- [views.py](../../rsc/matches/views.py): the Components V2 cards, `MatchCard` and `PendingSeriesCard`, each a frozen dataclass with a pure `render()`, plus `player_line` (the roster markers) and `MatchRefreshButton`.

### `/match` flow

`/match` resolves the team (named, or the caller's own), then calls `match_reply()`. Refresh calls the same method. It returns a `MatchCard`, a `PendingSeriesCard`, an error embed, or nothing when there is no upcoming match:

1. Fetch the next match (`next_match`), or the match on `day:`.
2. No match and no `day:`: fetch the pending series (`pending_series`). If there is one, gather the pending card.
3. A named team needs the caller to be a GM or AGM of a franchise in the match, or Manage Server.
4. `match_team_by_user()` decides the caller's side, and `match_card()` gathers the card. The two franchise logos are fetched at the same time.

The card's `/reportmatch` mention comes from the synced command list, fetched once per server and cached on the cog. If `/reportmatch` isn't synced, the card shows it as plain code.

### Helpers used by other modules

| Method | What it does | Used by |
|---|---|---|
| `find_match(teams, date_lt, date_gt, day, ...)` | `MatchesApi.matches_find_match_retrieve`, teams joined with commas | `/reportmatch` ([ballchasing](./ballchasing.md)) |
| `get_match_from_list(home, away, matches)` | Picks the match whose two teams match, in either order and ignoring case. With several matches it returns the last one. | `/reportmatch` |
| `report_match(match_id, ballchasing_group, home_score, away_score, executor, override)` | `MatchesApi.matches_score_report_create` | `/reportmatch` |
| `discord_member_in_match`, `is_match_franchise_gm`, `is_match_franchise_agm`, `match_franchise_agm_team` | Is the member a player, the GM or an AGM for a side of the match | `/match`, `/reportmatch` |
| `create_match(match_type, match_format, home_team_id, away_team_id, day)` | `MatchesApi.matches_create` | [admin](./admin.md) match commands |
| `is_match_day(guild)` | Is today (in the guild timezone) one of the current season's match nights | [free agents](./freeagents.md) |
| `matches(...)` | `MatchesApi.matches_list`, one page | [LLM](./llm.md) `get_schedule` tool |
| `paged_matches(season_number, ...)` | Async generator over `matches_list` that walks every page. A season number is required because of API load. | |
| `match_by_day(team_id, day, preseason)` | `TeamsApi.teams_match_retrieve` | `/match day:` |
| `match_by_id`, `match_results` | `MatchesApi.matches_retrieve`, `matches_results_retrieve` | |
| `match_reply`, `match_card`, `pending_series_card`, `match_team_by_user` | Gather the `/match` card or pending card | `/match`, Refresh |
| `bracket_link(tier, season_number)` | The tier's playoff bracket on the league website, or None | `/match` |

`/schedule` and `/match` also use `next_match` (`TeamsApi.teams_next_match_retrieve`), `pending_series` (`TeamsApi.teams_pending_series_retrieve`) and `season_matches` (`TeamsApi.teams_season_matches_list`, sorted by day) from the teams mixin. They use `players(discord_id=...)` to find the caller's team and `agm_franchise_of` for the AGM check. `/match` looks the AGM franchise up once and reuses it for both the permission check and the home/away decision. GM names and mentions come from the match itself. Logos come from `franchises` and `franchise_logo`, falling back to the server icon and then the bundled RSC logo. The Match page link is `match_page_link` from [ballchasing](./ballchasing.md).

API errors are wrapped as `RscException`. `match_by_id` is the exception: it does not wrap.

### `/match` home/away decision

`match_team_by_user()` checks, in order: GM of the home or away team, a player on either roster, AGM of either franchise (from the API, not Discord roles), and finally Manage Server. Manage Server gets no side. Anyone else gets an error.

## Gotchas

- The README says `/match` fetches "your match for the night". It actually returns the team's *next* match from the API, whatever its date, or the match day given with `day:`.
- `/schedule preseason:True` shows *only* preseason matches, although the option is described as "Include preseason matches".
- `/match day:` cannot look up preseason matches (`preseason=False` is hard-coded).
- The permission check for `/match team:` runs after the match lookup, against the GMs and AGMs of the franchises in the match that was found.
- `is_match_day()` reads match nights from the first tier in the season's tier data only.
- `/schedule` replies publicly, including its errors ("You are not currently rostered on a team."). `/match` is private.
