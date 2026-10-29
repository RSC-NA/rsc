# Transactions

**Package:** [rsc/transactions/](../../rsc/transactions/) · **Mixin(s):** `TransactionMixIn` · **Details:** [package README](../../rsc/transactions/README.md)

Transactions are the roster moves of the league: signing, cutting, re-signing, trading, drafting, temporary subs, Inactive Reserve, redshirts and retirements. The transaction committee runs these from Discord. The bot sends each move to the RSC API, updates the player's Discord roles and nickname prefix to match, and posts an announcement card in the transactions channel that pings the player and GM.

The module also handles moves that happen outside these commands. Trades made on the RSC website are announced and reconciled when the API reports them. When a league player leaves the server, they are retired automatically.

## Using it

**Admins set it up once** (all need Manage Server):

1. `/transactions transactionchannel` sets the public channel where announcement cards are posted. Trades and generic announcements refuse to run without it.
2. `/transactions logchannel` and `/transactions role` set the committee's private log channel and the role pinged there.
3. `/transactions notifications` turns on committee pings in the log channel. `/transactions gmnotifications` turns on GM pings in each franchise's `<franchise>-transactions` channel. Both are currently used only when a player leaves the server.
4. `/transactions cutmsg` sets the message sent to cut players by DM, and `/transactions toggledm` turns those DMs on.
5. `/transactions tools tradeannouncements` and `/transactions tools traderoleupdates` control how website trades are handled. Both are on by default.
6. `/transactions settings` shows everything.

**The transaction committee works day to day with:**

- `/transactions sign`, `cut` and `resign` for single-player moves, and `/transactions ir` (MOVE or RETURN) for Inactive Reserve.
- `/transactions sub` on match nights to put a free agent in for a starter. The bot gives the starter the "Subbed Out" role, posts a temporary-contract card, records the sub, and hides the free agent from `/freeagent availability`. The next day the bot posts a "contract expired" card and removes the role. `/transactions expire` ends a sub early, and `/transactions sublist` shows active subs.
- `/transactions trade` opens a form where you paste the trade text (format below). The bot parses it, sends it to the API, updates every traded player's roles, and posts a trade card.
- `/transactions draft` during the draft, and `/transactions captain` to set captains.
- `/transactions retire` and `/transactions redshirt` (moves an AGM to redshirt).
- `/transactions history` and `/transactions leaderboard` to review what was done.

Most move commands have an `override` option, described as admin-only. The bot does not enforce that itself (the check is commented out in the code). It sends `admin_override` and the executor's Discord ID to the API with the request.

**Trade text format** for `/transactions trade`, one item per line:

```
GMName receives:
@Player Display Name
@Player Display Name to Team Name
1st Round Elite (12)
OtherGM's 2nd Round Elite (30)
OtherGM's S25 1st Round Elite
---
OtherGM receives:
...
```

- `X receives:` starts a franchise's section. `X` is matched against the start of each General Manager role member's name, with the franchise prefix removed.
- `@Name` must match a League role member's display name exactly. Without `to Team`, the player goes to the receiving franchise's team in the player's current tier.
- `Nth Round Tier (pick)` is a pick for this season. In a trade between more than two franchises, put the giving GM's name in front (`GM's 1st Round ...`).
- `GM's S<season> Nth Round Tier` is a future pick.
- `---` ends a section, and blank lines are ignored. Any other line is a parse error.

**Players** do not run transaction commands. They receive the announcement pings and, if DMs are on, the cut message.

## Commands

All commands are in the `/transactions` group, which is server-only. The group's default permission is **Manage Roles**, so Discord hides it from members without that permission unless an admin changes it under Server Settings > Integrations. Commands marked "Manage Server" check that permission in code as well.

### Committee moves

| Command | Who can run it | What it does |
| --- | --- | --- |
| `/transactions sign <player> <team> [notes] [override]` | Manage Roles (default) | Signs the player to the team. Removes FA, tier FA, Spectator, Former Player and Draft Eligible roles, plus any old franchise role and old tier role. Adds the new franchise and tier roles and sets the nickname prefix. Posts a SIGNED card. |
| `/transactions cut <player> [notes] [announce] [override]` | Manage Roles (default) | Releases the player to free agency. Removes the captain and franchise roles, adds Free Agent and `<Tier>FA`, and sets the prefix to `FA`. A GM keeps their franchise role and prefix. Posts a RELEASED card and DMs the cut message if `announce` is true. |
| `/transactions resign <player> <team> [notes] [announce] [override]` | Manage Roles (default) | Re-signs the player. Role updates are the same as sign. Posts a RE-SIGNED card if `announce` is true. |
| `/transactions sub <player_in> <player_out> [notes] [override]` | Manage Roles (default) | Temporary substitution. Gives `player_out` the "Subbed Out" role, posts a TEMPORARY CONTRACT card, saves the sub for expiry, and hides `player_in` from the FA availability list. |
| `/transactions expire <player>` | Manage Roles (default) | Ends a temporary contract in the API. If the bot has the sub recorded, it also removes "Subbed Out" from the starter, posts a CONTRACT EXPIRED card, and drops the record. |
| `/transactions sublist` | Manage Roles (default) | Shows every recorded sub (in, out, team). The reply is public. |
| `/transactions ir <action> <player> [notes] [announce] [override]` | Manage Roles (default) | `MOVE` puts the player on Inactive Reserve and adds the "IR" role. `RETURN` takes them off and removes it. Posts an INACTIVE RESERVE card if `announce` is true and the franchise has a GM. |
| `/transactions redshirt <player> [notes] [override]` | Manage Roles (default) | Moves an AGM to redshirt status in the API, using the IR endpoint with `redshirt=true`, and removes their tier and tier FA roles. Posts no announcement. |
| `/transactions retire <player> [notes] [override] [announce]` | Manage Roles (default) | Retires the player. Removes League, franchise, tier, FA, IR, Captain and Subbed Out roles. Adds the welcome roles, plus Former Player if they had a prefix, and strips the prefix. A retiring AGM keeps the AGM role, League role, franchise role and prefix, which only `/admin agm remove` ends. Posts a RETIRED card if `announce` is true. |
| `/transactions trade [notes] [override] [announce]` | Manage Roles (default) | Opens the trade form, parses the text, sends the trade to the API, updates every traded player's roles and nickname, and posts a trade card if `announce` is true. If `notes` is not given, the trade text is sent as the notes. |
| `/transactions draft <player> <team> <round> <pick> [override]` | Manage Roles (default) | Records a draft pick, updates the player's roles, and posts a plain line in the transactions channel ("Round R Pick P: @player was drafted/kept by Team (@GM - Tier)"). The reply is public. |
| `/transactions captain <player> [player1 … player6]` | Manage Roles (default) | Toggles the captain flag for up to seven rostered players, then syncs the "Captain" role across each player's whole team. |

### Announcements and lookups

| Command | Who can run it | What it does |
| --- | --- | --- |
| `/transactions announce` | Manage Roles (default) | Opens a form and posts its text as-is in the transactions channel. User mentions ping. |
| `/transactions announcetrade` | Manage Roles (default) | Opens the trade form and posts the raw text in the transactions channel. It does not send anything to the API. |
| `/transactions history [player] [executor] [season] [type] [limit]` | Manage Roles (default) | Lists up to 20 transactions (default 10) for the current season unless a season is given. Shows date, type and executor ID. Only you can see the reply. |
| `/transactions leaderboard [season] [transaction_type] [no_draft]` | Manage Roles (default) | Top 15 committee members by number of transactions run in the season (current season by default). The reply is public. |

### Settings

| Command | Who can run it | What it does |
| --- | --- | --- |
| `/transactions settings` | Manage Server | Shows every setting below. |
| `/transactions transactionchannel <channel>` | Manage Server | Sets `TransChannel`. |
| `/transactions logchannel <channel>` | Manage Server | Sets `TransLogChannel`. |
| `/transactions role <role>` | Manage Server | Sets `TransRole`. |
| `/transactions notifications` | Manage Server | Toggles `TransNotifications`. |
| `/transactions gmnotifications` | Manage Server | Toggles `TransGMNotifications`. |
| `/transactions toggledm` | Manage Server | Toggles `TransDMs`. |
| `/transactions cutmsg` | Manage Server | Opens a form (up to 4,000 characters) and saves it as `CutMessage`. |

### `/transactions tools`

| Command | Who can run it | What it does |
| --- | --- | --- |
| `/transactions tools tradeannouncements` | Manage Server | Toggles `TradeAnnouncements` for website trades. Trades run with `/transactions trade` are not affected. |
| `/transactions tools traderoleupdates` | Manage Server | Toggles `TradeRoleUpdates` for website trades. When off, traded players keep their old franchise role and prefix until a sync is run. |
| `/transactions tools processtrade <transaction_id> [roles]` | Manage Server | Recovery path. Fetches a transaction by ID, posts its trade card, and (by default) reapplies roles and nicknames for the traded players. Use it when a website trade was never announced. |
| `/transactions tools clearsublist` | Manage Server | Empties the bot's recorded sub list. The API is not touched. |
| `/transactions tools validatefutures <franchise>` | Manage Roles (default) | Asks the API to validate one franchise's future pick board and shows any violations. |
| `/transactions tools validatefuturesall [ping]` | Manage Roles (default) | Validates every franchise. With `ping`, posts violations to each failing franchise's `<franchise>-transactions` channel and pings its GM. |

## Configuration

Stored in a Red custom config group `Transactions`, keyed by guild ID (defaults in [transactions.py](../../rsc/transactions/transactions.py), type `TransactionSettings` in [types.py](../../rsc/types.py)):

| Key | Default | Set by | Used for |
| --- | --- | --- | --- |
| `TransChannel` | `None` | `/transactions transactionchannel` | Where cards, trade cards, draft lines and announcements are posted. |
| `TransLogChannel` | `None` | `/transactions logchannel` | Committee log (leave notices, "franchise channel not found" errors). |
| `TransRole` | `None` | `/transactions role` | Role pinged in the log channel. Committee posts are skipped if it is unset. |
| `TransNotifications` | `False` | `/transactions notifications` | Committee notice when a rostered player or GM leaves the server. |
| `TransGMNotifications` | `False` | `/transactions gmnotifications` | Franchise-channel notice to the GM when a rostered player or GM leaves. |
| `TransDMs` | `False` | `/transactions toggledm` | Whether the cut message is DMed. |
| `CutMessage` | `None` | `/transactions cutmsg` | Text of the cut DM. |
| `TradeAnnouncements` | `True` | `/transactions tools tradeannouncements` | Announce website trades. |
| `TradeRoleUpdates` | `True` | `/transactions tools traderoleupdates` | Reapply roles and nicknames for website trades. |
| `Substitutes` | `[]` | `/transactions sub` adds, `expire`, the expiry loop and `tools clearsublist` remove | Active temporary contracts (`date`, `player_in`, `player_out`, `team`, `gm`, `tier`, `franchise`). |
| `AnnouncedTrades` | `[]` | The website-trade handler | The last 200 announced transaction IDs, used to avoid announcing a trade twice. |
| `ContractExpirationMessage` | `None` | Nothing | Registered but never read or written. |

The module also relies on Discord roles found by name: "Subbed Out", "IR", "Captain", "Free Agent", "League", "General Manager", "Spectator", "Former Player", "Draft Eligible", each tier's role and `<Tier>FA` role, and franchise roles. Franchise transaction channels must be named `<franchise-name-lowercased-with-dashes>-transactions`.

## Background work

- **`expire_sub_contract_loop`** runs daily at 17:00 UTC (the code comment says noon Eastern, ignoring daylight saving). For each guild, every recorded sub dated yesterday or earlier in the guild timezone gets a CONTRACT EXPIRED card in the transactions channel (if one is set), is removed from `Substitutes`, and the starter loses "Subbed Out". It does not call the API. An error handler logs the crash and restarts the loop.
- **`on_raw_member_remove` listener (auto-retire):** when anyone leaves, the bot looks them up in the API. If they are a league player, it retires them with the bot as executor, `override=True` and the note "Player left the RSC discord server". It tries up to 3 times (waiting 2s, then 5s) on retryable failures (408, 425, 429, 5xx, transport errors). After a reply that does not verify, it reads the player back before retrying, so it never creates a duplicate retirement. An API answer that the player is already not playing counts as success. If retirement fails, or the guild is not set up yet, it posts "Automatic Retirement Failed" to the league events channel ([events](./events.md)), which tells staff to run `/admin retire departed`. On success, and only if the player had a team and their status was Rostered, Renewed, IR, AGM IR or Unsigned GM, it posts a leave notice (with kicker and reason from the audit log, if any) to the committee log channel if `TransNotifications` is on, and to the franchise's transactions channel pinging the GM if `TransGMNotifications` is on. Every log line from this flow starts with `auto-retire:`.
- **Website trades:** the [events](./events.md) poller dispatches each `PLAYER_TRADED` league event to `process_trade_event` in [trade_announce.py](../../rsc/transactions/trade_announce.py). It ignores events from other leagues and transactions that are not trades. It posts the trade card unless announcements are off, the ID is already in `AnnouncedTrades`, or the event is more than 6 hours old. It records the ID before posting, so a crash between the two can miss an announcement but never double-post one. Separately, if `TradeRoleUpdates` is on, it reapplies roles with a 0.5s pause between players. Parse failures, post failures and role errors are reported to the league events channel.
- **DMs:** the cut message is sent with `member.send` directly when `/transactions cut` runs with `announce` true, `TransDMs` on and a `CutMessage` set.
- **Cards** are Components V2 `LayoutView`s with `timeout=None`, but they have no buttons and are not registered as persistent views. Mentions are in `TextDisplay`s so they ping. `allowed_mentions` permits user pings only.

## How it works

- [transactions.py](../../rsc/transactions/transactions.py) holds the mixin: commands, the sub-expiry loop, the leave listener and auto-retire retry logic, the trade-text parser (`parse_trade_text` and the four regexes at the top), `build_transaction_card` / `build_contract_expired_card`, `announce_transaction`, `announce_to_transaction_committee`, `announce_to_franchise_transactions`, the API wrappers, and the config accessors.
- [roles.py](../../rsc/transactions/roles.py) is a set of module-level functions that bring a member's Discord roles and nickname in line with their API state: `update_signed_player_discord`, `update_cut_player_discord`, `update_team_captain_discord`, `update_nonplaying_discord`, and the status dispatcher `update_league_player_discord` with its per-status helpers. It also handles AGMs (`apply_agm_role_updates`: an AGM keeps exactly one franchise role, the one the API gives them). The [admin](./admin.md) sync, `/admin agm` and [members](./members.md) modules use these functions too. `update_league_player_discord` takes `agm_franchise` as a required keyword argument so a caller cannot forget it and strip an AGM's roles.
- [trade_announce.py](../../rsc/transactions/trade_announce.py) builds trade cards from a `TransactionResponse` and handles website-trade events (above). Players and picks are grouped by receiving franchise, then by giving franchise. Franchises are keyed by GM Discord ID, or by lowercased name when there is no GM, never by franchise ID. The franchise each player left is taken from hints passed in by `/transactions trade`, inferred when only two franchises are involved, or looked up from the old team.
- [views.py](../../rsc/transactions/views.py) defines `TradeAnnouncementModal`, `TransactionCard` (one player's move) and `TradeCard` (one container per receiving franchise). `TradeCard._plan` fits a trade to Discord's limits of 40 components and about 3,900 characters. It removes spacing first, then logos, then merges sections, then lists the last franchises on one line each, and finally cuts picks. Player lines are never cut, because they carry the pings. [admin/franchise.py](../../rsc/admin/franchise.py) reuses `TransactionCard`.
- [modals.py](../../rsc/transactions/modals.py) defines `CutMsgModal` and `TransactionAnnouncementModal`.

RSC API calls:

| Method | Endpoint call |
| --- | --- |
| `sign()` / `resign()` | `TransactionsApi.transactions_sign_create` / `transactions_resign_create` |
| `cut()` | `transactions_cut_create` |
| `substitution()` / `expire_sub()` | `transactions_substitution_create` / `transactions_expire_create` |
| `inactive_reserve()` | `transactions_inactive_reserve_create` (IR move/return and redshirt) |
| `retire()` | `transactions_retire_create` |
| `trade()` | `transactions_trade_create` |
| `validate_franchise_futures()` | `transactions_trade_validate_futures_create` |
| `draft()` | `transactions_draft_create` |
| `transaction_history()` / `paged_transaction_history()` / `transaction_history_by_id()` | `transactions_history_list` / `transactions_history_retrieve` |
| `set_captain()` | `LeaguePlayersApi.league_players_set_captain_create` |

`sign`, `cut` and `resign` pass API errors through `translate_api_error` ([exceptions.py](../../rsc/exceptions.py)), so the user sees a specific message. The other wrappers raise a plain `RscException`. The trade parser also uses `players()` from [members](./members.md) and `teams()` / `franchises()` from [teams](./teams.md) and [franchises](./franchises.md).

Each command sends the API call first and then makes the Discord changes. A failure in roles or announcing is reported to the person who ran the command, but the API move has already happened.

## Gotchas

- The "Subbed Out" and "IR" roles must exist. Their lookups raise if the role is missing, and they run after the API call. With "Subbed Out" missing, `/transactions sub` stops before announcing and before recording the sub, so it will never expire in Discord. With "IR" missing, `/transactions ir` stops after the API change.
- `/transactions notifications` replies "Transaction committee and GM notifications are now ..." but only toggles the committee setting. GM notifications have their own toggle, `gmnotifications`.
- The website-trade failure report tells staff to use `/transactions announce`. That command only posts free text. The command that re-announces a transaction by ID is `/transactions tools processtrade`.
- `/transactions trade` requires the transactions channel to be set even when `announce` is false.
- The sub-expiry loop removes subs only from the bot's own list and Discord roles. If a sub was never recorded (see above) or `clearsublist` was used, nobody gets the expiry card or role removal.
- `/transactions cut` computes Dev League eligibility from the person running the command, not the player being cut, and `update_cut_player_discord` ignores that flag anyway (the Dev League role code is commented out). Cuts never add the Dev League role.
- `/transactions captain` adds a player to the "updated" list even when its role sync raised `ValueError`. Its "not a league player" message names the first player argument rather than the player being skipped.
- `/transactions draft` decides between "drafted" and "kept" from the player's current nickname. It says "drafted" if the nickname starts with `FA |` or `DE |`.
- Trade text matching is strict. Player names must equal a League member's display name exactly, and GM names are prefix-matched against General Manager role members, so a short GM name can match the wrong person.
- Several error messages for sign, resign, sub, retire and draft say "Cut was processed but..." because the text was copied from cut. The move named in the command is the one that ran.
