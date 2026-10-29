# Numbers

**Package:** [rsc/numbers/](../../rsc/numbers/) · **Mixin(s):** `NumberMixIn`

Tools for the Numbers Committee, the staff who place players by MMR. The commands read the MMR pulls RSC has taken from a player's trackers and show the player's peak MMR and games played per Psyonix (Rocket League) season, in 3v3, 2v2 and 1v1.

## Using it

1. An admin sets the committee role once with `/numbers role`.
2. Committee members look up a player:
   - `/numbers peaks player [psyonix_season]` for the highest season peak seen in any pull, per playlist. Leave the season out to cover all seasons.
   - `/numbers gamesplayed player psyonix_season` for the games-played counts from each distinct pull in that season, most 3v3 games first.

Results are private to the person who ran the command.

Tracker management (adding, linking, merging trackers) is in [trackers](./trackers.md).

## Commands

**`/numbers`** (visible to everyone; access is checked per command)

| Command | Who can run it | What it does |
|---|---|---|
| `/numbers settings` | Manage Server | Show the configured Numbers Committee role. |
| `/numbers role role` | Manage Server | Set the Numbers Committee role. |
| `/numbers peaks player [psyonix_season]` | Manage Server, or the Numbers Committee role | Highest 3v3, 2v2 and 1v1 season peak across the player's pulls. |
| `/numbers gamesplayed player psyonix_season` | Manage Server, or the Numbers Committee role | Games played per playlist for each distinct pull in the season. |

## Configuration

Stored in the custom Config group `Numbers`, keyed by guild ID.

| Key | Default | Set by |
|---|---|---|
| `NumbersRole` | `None` | `/numbers role` |

## Background work

None.

## How it works

- [numbers.py](../../rsc/numbers/numbers.py): `NumberMixIn`, the commands, `has_numbers_perms()`, the MMR helpers and Config.

`mmr_pulls()` calls `NumbersApi.numbers_mmr_list` and pages through every result. It accepts filters for pull date, Discord member, RSC ID range and Psyonix season, though the commands only use member and season. `calculate_mmr_peaks()` takes the maximum `*_season_peak` per playlist. `filter_no_games_played_mmr_pulls()` drops pulls with no games in any playlist and pulls whose three games-played counts match one already kept.

`has_numbers_perms()` passes members with Manage Server or the configured role. It is a separate check from the API staff positions used by [trackers](./trackers.md), so the Numbers role here does not need to match the API's Numbers position.

## Gotchas

- A member without permission who runs `peaks` or `gamesplayed` gets no reply at all; Discord shows "The application did not respond".
- If the API call fails, the command posts the error and then errors out itself, so a second failure appears in the bot log.
- `gamesplayed` with no pulls for the season sends empty columns, which Discord may reject.
- The module logs under `red.rsc.transactions`, not `red.rsc.numbers`.
