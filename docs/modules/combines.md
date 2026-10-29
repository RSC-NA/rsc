# Combines

**Package:** [rsc/combines/](../../rsc/combines/) · **Mixin(s):** `CombineMixIn`, `CombineManagerMixIn` · **Details:** [package README](../../rsc/combines/README.md)

Combines are the off-season games where new and returning players are seen by the Numbers Committee before the draft. Players check in on the Dev League website (devleague.rscna.com), and the website's combines system builds balanced series in batches. This module is the Discord side of that: it lets players check in and out from Discord, sets up the combines channels for the night, and when the website starts a lobby it creates a home and an away voice channel, posts a live lobby card that pings every player in it, and DMs each player their copy. When the match finishes the card turns Final with the series score and the voice channels are deleted.

The matchmaking itself happens on the website. The bot never decides who plays whom. It reacts to two webhooks the website sends to a small web server inside the bot. The webhook handling is shared with [Dev League](./devleague.md) and lives in [lobbies](./lobbies.md).

## Using it

**Admins, before a combines night**

1. Create a category for combines and run `/combinemanager category` with it.
2. Run `/combinemanager api` with the combines API base URL (for example `https://devleague.rscna.com/c-api/`).
3. Run `/combinemanager start`. The bot creates the combines channels in the category (skipping any that already exist), posts the how-to-play guide and the help messages, and turns combines on. Until this is done the website's lobby webhooks are refused.
4. Check everything with `/combinemanager settings`.

**Players, during the night**

1. Log in at devleague.rscna.com with Discord and check in, either on the site or with `/combines checkin`. Check-in has to be repeated for every series.
2. Wait in `#combines-announcements`. When your lobby starts, the bot posts a LIVE card that pings you, with the lobby name and password, both rosters, and Join buttons for the Home and Away voice channels. You also get a DM copy that says which team you are on, and whether you make the lobby (first Home player) or upload replays (Away team).
3. Lost the details? Run `/combines lobbyinfo`.
4. Home hosts and reports the score on the site, Away uploads replays and confirms. When the website marks the match finished, the card (channel post and DMs) turns Final with the score, and the voice channels are deleted 30 seconds later.
5. Leave the queue with `/combines checkout`.

If the website is down or slow, the `/combines` commands wait up to 10 seconds and then answer privately with "Couldn't reach the combines website. Try again in a moment."

**Admins, after the night**

- Run `/combinemanager stop`. It turns combines off, ends every open lobby (cards go Final, channels deleted), then deletes the combines category, every channel in it, and the overflow categories `<category>-2` to `<category>-4`.
- If a lobby finished on the website but its card or channels are still up in Discord (for example the bot restarted during the 30 second grace period), run `/combinemanager teardown <lobby_id>`, or with no ID to end every open lobby.

## Commands

**`/combines`** (players)

| Command | Who can run it | What it does |
|---|---|---|
| `/combines checkin` | anyone, while combines are started and the API is set | Checks you in for a combines match through the combines API. |
| `/combines checkout` | anyone, while combines are started and the API is set | Checks you out through the combines API. |
| `/combines lobbyinfo [lobby_id]` | anyone, while combines are started and the API is set | Shows your active lobby's name, password and your team (Home/Blue or Away/Orange). With `lobby_id`, looks up that lobby. |
| `/combines active [player] [tier]` | anyone, when the API is set (combines need not be started) | Lists active (not completed, not cancelled) lobbies that include `player` (you by default), optionally only those whose tier matches `tier`. |

Every `/combines` reply is private. Each command defers before it calls the combines API, so Discord shows "thinking" while the bot waits. A failure to reach the site (no connection, more than 10 seconds, a 5xx, or a reply that isn't JSON or isn't the expected shape) gets one private red reply: "Couldn't reach the combines website. Try again in a moment." An error the site answers with is shown in red with the site's own text.

**`/combinemanager`** (staff)

| Command | Who can run it | What it does |
|---|---|---|
| `/combinemanager settings` | Manage Server | Shows whether combines are active, the API URL and the category. |
| `/combinemanager category <category>` | Manage Server | Sets the category combines channels are created in. |
| `/combinemanager api <url>` | Manage Server | Sets the combines API base URL. |
| `/combinemanager start` | Manage Server | Creates the combines channels, posts the guide and help messages, and marks combines active. Needs the API URL, the category, and roles named `League` and `Admin`. Refuses if already active. |
| `/combinemanager stop` | Manage Server | Marks combines inactive, ends every open lobby without the grace period, then deletes the combines category and its overflow categories with all their channels. |
| `/combinemanager teardown [lobby_id]` | Manage Server | Ends one lobby (or every open lobby) now: card and DMs go Final, voice channels deleted. Errors if the lobby has no live card or channels. |
| `/combinemanager guide [channel] [overwrite]` | Manage Server | Posts the how-to-play guide card in `channel`, or in `#how-to-play` in the combines category. If the bot's guide is already in the last 100 messages there, links it instead; with `overwrite`, edits it in place. |

"Manage Server" is the group's `default_permissions`, so server admins can change who sees these commands in Discord's Integrations settings.

Every `/combinemanager` reply is private; only the guide card itself is posted publicly. `stop` and `teardown` reply green, or orange with the IDs that could not be ended (usually missing permissions).

## Configuration

Stored in the Red Config custom group `Combines`, keyed by guild ID.

| Key | Default | Set by |
|---|---|---|
| `Active` | `False` | `/combinemanager start` (True), `/combinemanager stop` (False) |
| `CombinesApi` | `None` | `/combinemanager api` |
| `CombinesCategory` | `None` (a category ID) | `/combinemanager category` |
| `LobbyMessages` | `{}` | Written by the lobby runner: lobby ID to the card and its message IDs, kept until teardown. See [lobbies](./lobbies.md). |

The module also relies on roles found by name: `League` (players who may join lobby voice channels), `Admin` (must exist for `start`), and optionally `Muted` (can see lobby channels but not connect or speak).

## Background work

- **Webhooks.** The bot's web server listens on `localhost:8008` (started in [rsc/core.py](../../rsc/core.py)). Combines uses two routes:

  | Route | Payload | What happens |
  |---|---|---|
  | `POST /combines_match` | JSON object of lobbies keyed by lobby ID, each a `CombinesLobby` (`id`, `lobby_user`, `lobby_pass`, `home_wins`, `away_wins`, `completed`, `cancelled`, `tier`, `guild_id`, `home` and `away` player lists) | Replies 200 straight away, then creates each lobby's voice channels and posts its card in the background. |
  | `POST /combines_event` | A `CombineEvent` (`actor`, `status`, `message_type`, `message`, `match_id`, `guild_id`) | Only `message_type: "Finished Game"` does anything: the lobby's card and DMs go Final at once and its channels are deleted 30 seconds later. |

  Responses: `400` for bad JSON, a payload that does not validate, an empty batch, or a finished event with no `match_id`; `503` if the bot is not in the guild, or (match route only) combines are not active in that guild; `501` for any other event type; `200` otherwise. Full detail in [lobbies](./lobbies.md).
- **Channels created by `start`:** `how-to-play` and `combines-announcements` (read-only for everyone and the League role), `combines-help` (help messages posted when created), `combines-general` (League can chat, 5 second slowmode), and voice channels `combines-waiting-room-1` and `combines-waiting-room-2`.
- **Lobby voice channels** are named `<tier>-<lobby id>-home` and `<tier>-<lobby id>-away` with the tier exactly as the API sends it (for example `veteran-81-home`), capped at 5 users. Everyone can see them; only the League role can connect and speak; the Muted role, if it exists, can see but not connect.
- **Lobby card** is posted in the channel named `combines-announcements` and pings the players listed on it. Each player in the server also gets an urgent DM copy through the bot's shared DM queue (see [utils](./utils.md)).
- **Persistent button.** The guide's "Where are my replays?" button (`ReplayLocationButton`) is a dynamic item registered on the bot at setup, so it keeps working on guides posted long ago. It replies privately with the Windows replay folder path.
- **Animated LIVE dot.** The card title uses the bot's `live` application emoji when available (uploaded at startup by [rsc/core.py](../../rsc/core.py)); without it the title just says LIVE.

## How it works

- [combines.py](../../rsc/combines/combines.py): `CombineMixIn` and the `/combines` player commands. The `active_combines` decorator blocks `checkin`, `checkout` and `lobbyinfo` unless combines are active and the API URL is set. `combine_players_from_lobby` resolves a lobby's players to guild members and is also used by the shared runner.
- [manager.py](../../rsc/combines/manager.py): `CombineManagerMixIn`, the `/combinemanager` commands, Config registration and getters/setters, channel creation for `start`, and category deletion for `stop`. `stop` ends open lobbies with the shared runner's `end_now`; `teardown`'s body and the "Ended ..." reply lines come from [rsc/lobbies/commands.py](../../rsc/lobbies/commands.py). `guide` finds an already posted guide with `is_combines_guide`.
- [api.py](../../rsc/combines/api.py): calls to the combines API. Each sends `discord_id` and `guild_id` as query parameters to `<api>/check_in`, `<api>/check_out`, `<api>/active` and `<api>/lobby/[<id>]` through the shared request helper in [rsc/lobbies/api.py](../../rsc/lobbies/api.py), which has a 10 second timeout and turns every failure into `SiteUnavailable`. A reply with `status` and `message` is treated as a status message; anything else is parsed as lobbies.
- [models.py](../../rsc/combines/models.py): pydantic models for the webhook and API payloads (`CombinesLobby`, `CombinesPlayer`, `CombineEvent`, `CombineEventType`, `CombinesStatus`). Player `discord_id` and `name` may be null because the API fills them from a LEFT JOIN.
- [runner.py](../../rsc/combines/runner.py): `CombinesLeague`, the combines settings for the shared [`LobbyRunner`](./lobbies.md). It supplies the Config group, the `combines-announcements` channel, channel names, the match link (`https://devleague.rscna.com/combine/<id>`), the Muted overwrite, and `final_score`, which reads the series score from `<api>/lobby/<id>` as one of the lobby's players. If the site can't answer, the card goes Final without a score.
- [lobby.py](../../rsc/combines/lobby.py) and [views.py](../../rsc/combines/views.py): the lobby card and its storage, shared with Dev League despite living here. `views.py` builds the Components V2 card (`LobbyCard.render`, live or Final, with an optional per-player line). `lobby.py` posts it, queues the DMs, records each sent DM's message ID in `LobbyMessages`, and redraws everything as Final on teardown.
- [guide.py](../../rsc/combines/guide.py): the how-to-play guide card with four screenshots from `rsc/resources/combines/` and a section on sending Numbers Reports from the match page, the persistent replays button, `is_combines_guide` (recognises a posted guide by that button), and lookups that turn `/combines checkin`, `checkout` and `lobbyinfo` into clickable command mentions when they are synced.

Flow for one lobby: the website posts to `/combines_match` → `LobbyRunner.start_game` validates and replies → `create_channels` makes the two voice channels (in an overflow category if the main one has more than 40 channels) → `post_lobby` sends the card, saves it under `LobbyMessages`, and queues one urgent DM per player. When the website posts `Finished Game` to `/combines_event`, `LobbyRunner.teardown` turns the card and DMs Final with the score, waits 30 seconds, and deletes every voice channel for that lobby ID in the category and its overflow categories.

External services: the combines API at the configured URL (part of the Dev League site). The RSC website API (`rscapi`) is not used by this module, apart from the tier list behind `/combines active`'s tier autocomplete.

## Gotchas

- `/combinemanager stop` deletes the configured category itself. The saved category ID then points at nothing, so the next `start` fails with "category channel has not been configured" until you create a new category and run `/combinemanager category` again.
- The webhook server only binds to `localhost:8008` and the routes have no authentication. The website (or a proxy) must reach the bot on the same host. If the port is taken the bot logs an error and the webhooks are dead until the next reload.
- `/combines_match` answers 200 before any channel exists. Channel creation failures only show up in the bot log.
- If the bot restarts during the 30 second grace period, the voice channels are never deleted. Use `/combinemanager teardown`.
- The lobby card is only posted if a channel named `combines-announcements` exists somewhere in the server. Without it the voice channels are still created, but there is no card and no DMs.
- Players who are not in the server, or whose Discord ID the API does not know, are shown by name on the card and get no DM. A lobby with no players in the server is skipped entirely.
- `/combines active` always filters to one player (you, if `player` is left empty), so there is no way to list every active lobby.
- If the site has active lobbies but none of them match `player` and `tier`, `/combines active` builds an embed with empty fields, which Discord rejects, so the command fails instead of saying there are none.
- `/combinemanager start` raises an unhandled error, rather than its "League role does not exist" message, when there is no `League` role.
