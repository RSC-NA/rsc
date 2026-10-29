# Staff guide

What the bot does for each role in an RSC server, and which commands they use. This page is the quick version; each section links to the module page with the full command table, permissions and edge cases.

Run `/help` in Discord to see the commands available to you, or `/help <command>` for one command's options.

## Who can run what

Commands are gated three ways:

- **Discord permissions.** Most staff commands need **Manage Server**, some **Manage Roles**, **Manage Channels** or **Manage Messages**. Server admins can change who sees a command in Discord's Server Settings > Integrations.
- **RSC staff positions.** Some commands also let in members whom the RSC website lists in a staff position for this league (for example Numbers), even without the Discord permission.
- **Bot owner.** API credentials and a few dangerous settings are limited to the bot's operator.

## Players

| To… | Run | More |
|---|---|---|
| Sign up for the league | `/signup`: confirm match nights and rules, choose Draft Eligible or PermFA, add your in-game name and tracker links | [members](modules/members.md) |
| Sign up as a permanent free agent | `/permfa` | [members](modules/members.md) |
| Check your sign-up | `/signupstatus` | [members](modules/members.md) |
| Say whether you're returning next season | `/intent declare`, or the buttons in the Intent to Play DM | [members](modules/members.md), [admin](modules/admin.md) |
| See your player card | `/playerinfo` | [members](modules/members.md) |
| See tracker accounts | `/accounts` | [trackers](modules/trackers.md) |
| See your next match, lobby name and password | `/match` (or `/match day:<n>`) | [matches](modules/matches.md) |
| See a team's schedule | `/schedule` | [matches](modules/matches.md) |
| Report a match you played | `/reportmatch home away`: enter the wins and attach up to 10 `.replay` files | [ballchasing](modules/ballchasing.md) |
| Standings, playoff picture, stats | `/standings`, `/playoffs`, `/playerstats`, `/teamstats` | [stats](modules/stats.md) |
| Rosters and teams | `/roster`, `/teams`, `/captains`, `/franchises`, `/tiers` | [teams](modules/teams.md), [franchises](modules/franchises.md), [tiers](modules/tiers.md) |
| Season info and key dates | `/season`, `/dates`, `/leagues`, `/drafteligible` | [leagues](modules/leagues.md) |
| Ask about the rules | `/ask`, or mention the bot | [llm](modules/llm.md) |
| Answer an activity check | The button in `#inactivity-check` or the DM | [admin](modules/admin.md) |

## Free agents

On a match night, `/freeagent checkin` puts you on the availability board for your tier; `/freeagent checkout` takes you off. Check-ins clear themselves the next day. Only players with Free Agent, PermFA or Waivers status can check in. See [freeagents](modules/freeagents.md).

PermFAs may get a DM poll from admins asking whether they want to convert; answer with its buttons. See [admin: PermFA poll](modules/admin.md).

## GMs and AGMs

| To… | Run |
|---|---|
| Find a sub for tonight | `/freeagent availability <tier>` for who's checked in, `/freeagents <tier>` for every FA with MMR |
| See another team's next match | `/match team:<team>` (GMs and AGMs of either franchise in the match) |
| Report a match | `/reportmatch`, the same as players. AGMs can only report matches they play in |
| Check who's coming back | `/intent search` |

Transactions themselves (signings, cuts, trades) are processed by the transaction committee. You'll be pinged on the transaction card.

## Transaction committee

The `/transactions` group (Manage Roles by default) changes the API first, then updates the player's roles and nickname prefix, then posts a transaction card pinging the player and GM. See [transactions](modules/transactions.md).

| Move | Command |
|---|---|
| Sign, cut, re-sign | `/transactions sign`, `cut`, `resign` |
| Injured reserve | `/transactions ir` |
| Retire a player | `/transactions retire` |
| Redshirt | `/transactions redshirt` |
| Captain | `/transactions captain` |
| Draft pick | `/transactions draft` |
| Match-night sub | `/transactions sub`. The sub expires automatically the next day at 17:00 UTC; `expire` ends one early, `sublist` shows active subs |
| Trade | `/transactions trade` with the trade text pasted in. Website trades are announced automatically; `/transactions tools processtrade <id>` re-runs one that failed |
| Review | `/transactions history`, `leaderboard`, `tools validatefutures` |

If a league player leaves the server, the bot retires them automatically. If that fails, a report in the events channel asks staff to run `/admin retire departed`.

## Stats committee

- Match reports land in each tier's `<tier>-score-reporting` channel. The log channel set with `/ballchasing log` collects "Replay Upload Failures" to follow up on.
- Members with the ballchasing manager role (and admins) can report any match with `/reportmatch ... override:True`.
- See [ballchasing](modules/ballchasing.md).

## Numbers committee

`/numbers peaks` and `/numbers gamesplayed` look up a player's MMR history; `/trackers` manages tracker links (add, link, unlink, merge, delete, and review recent or stale ones). Most `/trackers` replies are public, so use a staff channel. See [numbers](modules/numbers.md) and [trackers](modules/trackers.md).

## Combines and Dev League

Both run lobbies that the Dev League website starts. When it does, the bot creates home and away voice channels, posts a LIVE card that pings the players with the lobby name, password and Join buttons, and DMs each player their details. When the match finishes, the card turns Final and the channels are deleted 30 seconds later. See [lobbies](modules/lobbies.md).

**Players**

| To… | Combines | Dev League |
|---|---|---|
| Check in / out | `/combines checkin`, `/combines checkout` (or on the website) | `/devleague checkin`, `/devleague checkout` |
| See your lobby again | `/combines lobbyinfo`, `/combines active` | `/devleague status` |
| Get or drop the interest ping role | | `/devleague optin`, `/devleague optout` |

**Admins** (Manage Server)

| Step | Combines | Dev League |
|---|---|---|
| Set up | Create a category, then `/combinemanager category` and `/combinemanager api <url>` | `/devleaguemanager category`, then `announcements` (without it there are no cards or DMs) |
| Turn on | `/combinemanager start` creates the combines channels and posts the guide. Needs roles named `League` and `Admin` | `/devleaguemanager enable` |
| Clear a stuck lobby | `/combinemanager teardown [lobby_id]` | `/devleaguemanager teardown [match_id]` |
| Turn off | `/combinemanager stop` ends every lobby and **deletes the whole combines category**; set the category again before the next `start` | `/devleaguemanager disable` ends open matches, keeps the category |

See [combines](modules/combines.md) and [devleague](modules/devleague.md).

## Ticket (ModMail) staff

In a ticket channel: `/assign <group>` moves it to that team's category and pings their role, `/unassign` sends it back, `/resolve` marks it resolved. `/llm summarize` (Manage Server) writes a private summary of a long ticket. See [moderator](modules/moderator.md) and [llm](modules/llm.md).

## Admins

### Setting up a server

The bot operator first connects the server to the RSC API with `/rsc url`, `/rsc key` and `/rsc league`. After that, admins configure each feature the server uses. Every setting is listed on the [Configuration](configuration.md) page; the usual order:

1. **Welcome:** `/welcome channel`, `message`, `roles`. These roles are also re-added by cuts and syncs. ([welcome](modules/welcome.md))
2. **Roles and tiers:** a Discord role named exactly like each tier, plus `<Tier>FA`. Then `/admin sync requiredroles`, `sync tiers`, `sync franchiseroles`, `sync transactionchannels`. ([admin](modules/admin.md), [tiers](modules/tiers.md))
3. **Transactions:** `/transactions transactionchannel`, `logchannel`, `role`, and the notification toggles. ([transactions](modules/transactions.md))
4. **Match reporting:** `/ballchasing key`, `toplevelgroup`, `category`, `log`, `manager`. ([ballchasing](modules/ballchasing.md))
5. **Events feed** (bot owner): `/rsc events channel`, then `/rsc events toggle`. Staff with Manage Server can check it with `/rsc events status`. ([events](modules/events.md))
6. **Rules assistant:** `/llm apikey`, then `/llm toggle`. ([llm](modules/llm.md))
7. **Tickets:** `/thread category`, `/thread role`, `/thread groups add`. ([moderator](modules/moderator.md))
8. **Numbers:** `/numbers role`. ([numbers](modules/numbers.md))
9. **Combines and Dev League:** see [above](#combines-and-dev-league).
10. **Dates text** for `/dates`: `/admin dates`.

### Season calendar

| When | What | Commands |
|---|---|---|
| Before the season | Sign-ups open on the website; players sign up in Discord | `/signup`, `/permfa`; fix records with `/admin members` |
| | Draft Eligible activity check | `/admin inactivecheck start`, then `role`, `ping`, `dm` to chase, `stop` to end |
| | Franchise changes | `/admin franchise ...`, `/admin agm add/remove` |
| | Roles and channels in step with the API | `/admin sync ...` |
| Draft | Record picks | `/transactions draft` |
| Every match night | FA check-ins, subs, match reports | `/freeagent checkin`, `/transactions sub`, `/reportmatch` |
| During the season | Signings, cuts, trades, IR | `/transactions ...` |
| | Players who left the server | Daily audit report in the events channel; `/admin retire departed` |
| End of the season | Intent to Play for next season | `/admin intents populate`, `ping` or `dm`; track with `/admin stats intents` |
| | PermFA conversion poll | `/admin permfa poll`, `responses`, `close` |

### Mass DMs

Everything the bot DMs goes through one queue at about one message every 1.5 seconds, so a DM to a whole tier takes minutes. `/admin dmstatus` shows progress and `/admin dmcancel` stops it. Don't reload the bot during a large batch: queued DMs are dropped.
