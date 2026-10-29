# Dev League

**Package:** [rsc/devleague/](../../rsc/devleague/) · **Mixin(s):** `DevLeagueMixIn`, `DevLeagueManagerMixIn` · **Details:** [package README](../../rsc/devleague/README.md)

Dev League is RSC's pick-up development league, run on the Dev League website (devleague.rscna.com). Players check in, the website groups them into matches by letter-grade tier (S+ down to F), and plays them out. This module gives players `/devleague` commands to check in, check out and see their status from Discord, manages the opt-in "Dev League Interest" notification role, and, when the website starts a match, creates the match's home and away voice channels, posts a live match card, and DMs each player. When the match finishes the card turns Final and the voice channels go.

The match start and finish come from website webhooks to the bot's local web server. The handling is the same code as [combines](./combines.md), in [lobbies](./lobbies.md); this module only supplies what differs.

## Using it

**Players**

- `/devleague checkin` to queue, `/devleague checkout` to leave, `/devleague status` to see whether you are checked in, your Dev League name and tier. If the website is down or slow, these wait up to 10 seconds and then answer privately with "Couldn't reach the Dev League website. Try again in a moment."
- `/devleague optin` adds the Dev League Interest role (Dev League pings); `/devleague optout` removes it.
- When a match starts, your card is posted in the announcement channel (if one is set) with your name pinged, the lobby name and password, rosters, and Join buttons for the Home and Away voice channels. You also get a DM copy that says which team you are on and whether you make the lobby (first Home player).
- When the website marks the match finished, the card and your DM turn Final and the voice channels are deleted 30 seconds later.

**Admins, one-time setup**

1. `/devleaguemanager category` to pick the category match channels go in.
2. `/devleaguemanager announcements` to pick the text channel match cards are posted in. Optional, but without it there are no cards and no DMs.
3. `/devleaguemanager enable`. Until this is on, the website's match webhooks are refused.
4. Check with `/devleaguemanager settings`.

**Admins, when something is stuck or to switch off**

- `/devleaguemanager teardown <match_id>` ends a match that is finished on the website but still up in Discord. With no ID it ends every open match.
- `/devleaguemanager disable` stops new matches being created and ends every open match. Unlike combines, it leaves the category and its other channels alone.

## Commands

**`/devleague`** (players)

| Command | Who can run it | What it does |
|---|---|---|
| `/devleague status` | anyone | Shows whether you are checked in, plus your Dev League name and tier, from the Dev League API. |
| `/devleague checkin` | anyone | Checks you in through the Dev League API. |
| `/devleague checkout` | anyone | Checks you out through the Dev League API. |
| `/devleague optin` | anyone | Gives you the `Dev League Interest` role and records you in `DevLeagueRoleUsers`. |
| `/devleague optout` | anyone | Removes the `Dev League Interest` role and records you in `DevLeagueRoleUsers` so it is not added back automatically. |

Every `/devleague` reply is private. `status`, `checkin` and `checkout` defer before they call the Dev League API, so Discord shows "thinking" while the bot waits. A failure to reach the site (no connection, more than 10 seconds, a 5xx, or a reply that isn't JSON or isn't the expected shape) gets one private red reply: "Couldn't reach the Dev League website. Try again in a moment." An error the site answers with, such as an unknown player, is shown in red with the site's own text.

**`/devleaguemanager`** (staff)

| Command | Who can run it | What it does |
|---|---|---|
| `/devleaguemanager settings` | Manage Server | Shows whether game channel creation is on, the category and the announcement channel. |
| `/devleaguemanager category <category>` | Manage Server | Sets the category match voice channels are created in. |
| `/devleaguemanager announcements <channel>` | Manage Server | Sets the text channel match cards are posted in. |
| `/devleaguemanager enable` | Manage Server | Turns on game channel creation. Refuses if no category is set. |
| `/devleaguemanager disable` | Manage Server | Turns it off, then ends every open match without the grace period. |
| `/devleaguemanager teardown [match_id]` | Manage Server | Ends one match (or every open match) now: card and DMs go Final, voice channels deleted. Errors if the match has no live card or channels. |

"Manage Server" is the group's `default_permissions`, so server admins can change it in Discord's Integrations settings.

Every `/devleaguemanager` reply is private. `disable` and `teardown` reply green, or orange with the IDs that could not be ended (usually missing permissions).

## Configuration

Stored in the Red Config custom group `DevLeague`, keyed by guild ID.

| Key | Default | Set by |
|---|---|---|
| `Active` | `False` | `/devleaguemanager enable` / `disable` |
| `DevLeagueCategory` | `None` (category ID) | `/devleaguemanager category` |
| `DevLeagueAnnounceChannel` | `None` (channel ID) | `/devleaguemanager announcements` |
| `DevLeagueRoleUsers` | `None` (list of member IDs) | `/devleague optin` and `/devleague optout` |
| `LobbyMessages` | `{}` | Written by the lobby runner: match ID to the card and its message IDs, kept until teardown. See [lobbies](./lobbies.md). |

Roles found by name: `League` (who may join match voice channels) and `Dev League Interest` (the opt-in role). The Dev League API URL is fixed in code as `https://devleague.rscna.com`; there is no setting for it.

## Background work

- **Webhooks** on the bot's web server at `localhost:8008` (started in [rsc/core.py](../../rsc/core.py)):

  | Route | Payload | What happens |
  |---|---|---|
  | `POST /devleague_match` | JSON object of matches keyed by match ID, same shape as combines (`CombinesLobby`: `id`, `lobby_user`, `lobby_pass`, `tier`, `guild_id`, `home`, `away`, ...) | Replies 200 at once, then creates each match's voice channels and posts its card in the background. |
  | `POST /devleague_event` | `CombineEvent` with `message_type: "Finished Game"`, `match_id` and `guild_id` | Card and DMs go Final at once; voice channels deleted 30 seconds later. |

  Responses: `400` bad JSON, invalid payload, empty batch, or finished event with no `match_id`; `503` bot not in the guild, or (match route only) Dev League not enabled; `501` any other event type. See [lobbies](./lobbies.md) for the shared handling.
- **Match voice channels** are named `<tier slug>-<match id>-home` / `-away`, where the slug is the tier lowercased with `+` spelled out (`S+` becomes `splus-101-home`, `B` becomes `b-102-away`). They are capped at 5 users, visible to everyone, joinable only by the League role, and moved into order by tier (S+, S, A, B, ... F, unknown tiers last), then match ID, Home before Away.
- **Match card** in the configured announcement channel, pinging the players on it, plus an urgent DM per player through the shared DM queue (see [utils](./utils.md)). The Final card has no score: Dev League does not fetch one.
- **Dev League Interest role elsewhere.** Sign-up, cut and role sync code in [members](./members.md), [transactions](./transactions.md) and [admin](./admin.md) calls `should_get_devleague_role` and adds the role to a player when they are not in `DevLeagueRoleUsers`.

## How it works

- [devleague.py](../../rsc/devleague/devleague.py): `DevLeagueMixIn`, Config registration, the `/devleague` player commands, and the role helpers `add_devleague_role`, `remove_devleague_role` and `should_get_devleague_role`.
- [manager.py](../../rsc/devleague/manager.py): `DevLeagueManagerMixIn`, the `/devleaguemanager` commands and Config getters/setters. `disable` turns creation off first, then ends open matches with the shared runner's `end_now`. `teardown`'s body and the "Ended ..." reply lines come from [rsc/lobbies/commands.py](../../rsc/lobbies/commands.py).
- [api.py](../../rsc/devleague/api.py): `GET https://devleague.rscna.com/api/status`, `/api/check_in` and `/api/check_out`, each with `discord_id` as a query parameter. All three go through the shared request helper in [rsc/lobbies/api.py](../../rsc/lobbies/api.py), which honours proxy environment variables, has a 10 second timeout, and turns every failure into `SiteUnavailable`.
- [models.py](../../rsc/devleague/models.py): `DevLeagueStatus` and `DevLeagueCheckInOut` (an unknown player gets back only `error`), plus aliases showing that match webhooks reuse the combines models.
- [runner.py](../../rsc/devleague/runner.py): `DevLeague`, the Dev League settings for the shared [`LobbyRunner`](./lobbies.md): Config group, configured announcement channel, slugged channel names, the match link (`https://devleague.rscna.com/match/<id>`), and `place`, which reorders the category's voice channels by tier in a single bulk position update.
- [tiers.py](../../rsc/devleague/tiers.py): tier slug, tier rank and channel sort key helpers.

The match card itself and its storage live in [rsc/combines/views.py](../../rsc/combines/views.py) and [rsc/combines/lobby.py](../../rsc/combines/lobby.py), shared with combines. On a Dev League card the title reads "Dev League <tier> Match <id>", there is no "Uploads the replays" note for Away, and the footer has no `/combines lobbyinfo` hint.

## Gotchas

- `DevLeagueRoleUsers` is only written by `optin` and `optout`. Automatic grants from sign-up, cuts and sync do not record the player, so the role keeps being re-added by those flows until the player runs one of the two commands.
- `optin` and `optout` fail with an unhandled error if no role named `Dev League Interest` exists.
- Without an announcement channel, matches still get voice channels but no card and no DMs.
- If the bot restarts during the 30 second grace period, the voice channels stay up. Use `/devleaguemanager teardown`.
- The webhook routes have no authentication; they rely on the server binding to `localhost` only.
