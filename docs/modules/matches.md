# Matches

**Package:** [rsc/matches/](../../rsc/matches/) · **Mixin(s):** `MatchMixIn` · **Details:** [package README](../../rsc/matches/README.md)

Match information for players and franchise management. `/schedule` lists a team's season schedule, and `/match` shows a team's next match with the lobby name and password, both rosters, and instructions for the home and away sides.

The mixin also holds the RSC API helpers for matches that other modules use. [Ballchasing](./ballchasing.md) uses them to find and report a match, [admin](./admin.md) to create matches, [free agents](./freeagents.md) to check whether today is a match night, and the [LLM](./llm.md) agent to read the league schedule.

## Using it

**Players**

- `/match` shows your team's next match, visible only to you. It shows the match day and date, the lobby name and password, both rosters, and whether you are the home or away team:
  - **Home** creates the lobby and contacts the other team when ready. The home team should not join a team in the lobby before the away team does.
  - **Away** joins once the home team gets in touch.
  - Everyone is reminded to enable crossplay, save the replays and screenshots of the end-of-game scoreboard, and upload them to the RSC website.
- `/match day:<n>` shows a specific regular-season match day instead of the next match.
- `/schedule` posts your team's full regular-season and playoff schedule (date, home, away) in the channel. `/schedule preseason:True` shows only the preseason matches.
- `/schedule team:<team>` shows any team's schedule. Anyone can use it.

Your team comes from your RSC player record. `/schedule` needs your status to be Rostered, IR, AGM IR or Renewed. `/match` needs you to have a team.

Roster markers in `/match`: `(C)` captain, `(GM)`, `(IR)`, `(AGM IR)`, and for free agents `(Sub)`, `(Subbed In)` or `(Subbed Out)`. Players with any other status are left out.

**GMs, AGMs and admins**

- `/match team:<team>` shows another team's match card. It is allowed when you are the GM or AGM of either franchise in that match, or have Manage Server. Everyone else is told to run plain `/match`.

## Commands

| Command | Who can run it | What it does |
|---|---|---|
| `/schedule [team] [preseason]` | Anyone (server only) | Post a team's schedule for the current season. The default team is your own. `preseason:True` lists only preseason matches. Otherwise it lists regular season, then postseason, then finals. |
| `/match [team] [day]` | Anyone for their own team. `team:` needs GM or AGM of a franchise in that match, or Manage Server. | Show the next match (or match day `day`) for a team, privately. |

## Configuration

None. No Config keys or environment variables. The match card's upload link is hard-coded to `https://www.rocketsoccarconfederation.com/replay-and-screenshot-uploads`. Tier colours come from the tier's Discord role colour.

## Background work

None. There are no loops, listeners, views or DMs.

## How it works

### Files

- [matches.py](../../rsc/matches/matches.py): `MatchMixIn`. It holds the two commands, the match card builders, the role checks, and the RSC API wrappers.

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
| `match_team_by_user`, `build_match_embed`, `roster_fmt_from_match` | Build the `/match` card | `/match` |

`/schedule` and `/match` also use `next_match` (`TeamsApi.teams_next_match_retrieve`) and `season_matches` (`TeamsApi.teams_season_matches_list`, sorted by day) from the teams mixin. They use `players(discord_id=...)` to find the caller's team, `franchise_gm_by_name` for GM names, and `agm_franchise_of` for the AGM check. `/match` looks the AGM franchise up once and reuses it for both the permission check and the home/away decision.

API errors are wrapped as `RscException`. `match_by_id` is the exception: it does not wrap.

### `/match` home/away decision

`match_team_by_user()` checks, in order: GM of the home or away team, a player on either roster, AGM of either franchise (from the API, not Discord roles), and finally Manage Server. Manage Server returns **home**. Anyone else gets an error.

## Gotchas

- The README says `/match` fetches "your match for the night". It actually returns the team's *next* match from the API, whatever its date, or the match day given with `day:`.
- `/schedule preseason:True` shows *only* preseason matches, although the option is described as "Include preseason matches".
- `/match day:` cannot look up preseason matches (`preseason=False` is hard-coded).
- An admin who is not in the match is shown the **home** team instructions, because of the Manage Server fallback.
- The permission check for `/match team:` runs after the match lookup, against the GMs and AGMs of the franchises in the match that was found.
- `is_match_day()` reads match nights from the first tier in the season's tier data only.
- `/schedule` replies publicly, including its errors ("You are not currently rostered on a team."). `/match` is private.
