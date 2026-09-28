# Dev League

## Player Commands

`/devleague`

- `status` - Check your Dev League check-in status
- `checkin` - Check in for Dev League
- `checkout` - Check out of Dev League
- `optin` / `optout` - Add or remove the Dev League notification role <!-- codespell:ignore optin -->

## Game Channels

When the Dev League API creates a match, the bot creates `home` and `away` voice channels for it in the configured category and announces the lobby. When the match finishes, the bot deletes the channels 30 seconds later.

The feature is **disabled by default**.

### Manager Commands

`/devleaguemanager` (requires Manage Server by default)

- `settings` - Show the current configuration
- `category <category>` - Category that game channels are created in
- `announcements <channel>` - Text channel that new games are announced in (optional)
- `enable` - Start creating game channels (requires a category)
- `disable` - Stop creating game channels. Existing channels are left alone

### Channels

- Channel names use a lowercase tier slug: `S+` becomes `splus`. For example, `splus-101-home` and `b-102-away`.
- Channels are ordered by tier (S+, S, A, B, ... F), then by match id.
- Only the match's players can connect and speak. Everyone else can view the channel.
- When a category has more than 40 channels, new games go into overflow categories named `<category>-2` to `<category>-4`.

### Webhooks

The bot listens on `localhost:8008`. The payloads have the same shape as combines (`rsc/combines/models.py`).

| Route | Payload | Action |
|---|---|---|
| `POST /devleague_match` | Object of lobbies keyed by match id (`CombinesLobby`) | Create channels and announce |
| `POST /devleague_event` | `CombineEvent` with `message_type: "Finished Game"` | Delete the match's channels |

Responses:

- `400`: invalid JSON or payload
- `503`: the bot is not in the guild, or Dev League is disabled
- `501`: the event type is not handled

Sample payloads are in `data/devleague/`. To send them, use `scripts/send_devleague_lobby.py` and `scripts/send_devleague_end.py <match_id>`.
