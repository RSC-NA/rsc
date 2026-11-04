# Teams

**Package:** [rsc/teams/](../../rsc/teams/) · **Mixin(s):** `TeamMixIn`

A team is one franchise's roster in one tier. This module answers the everyday "who is on this team" questions: rosters, which teams a franchise has, which teams are in a tier, and who the captains are. It also wraps the RSC API's team endpoints for other modules: team IDs, next match, season schedule, team stats, and team creation and deletion.

## Using it

These commands are read-only, and anyone in the server can use them.

- Players and GMs check a roster with `/roster <team>`. The team name autocompletes.
- `/teams franchise <franchise>` shows a franchise's teams by tier, with its GM and AGMs.
- `/teams tier <tier>` shows every team in a tier and the franchise it belongs to.
- `/captains team|tier|franchise` shows elected captains.

Captains are set by the transaction committee with `/transactions captain` ([transactions](./transactions.md)). Admins add and remove teams with `/admin franchise addteam` and `/admin franchise delteam` ([admin](./admin.md)), which call `create_team` and `delete_team` here.

## Commands

### `/teams`

| Command | Who can run it | What it does |
| --- | --- | --- |
| `/teams franchise <franchise>` | Anyone (server only) | Lists the franchise's teams with their tiers, highest tier first, plus the GM and any AGMs. Uses the franchise logo as the thumbnail when there is one. |
| `/teams tier <tier>` | Anyone (server only) | Lists every team in the tier, sorted by name, with its franchise. The embed takes the tier role's colour. |

### `/roster`

| Command | Who can run it | What it does |
| --- | --- | --- |
| `/roster <team>` | Anyone (server only) | Posts the team's roster card in the tier colour, headed by the tier, franchise, team, GM and franchise logo. Players sit under Active roster, Subbed out and Inactive reserve, each with their MMR and any of the tags GM, Captain, Sub and AGM. The GM and captain come first. Each player has a Profile button to their website page, and the card ends with Team page and Franchise page buttons. An unknown team gets a private "Team not found" reply. |

### `/captains`

| Command | Who can run it | What it does |
| --- | --- | --- |
| `/captains team <team>` | Anyone (server only) | Shows the team's captain and franchise. |
| `/captains tier <tier>` | Anyone (server only) | Lists every team in the tier with its captain, or "None" if no captain has been elected. |
| `/captains franchise <franchise>` | Anyone (server only) | Lists the franchise's teams by tier with their captains, plus the GM and franchise role. |

## Configuration

This module stores no settings.

## Background work

None of its own. On startup `_setup_guild` in [core.py](../../rsc/core.py) calls `teams(guild)` for each guild with an API and league configured, which fills the team-name autocomplete cache.

## How it works

The commands and API calls live in [teams.py](../../rsc/teams/teams.py). The roster card lives in [views.py](../../rsc/teams/views.py).

- `_team_cache` is a per-guild, sorted list of team names. `teams()` refreshes it through `merge_name_cache` on every call. An unfiltered call replaces it, while a filtered call can only add to it. The franchise delete flow in [admin](./admin.md) removes names from it directly, once the API supports deletion.
- `teams_autocomplete` works like the franchise autocomplete: the first 25 names when nothing is typed, otherwise up to 25 substring matches.
- `/roster` calls `players(team_name=...)` from [members](./members.md), then keeps only exact, case-insensitive team-name matches, because the API filter is looser than that.
- `build_roster_card` turns the players into a `RosterCard` from [views.py](../../rsc/teams/views.py), a Components V2 card that pings nobody. The `/playerinfo` Team button sends the same card privately. Website links come from the guild's API URL (see [utils/website.py](../../rsc/utils/website.py)). A player without an RSC ID gets a greyed-out Profile button. With no API URL or league configured there is nothing to link, so the card has no buttons at all.
- `tier_captains` keeps captains whose status is Rostered, Renewed, IR or AGM IR. `franchise_captains` keeps captains with any tier position, including 0. A comment notes that the top tier was once dropped because 0 is falsy.
- `build_franchise_teams_embed` fetches the franchise separately to get the AGM list, because `TeamList` only carries the GM. If that lookup fails, the embed is still sent, just without AGMs.
- `team_id_by_name` prefers an exact name match when the API returns several teams, and raises `ValueError` otherwise.
- `teams_in_same_tier` is used by `/admin match` to check that both teams are in one tier.

RSC API calls (`TeamsApi`):

| Method | Endpoint call | Used by |
| --- | --- | --- |
| `teams()` | `teams_list` (filters: season, franchise, name, tier; always the guild's league) | Many modules |
| `team_by_id()` | `teams_retrieve` | No callers outside this module |
| `team_players()` | `teams_players_list` | `/transactions captain`, LLM agent tools |
| `next_match()` | `teams_next_match_retrieve` (returns `None` on 404) | [matches](./matches.md), LLM agent tools |
| `season_matches()` | `teams_season_matches_list` (sorted by match day) | [matches](./matches.md) |
| `team_stats()` | `teams_stats_retrieve` | [stats](./stats.md), LLM agent tools |
| `create_team()` / `delete_team()` | `teams_create` / `teams_destroy` | `/admin franchise addteam` / `delteam` |

## Gotchas

- `/teams tier` passes the tier exactly as typed, while `/captains tier` capitalises it first. Use the autocomplete value to avoid surprises.
- `/captains team` raises an unhandled `ValueError` ("Malformed player data received from API") if the captain record is missing team, franchise, tier or Discord ID data. The user sees a generic failure.
- A roster card holds at most 40 Discord components. A roster too big for that shows the first players and ends with "And N more on the team page". About nine players fit with one group, fewer when all three groups show.
- When an embed would include data the API failed to return (a team with no name or tier), most of these commands stop and tell the user to open a modmail ticket.
