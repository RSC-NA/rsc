# Modules

Each feature lives in its own package under [rsc/](../../rsc/) and adds one or more mixins to the `RSC` cog (see [Architecture](../architecture.md)). Every page follows the same layout: what the module does, how staff use it, its commands with who can run them, its settings, background work, how it works inside, and gotchas.

## League operations

| Module | What it does | Main commands |
|---|---|---|
| [admin](admin.md) | Staff tooling: role and channel sync, franchise changes, member fixes, Intent to Play, activity checks, PermFA polls, departed-player audit, mass DMs | `/admin ...` |
| [transactions](transactions.md) | Signings, cuts, re-signs, IR, retirements, subs, trades, draft picks, with roles and nicknames kept in step | `/transactions ...` |
| [members](members.md) | Sign-up, PermFA requests, Intent to Play, player cards, waivers | `/signup`, `/permfa`, `/intent`, `/playerinfo` |
| [freeagents](freeagents.md) | Free agent lists and the match-night availability board | `/freeagent ...`, `/freeagents` |
| [franchises](franchises.md) | Franchise listing and the franchise API helpers admin uses | `/franchises` |
| [teams](teams.md) | Rosters, teams and captains | `/roster`, `/teams`, `/captains` |
| [tiers](tiers.md) | Tier listing and tier cache | `/tiers` |
| [leagues](leagues.md) | League and season info, key dates, draft eligibility | `/season`, `/dates`, `/leagues`, `/drafteligible` |
| [seasons](seasons.md) | Season lookups and the season number ↔ ID cache (no commands) | |

## Matches and stats

| Module | What it does | Main commands |
|---|---|---|
| [matches](matches.md) | Next match, lobby details, schedules | `/match`, `/schedule` |
| [ballchasing](ballchasing.md) | Match reporting with replay upload to ballchasing.com | `/reportmatch`, `/ballchasing ...` |
| [stats](stats.md) | Standings, playoff picture, player and team stats | `/standings`, `/playoffs`, `/playerstats`, `/teamstats` |
| [trackers](trackers.md) | Rocket League tracker links for the Numbers committee | `/accounts`, `/trackers ...` |
| [numbers](numbers.md) | MMR peaks and games played lookups | `/numbers ...` |

## Combines and Dev League

| Module | What it does | Main commands |
|---|---|---|
| [combines](combines.md) | Combines check-in, channels and lobby announcements | `/combines ...`, `/combinemanager ...` |
| [devleague](devleague.md) | Dev League check-in, interest role and lobby announcements | `/devleague ...`, `/devleaguemanager ...` |
| [lobbies](lobbies.md) | The shared lobby engine behind both: webhooks, voice channels, LIVE/Final cards, lobby DMs | — |

## Server and community

| Module | What it does | Main commands |
|---|---|---|
| [events](events.md) | Mirrors the RSC website's event feed into a log channel and dispatches events to other modules | `/rsc events ...` |
| [llm](llm.md) | The rules assistant and ticket summaries, backed by OpenAI | `/ask`, `/llm ...` |
| [welcome](welcome.md) | Welcome message and default roles for new members | `/welcome ...` |
| [moderator](moderator.md) | ModMail ticket routing (moderation commands are stubs) | `/assign`, `/unassign`, `/resolve`, `/thread ...` |
| [utils](utils.md) | Shared helpers (DM queue, caches, images) plus ID, role and accolade commands | `/getid`, `/addrole`, `/accolades ...` |
| [extras](extras.md) | Fun commands | `/8ball`, `/roll`, `/rps` |
| [developer](developer.md) | Log tail and a test command for the operator | `/logs tail`, `/devtest` |

The core settings and `/help` live in the cog itself; see [Configuration](../configuration.md) and [Architecture](../architecture.md).

## Keeping these pages current

When you change a module's commands, permissions, settings or background work, update its page here and its package `README.md` in the same change. The project skill in `.claude/skills/update-module-docs/` walks through which sections each kind of change touches.
