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
| [combines_lobby.py](../scripts/combines_lobby.py) | Posts sample Combines lobbies (`start <guild_id>`, `-2` for the 2v2 sample) or a game-finished event (`teardown <guild_id> <lobby_id>`) to the bot on `localhost:8008`. Samples are in [data/combines/](../data/combines/) |
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
