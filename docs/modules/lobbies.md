# Lobbies

**Package:** [rsc/lobbies/](../../rsc/lobbies/) · **Mixin(s):** none (used by `CombineMixIn` and `DevLeagueMixIn`)

This is the shared engine behind [combines](./combines.md) and [Dev League](./devleague.md) game channels. Both websites tell the bot the same two things: "these lobbies are starting" and "this match is finished". `LobbyRunner` answers both webhooks once, for either system: it creates each lobby's home and away voice channels, posts the live lobby card and DMs every player, and on finish turns the card Final and deletes the channels. Each system plugs in a small `LobbyLeague` subclass with only what differs (settings, channel names, match link, a few extras).

Staff never use this module directly. Its effects show up through `/combinemanager` and `/devleaguemanager`.

## Using it

There is nothing to run here. What staff see:

- A lobby starts on the website → two voice channels appear in the configured category and a LIVE card is posted and DMed to each player.
- A match finishes on the website → the card and DMs turn Final right away, and the voice channels disappear 30 seconds later.
- Something is stuck → `/combinemanager teardown` or `/devleaguemanager teardown` (both use this module's shared command body) ends it now. Turning the system off (`/combinemanager stop`, `/devleaguemanager disable`) ends every open lobby the same way.
- The website is down or slow → the player commands that call it (`/combines checkin`, `checkout`, `lobbyinfo`, `active`, and `/devleague status`, `checkin`, `checkout`) wait up to 10 seconds, then answer privately with "Couldn't reach the combines website. Try again in a moment." (or the same for the Dev League website). The bot logs a warning, not a traceback.

## Commands

This package defines no commands of its own. [commands.py](../../rsc/lobbies/commands.py) holds the shared body of the two teardown commands:

| Command | Who can run it | What it does |
|---|---|---|
| `/combinemanager teardown [lobby_id]` | Manage Server | Ends one open combine lobby, or all of them, without the 30 second grace period. |
| `/devleaguemanager teardown [match_id]` | Manage Server | The same for Dev League matches. |

A lobby counts as open if it still has a saved card in `LobbyMessages` or a voice channel named for it in the category or its overflow categories. Asking for an ID that is neither, or running it with no ID when nothing is open, gives an error. Replies are private. The reply lists what was ended and which IDs failed (usually missing permissions), green if all ended and orange otherwise.

## Configuration

None of its own. The runner reads and writes each system's `LobbyMessages` key (in the `Combines` or `DevLeague` Config group) and reads that system's active flag, category and announcement channel through its `LobbyLeague`. See the [combines](./combines.md#configuration) and [Dev League](./devleague.md#configuration) pages.

## Background work

**Web server and routes.** [rsc/core.py](../../rsc/core.py) `start_webapp()` builds one aiohttp application and binds it to `localhost:8008`:

| Route | Handler |
|---|---|
| `POST /combines_match` | combines `LobbyRunner.start_game` |
| `POST /combines_event` | combines `LobbyRunner.handle_event` |
| `POST /devleague_match` | Dev League `LobbyRunner.start_game` |
| `POST /devleague_event` | Dev League `LobbyRunner.handle_event` |
| `POST /league_player_update` | `league_player_update_handler` in [leagues](./leagues.md) (returns 501) |

The server starts once in `setup()` (re-running on reconnect is a no-op) and is cleaned up in `cog_unload()`. If the port cannot be bound the bot logs "Unable to bind web app to localhost:8008" and carries on without webhooks.

**`start_game` (match route).**

1. Body must be a JSON object of lobbies keyed by ID; each value is parsed as a `CombinesLobby`. Bad JSON, a non-object, a lobby that fails validation, or no lobbies → `400`.
2. For each distinct `guild_id` in the batch: bot not in that guild, or the system not active there → `503`.
3. Otherwise reply `200` immediately and create the lobbies in a background task, one at a time, so a slow Discord rate limit cannot make the website time out and retry into duplicates.

**`handle_event` (event route).** Body parsed as a `CombineEvent`. Bad JSON or validation failure → `400`; bot not in the guild → `503`; `message_type` other than `"Finished Game"` → `501`; no `match_id` → `400`. Otherwise reply `200` and tear the lobby down in a background task. It does not check whether the system is active; switching a system off already ends every open lobby, so a late finished event finds nothing left to end.

**Creating one lobby** (`create_channels`). Skips the lobby, logging why, if: the system was turned off meanwhile, no category is set, a channel with either name already exists, none of the players are in the server, or there is no `League` role. Otherwise it picks the target category (the configured one, or the first overflow category `<name>-2` to `<name>-4` with room, creating it if needed, once the configured one has more than 40 channels), creates the two voice channels (user limit 5; everyone can view; League can connect, speak, stream and chat; plus the system's extra overwrites), lets the system reposition them, then posts the card if the system has an announcement channel.

**Card and DMs** ([rsc/combines/lobby.py](../../rsc/combines/lobby.py)). The card is sent with mentions limited to users, so every player named on it is pinged. The card and its message IDs are saved under `LobbyMessages[<lobby id>]`. Each player in the server is then queued an urgent DM through the shared DM queue, with a line saying their team and whether they make the lobby. A precheck drops any DM still queued when the match has already ended. Each DM that is sent has its message ID appended to the saved entry; one sent after teardown already ran is edited to Final on the spot.

**Teardown** (`teardown`). Removes the lobby from the in-memory active set, loads its saved entry, asks the system for a final score, and redraws the channel post and every DM as Final (then forgets the entry). Then, after a 30 second sleep unless called with `delay=False`, deletes every voice channel in the category and overflow categories whose name parses to that lobby ID. `end_now` runs teardown with no delay for a list of IDs and returns the ones that failed.

## How it works

- [runner.py](../../rsc/lobbies/runner.py): `LobbyLeague` (abstract: `store`, `active`, `category`, `announce_channel`, `channel_name`, `match_url`; optional `extra_overwrites`, `place`, `final_score`) and `LobbyRunner` (webhook handlers, creation, overflow categories, announce, teardown, `open_lobbies`, `end_now`).
- [channels.py](../../rsc/lobbies/channels.py): the `<tier>-<id>-<home|away>` channel name format, `parse_lobby_channel` and `is_lobby_channel`. Teardown finds channels by parsing names, comparing the ID as a number so lobby 1 never matches lobby 101.
- [commands.py](../../rsc/lobbies/commands.py): slash command bodies shared by combines and Dev League. `teardown_command` is the whole body of `/combinemanager teardown` and `/devleaguemanager teardown`: it checks the ID against `open_lobbies`, defers, runs `end_now` and replies. `ended_lines` builds the "Ended ..." and "Unable to end ..." lines, which `/combinemanager stop` and `/devleaguemanager disable` also use, worded with each league's `noun` and `nouns` ("lobby"/"lobbies" or "match"/"matches").
- [api.py](../../rsc/lobbies/api.py): `get_json`, the one request helper both API clients ([rsc/combines/api.py](../../rsc/combines/api.py) and [rsc/devleague/api.py](../../rsc/devleague/api.py)) go through. It makes a GET with proxy environment variables honoured and a 10 second total timeout, then parses the JSON reply with the caller's parser. Every failure (no connection, a timeout, a 5xx, a reply that isn't JSON, or one the parser rejects) is raised as `SiteUnavailable` from [rsc/exceptions.py](../../rsc/exceptions.py). `json_object` rejects a reply that isn't a JSON object. The player commands catch `SiteUnavailable`, log a warning and send the private "couldn't reach the website" reply; combines' `final_score` catches it and leaves the score off the Final card.

The two implementations:

| | Combines (`CombinesLeague`, [rsc/combines/runner.py](../../rsc/combines/runner.py)) | Dev League (`DevLeague`, [rsc/devleague/runner.py](../../rsc/devleague/runner.py)) |
|---|---|---|
| Config group | `Combines` | `DevLeague` |
| Announcement channel | any channel named `combines-announcements` | `DevLeagueAnnounceChannel` setting |
| Channel name tier | as sent (`veteran-81-home`) | slug (`splus-101-home`) |
| Match link | `https://devleague.rscna.com/combine/<id>` | `https://devleague.rscna.com/match/<id>` |
| Extra overwrites | `Muted` role: view, no connect/speak | none |
| Placement | where Discord puts it | sorted by tier, ID, home before away |
| Final score | read from the combines API | none |

The runners are created once in `RSC.__init__` as `self._combines_runner` and `self._devleague_runner`. The card builder (`LobbyCard`) and its storage helpers live in [rsc/combines/views.py](../../rsc/combines/views.py) and [rsc/combines/lobby.py](../../rsc/combines/lobby.py), not in this package. Sample payloads are in `data/combines/` and `data/devleague/`; `scripts/combines_lobby.py` and `scripts/devleague_lobby.py` post them to the local server (`start <guild_id> [--games N]`, `teardown <guild_id> <id>`).

## Gotchas

- The routes have no authentication. Safety rests on the server binding to `localhost` only.
- A `200` from the match route only means the batch was accepted. Per-lobby failures are logged, not reported back.
- Duplicate protection is an in-memory set plus the channel-name check. The set is lost on restart, so after a restart only existing channels stop a repeated webhook.
- The 30 second delay is an in-memory sleep. A restart in that window leaves the voice channels behind (the card is already Final); teardown commands clean them up.
- Teardown only looks in the configured category and its `-2` to `-4` overflow categories. Channels moved elsewhere are not found.
- When every overflow category is full, new lobbies go into the configured category anyway.
- Combines teardown asks the combines site for the final score before it deletes anything. When the site is down, each lobby with a saved card waits up to 10 seconds for that, so `/combinemanager stop` or `teardown` with many open lobbies can take a while before it replies.
