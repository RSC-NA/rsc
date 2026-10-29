# Configuration

Everything the bot needs set up in a server, in one place. All settings are **per server** (guild) and stored in Red's `Config`, so they survive restarts and updates. The bot itself reads no environment variables in production; secrets are set with commands.

Each table lists the settings an admin sets. Keys the bot writes for its own bookkeeping (cursors, usage counters, open lobbies) are listed at the end. The module pages have the full detail.

## 1. Connect the server to the RSC API

Only the bot owner can run these. Without them, nothing league-related works in that server.

| Setting | Key | Command |
|---|---|---|
| API URL, e.g. `https://api.rscna.com/api/v1` | `ApiUrl` | `/rsc url` |
| API key | `ApiKey` | `/rsc key` |
| Both at once, in a form | | `/rsc setup` |
| Which RSC league this server is | `League` | `/rsc league` (pick from a list) |
| Server time zone, used for match days, DM schedules and daily caps | `TimeZone` (default `UTC`) | `/rsc timezone` |
| ModMail bot players are pointed to | `ModmailBot` (default is RSC's ModMail bot) | `/rsc modmailbot` |

Check them with `/rsc settings`. Changing the URL or key rebuilds the API connection immediately; tier, franchise and team caches fill on the next reload.

## 2. Discord roles and channels the bot expects

Several features find roles by their exact name. Create these before turning features on:

| Role | Used by |
|---|---|
| `League` | Everyone in the league; lobby voice access; transactions |
| `General Manager`, `Assistant GM`, `Captain` | Transactions, sync |
| `Free Agent`, `PermFA`, `PermFA in Waiting`, `Draft Eligible`, `Spectator` | Sign-up, transactions, sync |
| `Former Player`, `Former GM`, `Former Staff`, `Former Admin` | Retirements, sync |
| `Subbed Out`, `IR` | Subs and injured reserve |
| `Admin` | Combines `start`; the ceiling for the bot's role commands |
| `Muted` | Optional, Combines lobby channels |
| `Dev League Interest` | Dev League opt-in |
| One per tier, named exactly like the tier, plus `<Tier>FA` | Tiers, transactions, `/tiers` |
| One per franchise | Created by `/admin sync franchiseroles` |

Transaction commands check that the roles a move changes exist before they call the API, and refuse with the missing names if not, so a missing role never leaves a move half done. The names are constants in [rsc/const.py](../rsc/const.py). `/admin sync requiredroles` creates most of them; it does not create `Draft Eligible`, `Former GM`, `Admin`, `Dev League Interest`, or the tier roles (use `/admin sync tiers` for those).

Each franchise also needs a `<franchise-name>-transactions` channel (lowercase, dashes); `/admin sync transactionchannels` creates them.

## 3. Feature settings

### Welcome — [welcome](modules/welcome.md)

| Key | Default | Command |
|---|---|---|
| `WelcomeChannel` | none | `/welcome channel` |
| `WelcomeMsg` | none | `/welcome message` (`{member.mention}` is replaced) |
| `WelcomeRoles` | `[]` | `/welcome roles`, up to 4. Also re-added by cuts and syncs as the default roles |
| `WelcomeStatus` | `True` | `/welcome toggle`. Turns the message on or off; new members get the roles either way |

### Transactions — [transactions](modules/transactions.md)

| Key | Default | Command |
|---|---|---|
| `TransChannel` | none | `/transactions transactionchannel` |
| `TransLogChannel` | none | `/transactions logchannel` |
| `TransRole` | none | `/transactions role`. Committee log posts are skipped if unset |
| `TransNotifications` | `False` | `/transactions notifications` |
| `TransGMNotifications` | `False` | `/transactions gmnotifications` |
| `TransDMs` | `False` | `/transactions toggledm` |
| `CutMessage` | none | `/transactions cutmsg` |
| `TradeAnnouncements` | `True` | `/transactions tools tradeannouncements` |
| `TradeRoleUpdates` | `True` | `/transactions tools traderoleupdates` |

### Admin — [admin](modules/admin.md)

| Key | Default | Command |
|---|---|---|
| `Dates` | none | `/admin dates` (shown by `/dates`, read by the rules assistant) |
| `AgmMessage` | none | `/admin agm message` |
| `IntentChannel`, `IntentMissingRole`, `IntentMissingMsg` | none | `/admin intents missingchannel`, `missingrole`, `missingmsg` |
| `ActivityCheckMissingRole` | none | `/admin inactivecheck role` |
| `RetireAuditEnabled` | `True` | `/admin retire audit` |

### Match reporting (ballchasing) — [ballchasing](modules/ballchasing.md)

| Key | Default | Command |
|---|---|---|
| `AuthToken` | none | `/ballchasing key`. Checked with ballchasing before saving, and takes effect immediately |
| `TopLevelGroup` | none | `/ballchasing toplevelgroup` |
| `ReportCategory` | none | `/ballchasing category` (holds the `<tier>-score-reporting` channels) |
| `LogChannel` | none | `/ballchasing log` |
| `ManagerRole` | none | `/ballchasing manager` |

### Events feed — [events](modules/events.md)

Setup commands are bot owner only.

| Key | Default | Command |
|---|---|---|
| `EventChannel` | none | `/rsc events channel` |
| `EventsEnabled` | `False` | `/rsc events toggle` |
| `EventInterval` | `60` s (30–3600) | `/rsc events interval` |
| `IncludePrivate` | `False` | `/rsc events private` |
| `IncludeGlobal` | `True` | `/rsc events global` |
| `CategoryFilter`, `ActionFilter`, `SeverityFilter` | `[]` | `/rsc events filter` |

### Rules assistant (LLM) — [llm](modules/llm.md)

| Key | Default | Command |
|---|---|---|
| `OpenAIKey` | none | `/llm apikey` |
| `OpenAIOrg` | none | `/llm organization` (needed for `/llm summarize`) |
| `LLMActive` | `False` | `/llm toggle` |
| `LLMUserCooldown` | `20` s | `/llm cooldown` |
| `LLMUserDailyCap`, `LLMGuildDailyCap` | `15`, `400` | `/llm dailycap` |
| `LLMBlacklist` | none | `/llm blacklist add`, `rm` (channels the assistant ignores) |
| `LLMPublicAsk` | `True` | No command |

Models and token limits are code constants in [rsc/llm/config.py](../rsc/llm/config.py).

### Combines — [combines](modules/combines.md)

| Key | Default | Command |
|---|---|---|
| `CombinesCategory` | none | `/combinemanager category`. `stop` keeps it. If the category is deleted, `start` and `settings` say so |
| `CombinesApi` | none | `/combinemanager api`, e.g. `https://devleague.rscna.com/c-api/` |
| `Active` | `False` | `/combinemanager start`, `stop` |

### Dev League — [devleague](modules/devleague.md)

| Key | Default | Command |
|---|---|---|
| `DevLeagueCategory` | none | `/devleaguemanager category` |
| `DevLeagueAnnounceChannel` | none | `/devleaguemanager announcements`. Without it there are no lobby cards or DMs |
| `Active` | `False` | `/devleaguemanager enable`, `disable` |

The Dev League API URL is fixed in code (`https://devleague.rscna.com`).

### Tickets — [moderator](modules/moderator.md)

| Key | Default | Command |
|---|---|---|
| `PrimaryCategory` | none | `/thread category` |
| `ManagementRole` | none | `/thread role` |
| `Groups` | `{}` | `/thread groups add`, `rm` (name → category and role) |

### Numbers — [numbers](modules/numbers.md)

| Key | Default | Command |
|---|---|---|
| `NumbersRole` | none | `/numbers role` |

### Modules with no settings

[franchises](modules/franchises.md), [freeagents](modules/freeagents.md), [teams](modules/teams.md), [tiers](modules/tiers.md), [members](modules/members.md), [trackers](modules/trackers.md), [matches](modules/matches.md), [stats](modules/stats.md), [seasons](modules/seasons.md), [leagues](modules/leagues.md), [extras](modules/extras.md), [developer](modules/developer.md), [utils](modules/utils.md) and [lobbies](modules/lobbies.md) store nothing an admin sets. They depend on the API connection, the roles above, and the time zone.

## 4. State the bot keeps for itself

Don't edit these by hand; they're listed so you know what a backup contains.

| Group | Keys | What |
|---|---|---|
| `Admin` | `IntentDmLast*`, `ActivityCheckDmLast*`, `ActivityCheckMsgId` | Last mass-DM runs; the running activity check |
| `PermFAPoll` (guild, tier) | one record per tier | Open and past PermFA polls and their recipients |
| `Transactions` | `Substitutes`, `AnnouncedTrades` | Active sub contracts; trades already announced |
| `FreeAgents` | `CheckIns` | Match-night availability board |
| `Events` | `ConfirmedId`, `ConfirmedCreatedAt`, `SeenIds`, `TotalProcessed` | The poller's cursor. `/rsc events cursor` moves it |
| `Combines`, `DevLeague` | `LobbyMessages` | Open lobbies' cards and DM message IDs |
| `DevLeague` | `DevLeagueRoleUsers` | Members who opted in or out of the interest role |
| `LLMUsage` (guild, user) | `day`, `count`, `tokens` | Daily question and token counts per member; user `0` is the server total |

## Development and test settings

Tests and scripts read a `.env` file instead. See [Development: .env](development.md#env).
