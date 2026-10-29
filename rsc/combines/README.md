# Combines

## Player Commands

`/combines`

- `checkin` - Check in for a combines match
- `checkout` - Check out of combines
- `lobbyinfo [lobby_id]` - Show your lobby's name, password and team
- `active [player] [tier]` - List active combine games for you or another player, optionally in one tier

`checkin`, `checkout` and `lobbyinfo` only work while combines are started.

## Game Channels

When the combines API creates a lobby, the bot creates `home` and `away` voice channels for it in the configured category and announces the lobby in #combines-announcements. When the lobby finishes, the bot marks the lobby card Final straight away, with the series score from the combines API, and deletes the channels 30 seconds later.

Combines are **stopped by default**.

### Manager Commands

`/combinemanager` (requires Manage Server by default)

- `settings` - Show the current configuration
- `category <category>` - Category that combines channels are created in
- `api <url>` - Combines API location, for example `https://devleague.rscna.com/c-api/`
- `start` - Start combines and create the combines channels (requires the API and category)
- `stop` - Stop combines, end every open lobby as `teardown` does, then delete the combines category and its overflow categories
- `teardown [lobby_id]` - End a lobby that is finished on the website but still up in Discord: mark its card Final and delete its channels now. With no lobby ID, ends every lobby
- `guide [channel] [overwrite]` - Post the how-to-play guide, in #how-to-play by default. If one is already posted there, links it instead. `overwrite` updates it in place

### Channels

`start` creates these in the combines category, skipping any that already exist:

- `how-to-play` and `combines-announcements` - Read-only. The guide is posted when `how-to-play` is created
- `combines-help` - Posts the help messages when created
- `combines-general` - Chat, with a 5 second slowmode
- `combines-waiting-room-1` and `combines-waiting-room-2` - Voice

Lobby channels:

- Channel names are the tier as the API sends it, then the lobby ID and side. For example, `veteran-81-home`.
- Only members with the League role can connect and speak. Everyone else can view the channel. The Muted role, if there is one, can view but not connect.
- When a category has more than 40 channels, new lobbies go into overflow categories named `<category>-2` to `<category>-4`.

### Webhooks

The bot listens on `localhost:8008`. Payloads are in `rsc/combines/models.py`.

| Route | Payload | Action |
|---|---|---|
| `POST /combines_match` | Object of lobbies keyed by lobby id (`CombinesLobby`) | Create channels and announce |
| `POST /combines_event` | `CombineEvent` with `message_type: "Finished Game"` | Delete the lobby's channels |

Responses:

- `400`: invalid JSON or payload
- `503`: the bot is not in the guild, or combines are not started
- `501`: the event type is not handled

Sample payloads are in `data/combines/`. To send them, use `scripts/combines_lobby.py start <guild_id>` and `scripts/combines_lobby.py teardown <guild_id> <lobby_id>`. Add `-2` to `start` to send the 2s sample instead, and `--games N` to create N lobbies, cycling through the samples with IDs counting up from the first (81, 82, …).
