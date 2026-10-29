# Ballchasing

**Package:** [rsc/ballchasing/](../../rsc/ballchasing/) · **Mixin(s):** `BallchasingMixIn`

Match reporting. After a series, a player or GM runs `/reportmatch`, enters each team's wins and attaches the replay files. The bot then:

1. finds the scheduled match in the RSC API;
2. uploads the replays to [ballchasing.com](https://ballchasing.com) into a group for that match, skipping replays that are already there;
3. reports the score and the ballchasing group to the RSC API;
4. posts a result card in the tier's score-reporting channel, pinging both GMs.

The `/ballchasing` group holds the server settings for all of this.

## Using it

**Server admins (Manage Server)** set it up once:

1. `/ballchasing key` with the league's ballchasing.com API key.
2. `/ballchasing toplevelgroup` with the ID of the league's top-level ballchasing group, for example `rsc-v4rxmuxj6o`. Every match group is created under it.
3. `/ballchasing category` with the category that holds the score-reporting channels. Each tier needs a text channel named `<tier>-score-reporting` (lowercase tier name, for example `elite-score-reporting`) in that category.
4. `/ballchasing log` with the stats committee channel, where upload failures are reported.
5. `/ballchasing manager` with the stats committee role. Members with it may use `override` on `/reportmatch`.
6. Reload the cog or restart the bot so the ballchasing client is built with the new key (see Gotchas). Then run `/ballchasing ping` to confirm the key works, and `/ballchasing settings` to review everything.

**Players and GMs** report matches:

1. Run `/reportmatch home:<team> away:<team>`. Team names autocomplete. Add `day:` if the same two teams meet more than once within a week.
2. The bot looks up the match. It searches a window of 7 days either side of today. If it finds nothing, it says so before the form opens. When the lookup is quick, the form shows the tier, match day and series format, for example "Best of 5" or "4-game series".
3. In the form, enter each team's games won and attach the `.replay` files: one per game, up to 10.
4. You get a private "Processing Match" message. When it finishes, it is replaced by your own copy of the result card, with a line such as "Uploaded 3 · skipped 1 duplicate(s)". The public card goes to the tier's score-reporting channel.

Rules the bot enforces:

- Only players on either team, or either team's **GM**, can report. AGMs cannot report unless they also play on one of the teams.
- `override:True` is only for members with Manage Server or the ballchasing manager role. Admins who are not on either team must use it to report. The override flag is also passed to the RSC API.
- The wins must fit the series. In a best-of-N, the total must be between ceil(N/2) and N. In a fixed N-game series, the total must equal N. At least one game must have been won.
- Every file must end in `.replay` and parse as a Rocket League replay. If two attached files are the same game, the whole submission is rejected. That covers the same file twice, and two players' recordings of one game.
- It does not matter which team you put first. Scores are matched to the API's real home and away teams before reporting.

If two people report the same match at once, the second waits for the first to finish and is told so. Replays the first person already uploaded are skipped. If the match was already reported, the RSC API refuses the score. Any new replays are still added to the group, and the reporter sees "This match has already been reported but all additional replays have been uploaded."

**Stats committee:** watch the log channel. A "Replay Upload Failures" message lists each replay that did not make it into the group and why, with a link to the group.

## Commands

**`/ballchasing`** (group default permission: Manage Server, server only. Each subcommand except `scanmissing` also checks Manage Server in code.)

| Command | Who can run it | What it does |
|---|---|---|
| `/ballchasing settings` | Manage Server | Show whether a key is set, the manager role, log channel, report category and the top-level group link. |
| `/ballchasing key key` | Manage Server | Save the ballchasing API key. |
| `/ballchasing ping` | Manage Server | Test the key. Shows the Steam name, Steam ID and Patreon tier of the key's owner. |
| `/ballchasing manager role` | Manage Server | Set the ballchasing management role, for example the Stats Committee. |
| `/ballchasing log channel` | Manage Server | Set the channel for upload failure reports. |
| `/ballchasing category category` | Manage Server | Set the category that holds the `<tier>-score-reporting` channels. |
| `/ballchasing toplevelgroup group` | Manage Server | Set the top-level ballchasing group ID. |
| `/ballchasing scanmissing [matchday] [matchtype]` | Manage Server (default permission) | Not implemented. It replies with a not-implemented message. |

**Match reporting**

| Command | Who can run it | What it does |
|---|---|---|
| `/reportmatch home away [day] [override]` | Anyone may run it. Only players on either team or either team's GM may report. `override` needs Manage Server or the ballchasing manager role. | Opens the report form, uploads the replays, reports the score to the RSC API and posts the result card. |

## Configuration

Red `Config` custom group **`Ballchasing`** (identifier: guild id):

| Key | Default | Set by |
|---|---|---|
| `AuthToken` | `None` | `/ballchasing key` |
| `TopLevelGroup` | `None` | `/ballchasing toplevelgroup` |
| `LogChannel` | `None` | `/ballchasing log` |
| `ManagerRole` | `None` | `/ballchasing manager` |
| `ReportCategory` | `None` | `/ballchasing category` |

No environment variables. The ballchasing base URL is hard-coded as `BALLCHASING_URL = "https://ballchasing.com"` and is used to build group and replay links. API calls go through the `python-ballchasing` client (`ballchasing.Api`), which the project takes from a git fork (see `pyproject.toml`).

Constants in [ballchasing.py](../../rsc/ballchasing/ballchasing.py):

| Constant | Value | Meaning |
|---|---|---|
| `EARLY_MATCH_LOOKUP` | 2.0s | How long `/reportmatch` waits for the match lookup before opening the form anyway |
| `BC_REPORT_TIMEOUT` | 300s | Ceiling on the upload and report step for one match |
| `BC_LEDGER_TTL` | 3600s | How long the bot remembers what it uploaded to a group |
| `BC_LEDGER_MAX_GROUPS` | 512 | Ledger size before a sweep of expired entries |

The form itself times out after `MODAL_TIMEOUT` (600 seconds, from `rsc/const.py`).

## Background work

- **Startup**: `prepare_ballchasing(guild)` runs from the cog's per-guild setup in [core.py](../../rsc/core.py), only for guilds that have RSC API configuration. It builds a `ballchasing.Api` from the saved key, pings it, and keeps the client in memory. Setup runs again on every `on_ready`, but the client is only rebuilt when the key has changed.
- **Unload**: `close_ballchasing_sessions()` closes every client.
- **Channel posts**, all triggered by `/reportmatch`: the result card in `<tier>-score-reporting`, which pings the two GMs (user mentions allowed, role and `@everyone` mentions blocked), and failure reports in the log channel.
- There are no task loops, listeners, persistent views or DMs. The result card is a Components V2 `LayoutView` that holds only link buttons ("Match page" and "Ballchasing"), so nothing needs to listen for clicks.

## How it works

### Files

- [ballchasing.py](../../rsc/ballchasing/ballchasing.py): `BallchasingMixIn`. Settings commands, `/reportmatch`, upload orchestration, locks, the upload ledger, channel announcements and Config accessors.
- [groups.py](../../rsc/ballchasing/groups.py): finds or creates the group ladder for a match. Also holds `purge_ballchasing_group()`, a destructive helper that no command uses.
- [process.py](../../rsc/ballchasing/process.py): reads and parses replays (`replay_parser`), builds fingerprints, detects duplicates, and holds the upload result types.
- [modals.py](../../rsc/ballchasing/modals.py): `ReportMatchModal` (score inputs and a `FileUpload`) and `score_error()` for series validation.
- [views.py](../../rsc/ballchasing/views.py): `MatchResultCard`, the V2 result card, and `match_label()`.
- [validation.py](../../rsc/ballchasing/validation.py): `is_replay_file()`, which only checks the `.replay` extension.

### `/reportmatch` flow

1. If `override` is set, check `has_bc_permissions` (Manage Server or the manager role).
2. Look up the match within `EARLY_MATCH_LOOKUP`: `find_match()` from the [matches](./matches.md) module, over today ±7 days, then `get_match_from_list()`, which accepts the two teams in either order. A slow lookup opens the form without match details and the lookup runs again after submit.
3. Open the form and wait for it. Check that there are replays, that the score is above zero, and that every file ends in `.replay`.
4. `process.build_candidates()` reads each attachment once and parses it in a worker thread. It computes:
   - an MD5 digest of the file bytes;
   - a **fingerprint**: an MD5 over the sorted per-player `name:score:goals:assists:saves:shots` lines. Every player's recording of one game produces the same fingerprint.
   - the match GUID, for reference only.
5. `duplicate_in_batch()` rejects the submission if two files share a digest or a fingerprint.
6. Check that the match has an id and a tier, run `score_error()`, normalize home and away, and check who is reporting (`discord_member_in_match`, `is_match_franchise_gm`).
7. Take the per-match lock (`bc_match_guard`) and start the 300 second timeout, then run `process_match_replays()`:
   - **Group**: under the per-guild group lock, `groups.rsc_match_bc_group()` reuses `match.results.ballchasing_group` if the API already has one. Otherwise it finds or creates the ladder: top-level group → `Season <n>` → match type name → tier → `Match Day 07` (or the playoff round name) → `Home vs Away`. Each level is searched with a name filter first, then with an unfiltered listing, before a new group is created. New groups use player identification by ID and team identification by clusters. Resolved IDs are cached per guild.
   - **Duplicates against the group**: `replay_group_collisions()` fingerprints the replays already in the group, ignoring replays whose processing failed. It also uses the in-memory **upload ledger** of replays this bot uploaded in the last hour, which covers replays ballchasing has not finished processing. Matching candidates are skipped.
   - **Upload**: each remaining replay is uploaded as public under a random 64-character name into the group. If ballchasing says the replay already exists, the existing replay is moved into the group (`patch_replay`). Other ballchasing errors and network errors are recorded per file. If the rate-limit backoff runs out, the rest of the batch is marked as skipped.
8. `report_match()` (matches module) calls the RSC API score report endpoint with the group, the scores, the reporter's Discord id and `override`. An `RscException` with status 500 is treated as "already reported".
9. `report_upload_failures()` posts to the log channel when any file failed.
10. `match_result_card()` gathers the tier colour, the winning franchise's logo (else the server icon, else the bundled `rsc_logo.png`), the GM mentions, the website match page link and the ballchasing group link. The card is rendered twice: once for the score-reporting channel, and once (with the upload summary) to replace the reporter's message.

### Services called

- **ballchasing.com** through `python-ballchasing`: `ping`, `get_groups`, `create_group`, `get_group_replays`, `upload_replay_from_bytes`, `patch_replay`.
- **RSC API** through other mixins: `find_match` and `report_match` (matches), `franchises` and `franchise_logo`, `season_id_for_number`, and `timezone`.
- The **league website** match page URL comes from the guild's API host via `rsc/utils/website.py` (the API URL with `/api/...` removed): `/matches/<id>/?league=..&season=..&source=matches`.

### Invariants

- One reporter per match at a time: the per-match `asyncio.Lock` is reference-counted so waiters keep the same lock. Group creation is serialized per guild. The match lock is always the outer lock.
- Locks, the group cache and the ledger are in memory only. They reset on reload, and the ledger entries also expire after an hour.
- Fingerprints never use timestamps or the match GUID. A series played in one lobby shares one GUID, so the GUID cannot tell games apart.

## Gotchas

- `/ballchasing key` only saves the key. The client is built in `prepare_ballchasing()` during setup, so `/ballchasing ping` says "not configured" (or keeps using an old key) until the cog is reloaded or the bot reconnects. Guilds without RSC API configuration never get a client.
- Admins who are not on either team are refused unless they set `override:True`. AGMs are refused unless they play on one of the teams. Only GMs get the franchise exception.
- The per-tier channel must be named exactly `<tier name lowercased>-score-reporting` and must be in the configured category. Otherwise the public card is skipped with only a log warning.
- The score check only looks at the total number of games. In a best of 5, 2–1 passes because 3 games falls within 3 to 5.
- If one file in a submission fails to parse, nothing from that submission is uploaded.
- "Already reported" is inferred from an HTTP 500 from the RSC API, not from a specific error code.
- `/ballchasing scanmissing` is a stub.
- The permission error for `override` sent before the form opens is not ephemeral, so the channel sees it.
