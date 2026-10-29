# Operations

Running the bot day to day: where to look when something breaks, and how to fix the common cases.

## Logs

Red writes rotating logs to its data directory, under the instance's core data:

```
~/.local/share/Red-DiscordBot/data/<instance>/core/logs/
    latest.log       current run
    previous.log     the run before
    red-part*.log    rotated parts
```

Every cog line comes from a logger named `red.rsc.<module>` and starts with `[Guild Name]` when a guild is involved, so `grep '\[RSC 3v3\]'` or `grep red.rsc.transactions` narrows things quickly.

Change the level at runtime with `/rsc loglevel <level>` (bot owner only). It sets both `red.rsc` and `ballchasing`, and resets on restart. Starting Red with `--debug` sets DEBUG from the start.

At **DEBUG**, the [LLM assistant](modules/llm.md) logs each full OpenAI request, including the user's question, tool call arguments and tool results. That's the fastest way to see why an answer went wrong (grep `Original Question`, `'arguments':`, or `red.rsc.llm.usage`), but it means DEBUG logs contain member messages: treat them as sensitive and don't leave DEBUG on longer than needed.

## Health checks

| Check | How |
|---|---|
| Is the cog loaded? | `[p]cogs`, or run `/whatami` |
| Is a guild configured? | `/rsc settings` in that guild: API key, URL, league, ModMail bot, time zone |
| Did startup finish? | Log line `Finished preparing caches.` after each load or reconnect |
| Did a guild fail setup? | Log lines `Setup Error`, `Unhandled error preparing guild`, or `has no league configured`, prefixed with the guild name |
| Is the webhook server up? | `curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8008/league_player_update` on the host should print `501` |
| Is the events feed flowing? | See the [events](modules/events.md) page for its status command |

## Common problems

### Slash commands are missing or out of date

The commands weren't synced after a change. Run `[p]slash sync`. If a whole group is missing, check it's enabled with `[p]slash list` and `[p]slash enablecog RSC`. Members only see commands their permissions allow; server admins can also hide commands per role in Discord's Server Settings > Integrations.

### Every command in one server says the API isn't configured

That guild has no API URL, key or league. Run `/rsc settings` there, then set whatever is missing with `/rsc url`, `/rsc key`, `/rsc league` (bot owner only). Setting the key or URL rebuilds the API client immediately; the league caches fill on the next reload.

### Startup logs `401` / `403` from the RSC API

The guild's API key is wrong, expired or lacks permission for that league. Get a new key from the website admins and set it with `/rsc key`.

### Startup logs `502` / `504` / timeouts

The RSC API was down or slow while the bot started, so that guild's caches are empty and autocomplete returns nothing. Once the API is back, `[p]reload rsc` rebuilds them. API calls themselves retry server errors a few times before failing.

### A transaction says "Missing Roles"

The move needs a role that doesn't exist in this server, such as `Subbed Out` or `IR`. Nothing was changed in the API. Create the roles it names (`/admin sync requiredroles` creates most of the standard ones), then run the command again.

### `Unable to bind web app to localhost:8008`

Something else holds the port, most often a previous bot process that didn't exit. The bot keeps running without the Combines and Dev League webhooks. Find the process with `ss -ltnp 'sport = :8008'`, stop it, then `[p]reload rsc`.

### Combines or Dev League lobby channels didn't appear

- Check the feature is started in that guild (`/combinemanager settings` or the Dev League equivalent). The bot answers `503` while it's stopped.
- Check the website reached the bot: at DEBUG level the log shows `Received request to create ... games`. Nothing at all means the request never arrived (proxy or host problem).
- A lobby that finished on the website but is still up in Discord can be cleared with the manager's `teardown` command.

See [combines](modules/combines.md), [devleague](modules/devleague.md) and [lobbies](modules/lobbies.md).

### DMs are slow to arrive

All DMs go through one queue at about one every 1.5 seconds, so a large mass DM (activity checks, Intent to Play) takes a while, and Discord rate limits add retries. Time-sensitive DMs such as lobby details jump the queue. Members with DMs closed are recorded as failed rather than retried.

### Buttons on old messages stopped working

Persistent buttons (Intent to Play, activity check, PermFA poll, player card) keep working across restarts. Ordinary buttons time out with their view; ask the member to run the command again.

### A reload lost a DM batch

Expected: unloading discards the queue rather than draining it, so a reload doesn't stall for minutes. Avoid reloading during a large DM batch, or re-run the command that sent it.

## Routine tasks

| Task | How |
|---|---|
| Deploy a change | [Deployment: updating](deployment.md#updating) |
| Back up | [scripts/bot_backup.sh](../scripts/bot_backup.sh), see [Deployment: backups](deployment.md#backups) |
| Update the rulebook the assistant uses | [llm: rulebooks](modules/llm.md) |
| Add a new RSC server | Invite the bot, then configure it as in [Configuration](configuration.md) |
| Start of season | See the [staff guide](staff-guide.md#season-calendar) |
| Check data consistency | The validation scripts in [Scripts](scripts.md) |

## Getting the bot's attention in an emergency

- `[p]unload rsc` stops every RSC feature at once (loops, webhooks, DMs) while leaving Red online.
- `[p]shutdown` stops the bot entirely. If it runs under a supervisor configured to restart it, stop the service instead.
