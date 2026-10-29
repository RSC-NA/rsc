# Stats

**Package:** [rsc/stats/](../../rsc/stats/) · **Mixin(s):** `StatsMixIn`

Read-only commands that show league numbers from the RSC API: franchise and tier standings, the playoff race for a tier, and season stats for a player or a team. `/playoffs` draws a standings image for each playoff group, showing who has clinched, who is on the bubble and who is eliminated. It can also show the same thing as text.

Nothing here writes to the API or stores settings.

## Using it

Anyone can run these commands, and the answers are posted publicly in the channel.

- **Standings**: `/standings franchise` for overall franchise records, or `/standings tier tier:<tier>` for one tier. Both default to the current season, and `season:` picks an older one.
- **Playoff race**: `/playoffs` shows the race for your own tier, worked out from your player record. Pass `tier:` for another tier, `season:` for another season, and `text:True` for the text board instead of the image. The message ends with a "Full standings" button that links to the league website's playoff standings for that tier. Until the regular season is under way it says "No playoff hunt yet".
- **Player stats**: `/playerstats` shows your own stats. Pass `player:@member` for someone else, `season:` for an older season, and `postseason:True` for playoff stats.
- **Team stats**: `/teamstats team:<team>`. Team and tier names autocomplete.

How to read the playoff race:

- **Clinched**: the API's magic number is 0, or the regular season is over and the team qualified.
- **In** (Holding / "N to clinch"): in a playoff spot now, but not safe yet.
- **Bubble**: an outside team within 2 wins of the team it is chasing, or tied on a tiebreaker or a random draw. The qualifier being chased is marked as bubble too.
- **Out** ("N back"): outside and more than 2 wins back, but still alive.
- **Eliminated**: cannot reach the last playoff spot even by winning every remaining game. In division tiers, the team also cannot catch its division leader. Once the regular season is over, every team that did not qualify is eliminated.

The bubble margin is `BUBBLE_WINS = 2` in [playoffs.py](../../rsc/stats/playoffs.py). Eliminated teams at the bottom of a group are folded into one line.

## Commands

**`/standings`** (server only)

| Command | Who can run it | What it does |
|---|---|---|
| `/standings franchise [season]` | Anyone | Franchise rank, name and win-loss record for the season. |
| `/standings tier tier [season]` | Anyone | Team rank, name and win-loss record within a tier. |

**Other commands**

| Command | Who can run it | What it does |
|---|---|---|
| `/playoffs [tier] [season] [text]` | Anyone (server only) | The playoff race for a tier: one image per playoff group (one per conference, or one for the whole tier), or the text race board. |
| `/playerstats [player] [season] [postseason]` | Anyone (server only) | Season stats for a member (default: you): games, wins, losses, goals, saves, assists, GPG, shots, shot %, MVPs, points, PPG, average speed, and team goals for and against with goal differential. |
| `/teamstats team [postseason] [season]` | Anyone (server only) | Season stats for a team: games, wins, losses, goals, saves, assists, GPG, shots, shot %, points, PPG, demos and goal differential. |

## Configuration

None. The module has no Config keys or environment variables of its own. It relies on the guild's RSC API and league configuration (see [../configuration.md](../configuration.md)). Tier colours come from the tier's Discord role colour (`tier_color_by_name`). The image fonts are bundled in `rsc/resources/fonts/` (Apotek Black, Bold and Semibold).

## Background work

None. There are no loops, listeners, persistent views or DMs. `/playoffs` messages are Components V2 `LayoutView`s with only a link button, so nothing needs to listen for clicks.

## How it works

### Files

- [stats.py](../../rsc/stats/stats.py): `StatsMixIn`. The commands, `create_stats_embed()` (shared by player and team stats) and `standings_link()`.
- [playoffs.py](../../rsc/stats/playoffs.py): turns the API's `TierPlayoffHunt` into `Race` objects. It works out each team's `RaceStatus` (`clinched`, `in`, `bubble`, `out`, `eliminated`) and holds the shared wording (`spots`, `games_left`, `chase`, `to_clinch`, `route`).
- [graphic.py](../../rsc/stats/graphic.py): draws the standings image with Pillow. One PNG per race, laid out at 640 units and drawn at 2x (1280 px wide) so it stays readable on phones.
- [views.py](../../rsc/stats/views.py): `PlayoffRaceCard`, which builds the V2 message, either the image cards or the text board, plus image alt text within Discord's 256-character limit.

### RSC API calls

The commands go through helpers in other mixins:

| Helper | Mixin | Endpoint (rscapi) |
|---|---|---|
| `franchise_standings(season_id)` | seasons | `SeasonsApi.seasons_franchise_standings_list` |
| `tier_standings(tier_id, season)` | tiers | `TiersApi.tiers_standings_list` |
| `tier_playoff_hunt(tier_id, season)` | tiers | `TiersApi.tiers_playoffs_retrieve` |
| `player_stats(member, season, postseason)` | members | `MembersApi.members_stats_retrieve` |
| `team_stats(team_id, season)` | teams | `TeamsApi.teams_stats_retrieve` |
| `current_season`, `seasons`, `tiers`, `teams`, `players`, `tier_id_by_name`, `season_id_for_number` | various | lookups |

The "Full standings" link is built by `standings_page_url()` in `rsc/utils/website.py`: the website base (the guild's API URL with `/api/...` removed) plus `/standings/?league=..&season=..&tier=..&mode=playoffs`.

### `/playoffs` details

- The API ranks each group, sets the cut line (`cutline_rank`) and provides `playoff_qualified`, `playoff_qualifier_reason`, `playoff_delta_label` and `playoff_magic_number`. It has no "eliminated" flag, so `is_eliminated()` works that out: a team is out when its `max_possible_games_won` is below the fewest wins among the teams above the cut line, and, in a division tier, also below its division leader's wins.
- A whole-tier hunt (`playoff_format == TIER`) is drawn as one card. Otherwise there is one card per group.
- **Image cache**: `GRAPHIC_CACHE` is an in-memory LRU of 32 entries, keyed by (guild, tier id, season). A cached entry is reused only while a SHA-256 of the hunt JSON plus the tier colour is unchanged. Rendering runs in a worker thread behind a lock, because FreeType font objects are shared between renders.
- A tier role with no colour set would draw invisible black accents, so the image uses Discord blue instead.

## Gotchas

- The `postseason` option on `/teamstats` changes nothing: `team_stats()` is called without it, and the team embed always says "Displaying team stats for current season", even when `season:` is given.
- `/playoffs` without `tier:` uses your player record's tier. Staff and anyone without a player record have to pass `tier:`.
- `/playerstats` takes a Discord member, so it cannot look up players who have left the server.
- The playoff image cache lives in process memory and is cleared on reload. An API change to the hunt or a tier colour change also invalidates an entry.
