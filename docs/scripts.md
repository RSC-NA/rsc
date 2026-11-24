# Scripts

[scripts/](../scripts/) holds one-off utilities for operators and developers. None of them are imported by the bot. Most talk to the RSC API or ballchasing.com directly.

## Running them

```sh
uv sync --group scripts                         # once: OpenCV, matplotlib, requests, ...
uv run --group scripts scripts/<name>.py --help
```

Most scripts load `.env` (see [Development](development.md#env)) and read:

- `RSC_API_KEY` for the RSC API. The host is hard-coded in each script's `API_HOST`: most point at **production** (`https://api.rscna.com/api/v1`), a few at staging. Check it before running anything.
- `BALLCHASING_KEY` for ballchasing.com.
- `RSC_DRAFT_LOG_LEVEL` for the draft scripts' log level.

Scripts that change data (uploads, tests that run a draft) say so in their description. Read one before pointing it at production.

## Webhook testing

| Script | What it does |
|---|---|
| [combines_lobby.py](../scripts/combines_lobby.py) | Posts sample Combines lobbies (`start <guild_id>`, `-2` for the 2v2 sample, `--games N` for N lobbies in one webhook, `--presses N` to send it N times growing each time, as the website does when staff press the button again). Only the lobby maker gets a Discord ID (`--discord-id`, default the developer's), so testing never pings real players or a game-finished event (`teardown <guild_id> <lobby_id>`, or `teardown <guild_id> --all` for every lobby the bot still has open, read from `GET /combines_open`) to the bot on `localhost:8008`. Samples are in [data/combines/](../data/combines/) |
| [devleague_lobby.py](../scripts/devleague_lobby.py) | Same for Dev League, with samples in [data/devleague/](../data/devleague/) |
| [brute_test_combines_check_in.py](../scripts/brute_test_combines_check_in.py) | Load-tests Combines check-in with a file of Discord IDs. It calls the live `devleague.rscna.com` check-in endpoint, not the bot |

## ballchasing.com

| Script | What it does |
|---|---|
| [ballchasing_backup.py](../scripts/ballchasing_backup.py) | Bulk-downloads every replay in a group |
| [bulk_ballchasing_upload.py](../scripts/bulk_ballchasing_upload.py) | Bulk-uploads replays to a group |
| [bulk_combine_upload.py](../scripts/bulk_combine_upload.py) | Bulk-uploads Combine replays into a match-day group under a top-level group |
| [organize_bc_group_by_date.py](../scripts/organize_bc_group_by_date.py) | Reorganises a group's replays by date |
| [find_ballchasing_failed_replay.py](../scripts/find_ballchasing_failed_replay.py) | Finds replays in a group that failed to process |
| [find_duplicate_bc_groups.py](../scripts/find_duplicate_bc_groups.py) | Finds sibling groups that share a name under a top-level group |
| [bc_check_duplicates.py](../scripts/bc_check_duplicates.py) | Finds duplicate recordings of the same game in a group |
| [bc_replay_fields.py](../scripts/bc_replay_fields.py) | Compares the shallow and deep group listings' fields |
| [bc_verify_fingerprints.py](../scripts/bc_verify_fingerprints.py) | Checks that local replay parsing and ballchasing agree on each game's fingerprint |
| [get_replay.py](../scripts/get_replay.py) | Fetches one replay by ID |
| [dump_replay_header.py](../scripts/dump_replay_header.py) | Prints the header properties the bot relies on from `.replay` files |

## League data checks

| Script | What it does |
|---|---|
| [check_contracts.py](../scripts/check_contracts.py) | Checks a season's contracts for inconsistencies |
| [check_inactive_league_players.py](../scripts/check_inactive_league_players.py) | Lists inactive league players for a season |
| [check_prior_season_status.py](../scripts/check_prior_season_status.py) | Checks whether members had an active status (RO/RN/FA) the season before |
| [validate_league_players.py](../scripts/validate_league_players.py) | Flags league players with no MMR value |
| [validate_trackers.py](../scripts/validate_trackers.py) | Validates tracker links (uses [scripts/data/trackers.json](../scripts/data/trackers.json)) |
| [find_duplicate_trackers.py](../scripts/find_duplicate_trackers.py) | Finds tracker links registered more than once |
| [duplicate_rsc_members.py](../scripts/duplicate_rsc_members.py) | Finds members with no RSC ID and RSC IDs used more than once |
| [test_valid_franchise_draft_picks.py](../scripts/test_valid_franchise_draft_picks.py) | Validates each franchise's draft picks for a season |
| [sync_season_probe.py](../scripts/sync_season_probe.py) | Read-only check of who a sync treats as a league player around a season change. It runs the checkout's own league player read against the production API with GET requests only, then checks the result against rows it fetched itself. `--lane NAME` runs one check, and `--time` times the read and counts its requests. The `agms` lane lists the AGMs whose row is not rostered, with the franchise prefix a sync writes for each. Run it with `uv run python scripts/sync_season_probe.py`; it needs `RSC_API_KEY` |
| [sync_lab.py](../scripts/sync_lab.py) | Runs one role sync on the **test server** and prints the Discord requests it sent. **It changes the lab member's roles and nickname.** It logs in as the test bot over HTTP only, with no gateway connection, builds the league player row itself, and never calls the RSC API. Scenarios are `reset`, `fresh-to-de`, `de-to-rostered`, `rostered-to-fa`, `no-change` and `nick-forbidden` (the lab member must be the server owner). Each prints the starting and final roles and nickname, the request list, the wall time and the run's `Sync summary.` line, and exits 1 when the final state or the request count is not the expected one. `--repeat N` reports the median and spread of the wall time. It reads `RSC_LAB_BOT_TOKEN`, `RSC_LAB_GUILD_ID` and `RSC_LAB_MEMBER_ID` from the shell, not from `.env`. It refuses to run on the production server or while a `redbot` process is running |
| [role_matrix.py](../scripts/role_matrix.py) | Runs every role function against fake members and prints each member's final roles and nickname and the number of Discord requests the call sent. It makes no network request. The columns are every league status, a member with no league player row, a non-playing GM, a sign, a cut, a cut of the franchise's GM, and a captain gained or lost. The members are one who holds every role, one who holds none, the server owner, one with a role above the bot's, and one whose nickname the bot may not change. `--agm` runs every case for an AGM. `--json FILE` writes the result, and `--compare BEFORE AFTER` prints final state differences and request counts for two such files and exits 1 on any final state difference. The code it runs is the first `rsc` package on the path, so `PYTHONPATH=<tree>` measures another checkout |

## Combines analysis

| Script | What it does |
|---|---|
| [combines_participation.py](../scripts/combines_participation.py) | Reports Combines participation for a season (takes the season **ID**, not number) |
| [combines_season_performance.py](../scripts/combines_season_performance.py) | Analyses performance from a Combines CSV export |
| [calculate_round_mmr.py](../scripts/calculate_round_mmr.py) | Works out players' current MMR from transaction history, optionally for one tier |
| [show_league_player_stats.py](../scripts/show_league_player_stats.py) | Counts league players per status and draft rounds per tier, optionally for one tier |

## API and draft testing

| Script | What it does |
|---|---|
| [test_draft.py](../scripts/test_draft.py) | Runs draft picks for a season against staging |
| [test_find_match.py](../scripts/test_find_match.py) | Looks up a match between two teams |
| [test_name_change.py](../scripts/test_name_change.py) | Exercises a member name change by Discord ID |
| [test_pagination_members.py](../scripts/test_pagination_members.py), [test_pagination_players.py](../scripts/test_pagination_players.py), [paged_league_players.py](../scripts/paged_league_players.py) | Exercise the paged list endpoints |
| [test_throttling.py](../scripts/test_throttling.py) | Fires a burst of API calls to observe throttling |

These are manual scripts, not part of the pytest suite.

## Assets

| Script | Generates |
|---|---|
| [make_card_banners.py](../scripts/make_card_banners.py) | `rsc/resources/transactions/card/`, the transaction card banners |
| [make_trade_banner.py](../scripts/make_trade_banner.py) | `rsc/resources/transactions/Trade.png`, from a PSD |
| [make_live_emoji.py](../scripts/make_live_emoji.py) | `rsc/resources/emoji/live.gif`, the animated LIVE application emoji |
| [parse_screenshot_stats.py](../scripts/parse_screenshot_stats.py) | Reads stats from a lobby scoreboard screenshot with OCR (needs Tesseract installed) |

## Operations

| Script | What it does |
|---|---|
| [bot_backup.sh](../scripts/bot_backup.sh) | Archives Red's data directory and uploads it to Google Cloud Storage. See [Deployment: backups](deployment.md#backups) |
