# Admin

**Package:** [rsc/admin/](../../rsc/admin/) · **Mixin(s):** `AdminMixIn`, `AdminAGMMixIn`, `AdminAuditMixIn`, `AdminFranchiseMixIn`, `AdminInactivityMixIn`, `AdminIntentsMixIn`, `AdminMatchMixIn`, `AdminMembersMixIn`, `AdminPermFAPollMixIn`, `AdminRetireMixIn`, `AdminStatsMixIn`, `AdminSyncMixIn` · **Details:** [package README](../../rsc/admin/README.md)

The admin module is the `/admin` command tree that league staff use to run the league from Discord. It creates and changes franchises, teams, members and matches in the RSC API, then brings Discord into line with them: roles, nicknames, franchise emoji and transaction channels. It also runs the season-transition chores: Intent to Play and activity check reminders (pings and DMs with answer buttons), PermFA-to-FA conversion polls, and finding and retiring players who have left the server.

Two jobs also run on a timer. A daily role sync re-applies API state to every league player, and a daily audit reports league players who are no longer in the server. Neither job retires anyone. Retiring is always a manual, confirmed command.

## Using it

Every command lives under `/admin` and, by default, needs the **Manage Server** permission (see [Commands](#commands)). The usual work, roughly in season order:

1. **Setting up a new server or season.** Run `/admin sync requiredroles` to create the base roles, `/admin sync tiers` for tier roles, tier FA roles and (optionally) tier chat and score-reporting channels, `/admin sync franchiseroles` for franchise roles, and `/admin sync transactionchannels` for each franchise's `<franchise>-transactions` channel. Set the text for `/dates` with `/admin dates`, and the AGM welcome text with `/admin agm message`.
2. **Franchises.** `/admin franchise create` makes a franchise with its GM. `addteam` and `delteam` manage its teams per tier. `rebrand` renames the franchise, its prefix and its teams. `logo` uploads a logo and updates the franchise emoji and role icon. `transfer` hands the franchise to a new GM. `/admin agm add` and `/admin agm remove` manage Assistant GMs.
3. **Intent to Play (end of season, signups open).** Set the missing role, channel and message once (`/admin intents missingrole`, `missingchannel`, `missingmsg`). Then use `/admin intents populate` to tag players who have not declared, `/admin intents ping` to ping that role in the channel, or `/admin intents dm` to DM every missing player with Returning / Not Returning buttons. Use `/admin stats intents` and `/admin stats intentbyfranchise` to track progress, and `/admin intents set` to record a player's intent for them.
4. **Activity check (draft-eligible players).** `/admin inactivecheck start` creates an `#inactivity-check` channel in a category you pick, with "I'm active" / "Withdraw" buttons, and pings the Draft Eligible role. Set a missing role with `/admin inactivecheck role`, then use `populate`, `ping` or `dm` to chase players who have not answered. Use `/admin inactivecheck manual` to record an answer for a player, and `/admin inactivecheck stop` to delete the channel and end the check.
5. **PermFA conversion poll (a tier is short on Free Agents).** `/admin permfa poll` DMs every Permanent Free Agent in a tier, asking whether they want to become a regular Free Agent. The poll stays open for 72 hours. `/admin permfa responses` lists the answers, with Yes answers in first-come order and with MMR. `remind` re-DMs players who have not answered, and `close` ends the poll early. The poll only collects answers. Staff still change player statuses themselves.
6. **Fixing individual players.** `/admin members patch` edits a league player's status, tier, team, MMR, contract length or waiver date. `changename` renames them, `transfer` moves a membership to a new Discord account, `signup` signs someone up, and `/admin sync member` re-applies API roles and nickname to one person.
7. **Players who left the server.** The daily audit posts a report to the league events channel. `/admin retire departed` shows the same list (a dry run by default) and, with `apply: True` plus a confirmation, retires them. `/admin members notinserver` gives a similar report for the current season and prints Discord IDs ready to paste into `/admin bulkretire`.
8. **The DM queue.** All bulk DMs go through the bot's single rate-limited queue. `/admin dmstatus` shows its progress and who could not be reached. `/admin dmcancel` drops everything still waiting.

## Commands

All groups are created with `guild_only=True` and `default_permissions=Manage Server`. Discord applies that default only to the top-level `/admin` command, and server admins can change who sees it under Server Settings > Integrations. The code has no further role checks, with one exception: the `override` option on `/admin inactivecheck manual` also checks Manage Server inside the command. "Who can run it" below therefore means **Manage Server, or whatever the server's Integrations settings allow for `/admin`**.

Several commands reply **publicly** in the channel rather than ephemerally: `members namehistory`, `elevatedroles`, `changename`, `transfer`, `patch`, `signup`, `signupstatus`, `intents set`/`setbyid`, `inactivecheck manual`, `matches create`/`playoff`/`bulk`, `sync member`, and the confirmation of `intents ping`.

### /admin (base)

| Command | Who can run it | What it does |
|---|---|---|
| `/admin settings` | Manage Server | Shows the intent missing channel, role and message, the `/dates` text and the AGM message. |
| `/admin dates` | Manage Server | Opens a modal and saves the text that the public `/dates` command shows. |
| `/admin dmstatus` | Manage Server | Shows the shared DM queue: running or idle, sent, failed, pending, scheduled, skipped, cancelled, and recently undeliverable members. |
| `/admin dmcancel` | Manage Server | Drops every pending and scheduled DM straight away, with no confirmation. A DM already being sent may still go out. |
| `/admin bulkretire` | Manage Server | Opens a modal for Discord IDs (one per line; `<@id>` mentions are accepted). Retires each player with admin override, resets roles for those still in the server, and posts a transaction card for each. Reports retired, skipped and failed players. |
| `/admin directmessage member message [send_at]` | Manage Server | DMs a member now, or at `send_at` (ISO 8601, read in the guild's timezone) through the DM queue. |

### /admin agm

| Command | Who can run it | What it does |
|---|---|---|
| `/admin agm message` | Manage Server | Modal. Saves the message posted in the franchise transaction channel when an AGM is added. |
| `/admin agm add franchise agm` | Manage Server | Adds the AGM in the API. If the member is an AGM of another franchise, that record is removed first. Then gives them the Assistant GM, League and franchise roles, sets their prefix, grants access to the franchise transaction channel and posts the AGM message there. Refuses if they are rostered on another franchise or if no AGM message is set. |
| `/admin agm remove franchise agm` | Manage Server | Removes the AGM record, re-syncs the member's roles and prefix from the API, and removes their transaction channel access. Refuses if the API says they are an AGM of a different franchise. |

### /admin franchise

| Command | Who can run it | What it does |
|---|---|---|
| `/admin franchise create name prefix gm` | Manage Server | After a confirmation, creates the franchise in the API, creates the `Name (GM name)` role, gives the GM that role and the General Manager role, and sets their prefix. `prefix` is 1 to 3 characters. |
| `/admin franchise addteam franchise tier name` | Manage Server | Creates a team in the API. |
| `/admin franchise delteam franchise tier team` | Manage Server | Deletes the matching team from the API. |
| `/admin franchise logo franchise logo` | Manage Server | Uploads a PNG of at most 200 KB to the API. Then replaces the franchise emoji (named after the prefix), resizing to 128x128 if needed, and sets the franchise role icon if the server has role icons. |
| `/admin franchise rebrand franchise [override]` | Manage Server | Modal for the new name, prefix and team names (one per line, highest tier first). The number of team names must match the franchise's tiers. After a confirmation, rebrands in the API, then renames the transaction channel (and re-sorts it alphabetically), the franchise role and the emoji, and re-prefixes every member who has the franchise role. `override` sets the API's `admin_override`. |
| `/admin franchise delete franchise` | Manage Server | Meant to delete the franchise and send its players to free agency. It currently always fails, because the API cannot delete franchises (see [Gotchas](#gotchas)). |
| `/admin franchise transfer franchise gm` | Manage Server | After a confirmation, transfers the franchise in the API. Renames the franchise role, gives the new GM the GM and franchise roles (removing FA, Captain, AGM and tier FA roles) and their prefix. Moves the old GM to Former GM with an `FA \|` prefix and their tier FA roles. Clears the AGM role and channel access of the franchise's former AGMs, because the API drops them on transfer, and swaps transaction channel access from the old GM to the new one. |

### /admin members

| Command | Who can run it | What it does |
|---|---|---|
| `/admin members namehistory member` | Manage Server | Lists the member's API name changes (old name, new name, date, who made the change). |
| `/admin members elevatedroles member` | Manage Server | Shows the member's API staff positions, fetched live rather than from the permission cache. |
| `/admin members changename member name [tracker] [override]` | Manage Server | Optionally adds a tracker, renames the member in the API, then re-syncs their roles and nickname. If they are a GM, also renames their franchise role. |
| `/admin members transfer old new` | Manage Server | Moves an RSC membership from an old Discord ID (typed as text) to a new member. |
| `/admin members patch player [status] [tier] [team] [base_mmr] [current_mmr] [contract_length] [waiver_period]` | Manage Server | Updates the league player in the API, then re-syncs their Discord roles and nickname. `contract_length` is 0 to 2. `waiver_period` is a date such as `2025-01-25`. |
| `/admin members create member [rsc_name]` | Manage Server | Creates an RSC member in the API. If `rsc_name` is given, also sets it as their nickname. |
| `/admin members delete member` | Manage Server | Permanently deletes the member from the API. |
| `/admin members list [rsc_name] [discord_username] [discord_id] [limit] [offset]` | Manage Server | Searches API members (at least one filter is required). `limit` is 1 to 64. `offset` is 0 to 64. |
| `/admin members signup player_type member [rsc_name] [tracker] [platform] [override]` | Manage Server | Signs a player up for the latest season. Region is fixed to East and referrer to Other. Then syncs their roles and nickname, adding the Dev League role if they qualify. |
| `/admin members signupstatus member [season]` | Manage Server | Shows whether the member is signed up for the signup season (or the current season if signups are closed). For returning players it shows their intent instead. The `season` option is accepted but not used. |
| `/admin members notinserver [status]` | Manage Server | A read-only sweep of current-season league players who are not in the server. Each miss is checked over HTTP, up to 100 checks. Prints details, then the bare IDs ready for `/admin bulkretire`. Defaults to every status except Former, Banned and Dropped. |

### /admin intents

| Command | Who can run it | What it does |
|---|---|---|
| `/admin intents set member returning [override]` | Manage Server | Records Intent to Play for a member. |
| `/admin intents setbyid member returning [override]` | Manage Server | Same, using a Discord ID (integer option). |
| `/admin intents missingrole role` | Manage Server | Sets the role used to tag players with a missing intent. |
| `/admin intents missingchannel channel` | Manage Server | Sets the channel that `ping` posts in. This channel is also linked in the intent DM. |
| `/admin intents missingmsg` | Manage Server | Modal. Sets the text that `ping` posts after the role mention. |
| `/admin intents populate` | Manage Server | Adds the missing role to players with no intent for the signup season (or the current season if signups are closed) and removes it from players who have since declared. |
| `/admin intents ping` | Manage Server | Posts `@missing-role <message>` in the missing channel. |
| `/admin intents dmtest [message]` | Manage Server | Sends you the intent DM, buttons included. |
| `/admin intents dm [member] [message]` | Manage Server | With `member`, DMs that one player straight away. Without it, shows a recipient list and confirmation, then queues a DM with Returning / Not Returning buttons to every player still missing an intent. Warns if DMs were already sent this season. Refuses when signups are closed. |

### /admin inactivecheck

| Command | Who can run it | What it does |
|---|---|---|
| `/admin inactivecheck start category` | Manage Server | Creates `#inactivity-check` in the category. Only Draft Eligible, GM and AGM can see it, and nobody can post. Posts the activity check message with "I'm active" / "Withdraw" buttons and pings Draft Eligible. |
| `/admin inactivecheck stop` | Manage Server | Deletes `#inactivity-check` and ends the check. Buttons in DMs then say the check has ended. |
| `/admin inactivecheck manual player status [override]` | Manage Server; `override` re-checks Manage Server | Records Active / NotActive for a player. |
| `/admin inactivecheck role role` | Manage Server | Sets the role used to tag players missing the check. |
| `/admin inactivecheck populate` | Manage Server | Adds or removes the missing role to match the players who have not completed the check this season. |
| `/admin inactivecheck ping` | Manage Server | Runs `populate`, then pings the missing role in `#inactivity-check`. |
| `/admin inactivecheck testmsg` | Manage Server | Sends you the activity check DM, buttons included. |
| `/admin inactivecheck dm` | Manage Server | After a confirmation, queues an activity check DM with buttons to every player who has not completed the check. Warns if DMs were already sent this season. |

### /admin permfa

| Command | Who can run it | What it does |
|---|---|---|
| `/admin permfa poll tier` | Manage Server | After a confirmation, opens a 72-hour poll and queues a Yes/No DM to every PermFA in the tier. Refuses while a poll for that tier is open or still closing. A new poll replaces the tier's previous results. |
| `/admin permfa dmtest member [reminder]` | Manage Server | Sends a preview of the poll DM, using the member's own tier. The buttons work but nothing is recorded. |
| `/admin permfa responses tier` | Manage Server | Shows the answers: Yes (first come, first served, with MMR and answer time), No, No Response, and Not Delivered. |
| `/admin permfa remind tier` | Manage Server | After a confirmation, re-DMs players who have not answered. The original deadline still applies. |
| `/admin permfa close tier` | Manage Server | Closes the poll now and removes the buttons from its DMs in the background. |

### /admin matches

| Command | Who can run it | What it does |
|---|---|---|
| `/admin matches create match_type format home_team away_team [day]` | Manage Server | Creates a match in the API. Both teams must be in the same tier. `day` is 0 to 20. |
| `/admin matches playoff round format home_team away_team` | Manage Server | Creates a postseason match. `round` (Playoff, Wildcard, Quarterfinals, Semifinals, Finals) is stored as the match day. |
| `/admin matches bulk` | Manage Server | Modal that takes a JSON list such as `[{"day":1,"type":"REG","format":"BO3","home":"Team1","away":"Team2"}]` and creates each match in order. |

Match types are `REG`, `PRE`, `PST`, `FNL` and `ANY`. Formats are `GMS`, `BO3`, `BO5` and `BO7`.

### /admin retire

| Command | Who can run it | What it does |
|---|---|---|
| `/admin retire departed [apply]` | Manage Server | Runs the departed-player audit now. Without `apply` it only lists the players. With `apply: True` and a confirmation it retires them through the same path as `bulkretire`, and mirrors the result to the league events channel. |
| `/admin retire audit` | Manage Server | Turns the daily departed-player audit on or off. It is on by default. |

### /admin stats

| Command | Who can run it | What it does |
|---|---|---|
| `/admin stats intents` | Manage Server | Counts of Returning, Not Returning and Missing intents for the signup season (or the current season if signups are closed). |
| `/admin stats intentbyfranchise` | Manage Server | Completed and missing intents per franchise, with the most missing first. |
| `/admin stats current` | Manage Server | Count of current-season league players by status. |
| `/admin stats signups` | Manage Server | Number of Draft Eligible players for the signup season. |

### /admin sync

| Command | Who can run it | What it does |
|---|---|---|
| `/admin sync requiredroles` | Manage Server | Creates any missing base roles: League, General Manager, Assistant GM, Free Agent, Captain, Former Player, Former Admin, Former Staff, Spectator, Subbed Out, IR, Muted, PermFA and PermFA in Waiting. |
| `/admin sync tiers [chatcategory] [scorecategory]` | Manage Server | Creates or recolours each tier role and `<Tier>FA` role from the API. If categories are given, creates `<tier>-chat` and `<tier>-score-reporting` channels or resets their overwrites. |
| `/admin sync transactionchannels category [delete_stale]` | Manage Server | After a confirmation, creates any missing `<franchise>-transactions` channels, giving access to the transactions role and the GM, and pings the GM. With `delete_stale`, deletes every text channel in the category that does not match a franchise. |
| `/admin sync franchiseroles` | Manage Server | After a confirmation, creates missing `Franchise (GM name)` roles and renames roles whose GM part is out of date. |
| `/admin sync players [dryrun]` | Manage Server | After a confirmation, re-applies roles and nickname from the API to every league player in the server. Slow. |
| `/admin sync nonplaying [dryrun]` | Manage Server | After a confirmation, resets every API member who is not a league player (or is Dropped) to non-playing roles. Then removes the Assistant GM role from anyone the API has no AGM record for. Slow. |
| `/admin sync member member` | Manage Server | Re-applies API roles and nickname to one member, including non-playing GMs and AGMs. |
| `/admin sync freeagent [dryrun]` | Manage Server | After a confirmation, re-syncs every FA and PermFA, with a progress bar and a cancel button. |
| `/admin sync drafteligible [dryrun]` | Manage Server | After a confirmation, re-syncs every Draft Eligible player, with a progress bar and a cancel button. |

### /admin audit

| Command | Who can run it | What it does |
|---|---|---|
| `/admin audit search [action] [before] [after] [user] [limit]` | Manage Server | Reads the server's Discord audit log for one action type. The entries are only written to the debug log and the command sends no reply (see [Gotchas](#gotchas)). |

## Configuration

Per-guild settings are stored in Red `Config` under the custom group `"Admin"`, keyed by guild ID ([admin.py](../../rsc/admin/admin.py)):

| Key | Default | Set by |
|---|---|---|
| `Dates` | `None` | `/admin dates` (read by `/dates` in the leagues module and by the LLM agent's league tool) |
| `AgmMessage` | `None` | `/admin agm message` |
| `IntentChannel` | `None` | `/admin intents missingchannel` |
| `IntentMissingRole` | `None` | `/admin intents missingrole` |
| `IntentMissingMsg` | `None` | `/admin intents missingmsg` |
| `IntentDmLastSeason`, `IntentDmLastRun`, `IntentDmLastExecutor` | `None` | Written by `/admin intents dm` when confirmed. Used for the "already sent this season" warning. |
| `ActivityCheckMissingRole` | `None` | `/admin inactivecheck role` |
| `ActivityCheckMsgId` | `None` | Set by `/admin inactivecheck start`, cleared by `stop`. Its presence means "an activity check is running". |
| `ActivityCheckDmLastSeason`, `ActivityCheckDmLastRun`, `ActivityCheckDmLastExecutor` | `None` | Written by `/admin inactivecheck dm` when confirmed. |
| `RetireAuditEnabled` | `True` | `/admin retire audit` (toggle) |

PermFA polls are stored in a second custom group, `"PermFAPoll"`, keyed by (guild ID, tier ID). Each tier keeps one record, with `PollId`, `TierId`, `TierName`, `Season`, `CreatedAt`, `ExpiresAt`, `CreatedBy`, `ClosedAt`, `ClosedBy`, `LastRemindAt`, `DmsCleaned` and `Recipients`. Each recipient has a name, MMR, delivery state, answer, answer time, and the DM message IDs kept until the poll is cleaned up. These records are written by the `/admin permfa` commands and by the DM buttons.

The module also reads settings owned by other modules:

- The league events channel ([events](./events.md)): where the departed-player audit posts.
- The welcome roles ([welcome](./welcome.md)): the default roles given to non-playing members.
- The transactions role and transaction log channel ([transactions](./transactions.md)).
- The ModMail bot ID: linked in DMs.
- The guild timezone: used by `directmessage send_at`.
- The per-guild API configuration and league ID ([../configuration.md](../configuration.md)).

## Background work

- **Daily Discord role sync** (`sync_discord_roles`, [sync.py](../../rsc/admin/sync.py)). A `tasks.loop` at 07:00 UTC. For every league player in the API, it re-applies roles, nickname, Dev League role and AGM franchise state with `update_league_player_discord`. **It only runs for guild `395806681994493964`, which is hard-coded.** It restarts itself if it crashes.
- **Daily departed-player audit** (`retire_audit_loop`, [retire.py](../../rsc/admin/retire.py)). A `tasks.loop` at 09:00 UTC. For every guild that has the audit on, the API configured and an events channel set, it posts a report of active league players who are no longer in the server. It only reports and never retires. It restarts itself if it crashes.
- **PermFA poll close timers** ([permfa_poll.py](../../rsc/admin/permfa_poll.py)). These are one-off `asyncio` tasks rather than a loop: one per open poll, sleeping until the deadline. At expiry, or after `/admin permfa close`, a sweep edits every poll DM to show the final answer and remove the buttons, pausing 1 second between edits. `setup()` re-arms the timers on each start, and sweeps straight away any poll that expired while the bot was down. `cog_unload` cancels them.
- **Persistent activity check view.** On startup, `setup_persistent_activity_check` re-attaches `InactiveCheckView` to the stored `ActivityCheckMsgId`, so the channel buttons keep working after a restart. If `#inactivity-check` no longer exists, it clears the stored ID instead.
- **Dynamic DM buttons**, registered once at startup with `bot.add_dynamic_items()` in [core.py](../../rsc/core.py):
  - `IntentDMButton` (`intent_dm:<guild>:<season>:<yes|no>`) declares intent from a DM. It checks that signups are still open and that the season matches, and answers "out of date" otherwise.
  - `ActivityCheckDMButton` (`activity_dm:<guild>:<season>:<yes|no>`) submits the activity check. It checks that the check is still running (`ActivityCheckMsgId`) and the season matches.
  - `PermFAPollButton` (`pfa_poll:<guild>:<tier>:<poll>:<yes|no>`) records a poll answer. Poll ID `0` is the `dmtest` preview, which records nothing.
- **DMs sent:**
  - Bulk intent, activity check and PermFA poll DMs and reminders are queued on the bot's single `DMHelper` (1.5 s base rate). Each carries a send-time precheck, so a player who answers while the batch is draining is skipped. PermFA DMs also report delivery back into the poll record.
  - `/admin directmessage` with `send_at` is also queued.
  - Sent directly, outside the queue: `directmessage` without `send_at`, the single-player `/admin intents dm member:`, and the `dmtest`/`testmsg` previews.
- **Channel posts:** the AGM message in the franchise transaction channel; retirement transaction cards from `bulkretire` and `retire departed` in the transaction log channel; audit reports and `retire departed` results in the events channel; intent pings and activity check pings.

## How it works

**Files**

- [admin.py](../../rsc/admin/admin.py): `AdminMixIn`, the root. It defines the top-level `/admin` group, registers the `"Admin"` Config group, and holds the base commands (`settings`, `dates`, `dmstatus`, `dmcancel`, `bulkretire`, `directmessage`). It also has the shared helpers used across the package:
  - `bulk_retire_players` and `build_bulk_retire_embed`.
  - `_ensure_chunked`, which chunks the guild member cache with a 30 s timeout.
  - `_resolve_members_by_id`, which splits IDs into members, left-the-guild and lookup-failed. It checks the cache first and falls back to `fetch_member`, capped at 25 lookups by default.
  - `_format_truncated_list`, which fits a list into the 1024-character embed field limit.
- [agm.py](../../rsc/admin/agm.py): `/admin agm`.
- [audit.py](../../rsc/admin/audit.py): `/admin audit search`, and an indexable `RSCAuditLogAction` enum for autocomplete.
- [franchise.py](../../rsc/admin/franchise.py): `/admin franchise`, including `rebrand_length_errors` (prefix at most 3 characters, team names at most 16) and `_clear_former_agms`.
- [inactivity.py](../../rsc/admin/inactivity.py): `/admin inactivecheck`, the role populate logic and the persistent-view setup.
- [intents.py](../../rsc/admin/intents.py): `/admin intents`, including the DM flow.
- [match.py](../../rsc/admin/match.py): `/admin matches`.
- [members.py](../../rsc/admin/members.py): `/admin members`.
- [permfa_poll.py](../../rsc/admin/permfa_poll.py): `/admin permfa`, the `PermFAPoll` and `PollRecipient` records, click handling, close timers and the results renderer.
- [retire.py](../../rsc/admin/retire.py): the departed-player audit loop and `/admin retire`.
- [stats.py](../../rsc/admin/stats.py): `/admin stats`.
- [sync.py](../../rsc/admin/sync.py): the daily role sync loop and `/admin sync`.
- [views.py](../../rsc/admin/views.py): `InactiveCheckView` (channel buttons, which call the API with their own `ApiClient`), the three dynamic DM buttons and their `build_*_view` helpers, and the confirmation views. `DMConfirmView`, `ConfirmSyncView` and `ConfirmRetireView` use the default 30 s timeout. The rebrand, delete, create and transfer franchise views also use 30 s.
- [modals.py](../../rsc/admin/modals.py): the bulk match, bulk retire, AGM message, league dates, intent missing message and franchise rebrand modals. They time out after 600 s.
- [models.py](../../rsc/admin/models.py): `BulkRetireResult`, `DepartedReport` and the `CreateMatchData` pydantic model for bulk matches.

**RSC API calls** go through wrapper methods that other mixins own. The admin code itself only calls those wrappers. The underlying `rscapi` endpoints are:

- Franchises: `franchises_create`, `franchises_rebrand_update`, `franchises_upload_logo_update`, `franchises_transfer_franchise_update`, `franchises_add_agm_update`, `franchises_remove_agm_update`, and the franchise list.
- Teams: `teams_create`, `teams_destroy`.
- Members: `members_create`, `members_destroy`, `members_list`, `members_signup_create`, `members_name_change_partial_update`, `members_name_changes_list`, `members_elevated_roles_list`, `members_transfer_account_create`, `members_intent_to_play_create`, `members_activity_check_create`.
- Trackers: `tracker_links_create`.
- League players: `league_players_list`, `league_players_partial_update`.
- Seasons: `seasons_signup_season_retrieve`, `seasons_player_intents_list`, `seasons_activity_check_list`.
- Matches: `matches_create`.
- Transactions: `transactions_retire_create`.

All role and nickname changes go through `rsc.transactions.roles` (`update_league_player_discord`, `update_nonplaying_discord`, `update_free_agent_discord`, `update_draft_eligible_discord`, `update_nonplaying_gm_discord`).

**Main flows**

- *Bulk DM (intents, activity check, PermFA).* The flow runs in this order:
  1. Get the missing set from the API.
  2. Resolve it to members with `_resolve_members_by_id`.
  3. Show a recipient list with `DMConfirmView`.
  4. On confirm, record the run ("last run" Config, or the poll record) *before* queueing, so a second admin confirming at the same time sees the warning.
  5. Enqueue one fresh view per DM, with a precheck.

  The missing activity check set is always `completed=False, missing=True` via `_fetch_missing_activity_checks`. The API keeps `missing=True` on records that are already completed, so filtering on `missing` alone would return the whole roster.
- *Departed-player audit* (`find_departed_players`). It aborts rather than guess when:
  - the gateway is unhealthy;
  - chunking fails;
  - the cache holds less than 90% of `member_count`;
  - more than 5% of active players appear to have left (and at least 10 do).

  A player only counts as departed when `fetch_member` returns NotFound, with up to 250 lookups. Every status except Former, Dropped and Banned counts as active. This sweep catches leavers that the `on_raw_member_remove` listener in [transactions](./transactions.md) missed because the bot was offline.
- *PermFA poll state.* Each change to a poll record is a read-modify-write of the whole record under a per-(guild, tier) `asyncio.Lock`. `PermFAPoll.is_open()` alone decides whether answers are accepted. Pressing the same answer again keeps the original answer time, so the player keeps their first-come position. The close sweep edits DMs outside the lock and clears message refs as it goes, so an interrupted sweep resumes where it stopped. A new poll is blocked until `DmsCleaned` is true.
- *AGM add and remove* change the API before touching Discord, so a failure leaves Discord untouched and the command can simply be re-run. `add_agm` is idempotent.

## Gotchas

- **`/admin franchise delete` cannot succeed.** `delete_franchise` in [franchises.py](../../rsc/franchises/franchises.py) always raises "The API does not support deleting franchises", so none of the Discord cleanup after it runs.
- **The daily role sync only covers one guild.** `sync_discord_roles` skips every guild except the hard-coded ID `395806681994493964`.
- **`/admin audit search` never replies.** It writes the matching audit entries to the debug log only, so Discord shows "The application did not respond". It also errors unless `action` is given.
- **`/admin franchise create` fails if the franchise role already exists.** `frole` is only assigned when the role is created, so with an existing `Name (GM)` role the `add_roles` call raises after the API franchise has already been created.
- **`/admin sync transactionchannels delete_stale:True` deletes every text channel in the category that is not named after a franchise.** Point it only at the dedicated transactions category.
- **Franchise roles are found by prefix match.** `franchise_role_from_name` returns the first role whose name starts with the franchise name, case-insensitive. A franchise whose name is a prefix of another role's name can match the wrong role.
- **`#inactivity-check` is found by name anywhere in the guild.** `stop`, `ping`, startup re-attach and the DM jump link all look it up by name, while `start` only checks the chosen category for duplicates.
- **The intent and activity check DM buttons stay on the message forever.** They answer "signups are closed", "check has ended" or "out of date" rather than disappearing. Only PermFA poll DMs have their buttons removed, by the close sweep.
- **`/admin intents dm` refuses once signups close**, while `populate`, `stats intents` and `members signupstatus` fall back to the current season.
- **`/admin intents setbyid` takes the Discord ID as an integer option.** Discord integer options cannot hold full snowflakes. The code comment in `/admin members transfer` gives this as the reason that command takes its ID as a string.
- **`/admin matches bulk` stops at the first failure.** Matches created before the failure stay in the API. The error lists them, so you know where to resume.
- **`/admin dmcancel` drops everything** in the shared queue, including DMs from other features such as lobby notifications. There is no confirmation.
- **The PermFA poll only collects answers.** It changes no player status. Its tier argument is matched by name (capitalised) against the poll records in Config.
- **`/admin bulkretire` and `/admin retire departed` retire with `admin_override=True`.**
