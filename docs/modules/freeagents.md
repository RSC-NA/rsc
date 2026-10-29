# Free agents

**Package:** [rsc/freeagents/](../../rsc/freeagents/) · **Mixin(s):** `FreeAgentMixIn` · **Details:** [package README](../../rsc/freeagents/README.md)

This module helps GMs find free agents. It lists a tier's free agents and permanent free agents from the RSC API. It also runs a daily check-in board: on match days, free agents mark themselves available to sub, and GMs see who is available in each tier. The check-in board is stored by the bot itself, not in the RSC API.

## Using it

1. **Free agents, on a match day:** run `/freeagent checkin` and confirm. You stay on the board for that day. If you can no longer play, run `/freeagent checkout`.
2. **GMs looking for a sub:** run `/freeagent availability <tier>` to see who has checked in. To see every free agent in a tier regardless of check-in, run `/freeagents <tier>`, which also shows MMR and permanent free agents.
3. **Transaction committee:** once a sub is processed with `/transactions sub` ([transactions](./transactions.md)), the subbed-in player is hidden from the availability list automatically.
4. **Admins:** clear the board for one tier with `/clearavailability <tier>`, or for all tiers with `/clearallavailability`. Normally this is not needed, because check-ins expire on their own the next day.

## Commands

### Listing

| Command | Who can run it | What it does |
| --- | --- | --- |
| `/freeagents <tier>` | Anyone (server only) | Lists the tier's free agents and permanent free agents in separate sections, highest MMR first, with MMR shown. Skips players who are not in the server. Long lists are split across several messages. |

### `/freeagent`

| Command | Who can run it | What it does |
| --- | --- | --- |
| `/freeagent checkin` | Anyone (server only), but only succeeds for free agents | Asks you to confirm, then adds you to today's availability board for your tier. Refused if you are already checked in, if today is not a match night, if you are not a player in this league, or if your status is not Free Agent, Permanent FA or Waivers. |
| `/freeagent checkout` | Anyone who is checked in | Asks you to confirm, then removes you from the board. |
| `/freeagent availability <tier>` | Anyone (server only) | Lists checked-in free agents for the tier who are still in the server and still visible. |

### Admin

| Command | Who can run it | What it does |
| --- | --- | --- |
| `/clearavailability <tier>` | Manage Server | Removes every check-in for the tier. |
| `/clearallavailability` | Manage Server | Removes every check-in for all tiers. |

## Configuration

Stored in a Red custom config group `FreeAgents`, keyed by guild ID:

| Key | Default | Set by |
| --- | --- | --- |
| `CheckIns` | `[]` | `/freeagent checkin` and `checkout`, the clear commands, the expiry loop, and `/transactions sub` (which sets `visible` to false). Each entry is a `CheckIn` dict: `date` (ISO string in the guild timezone), `player` (Discord ID), `tier` (name), `visible` (bool). |

There is nothing to configure by command. The guild timezone comes from the settings module, and match nights come from the current season's schedule in the API (see [../configuration.md](../configuration.md)).

## Background work

- **`expire_free_agent_checkins_loop`** runs once a day at 17:00 UTC. The code comment calls this "noon Eastern", which is only correct outside daylight saving time. For every guild it removes check-ins whose date is yesterday or earlier in the guild's timezone. If the loop raises, its error handler logs the crash and restarts it.
- **Cache load on startup:** `_setup_guild` in [core.py](../../rsc/core.py) calls `_populate_free_agent_cache` for every guild, including guilds with no API configured, which copies `CheckIns` from config into memory.
- **Views:** `CheckInView` and `CheckOutView` are confirm/decline prompts that only the person who ran the command can use. They time out after the default view timeout and are not persistent.

This module sends no DMs.

## How it works

- [freeagents.py](../../rsc/freeagents/freeagents.py) holds the commands, the loop, and the check-in store. `_check_ins` is an in-memory copy of each guild's `CheckIns`. Every write reads the list from config, changes it, then saves it to both config and the in-memory copy. `/freeagent availability`, `is_checked_in` and `get_checkin` read the in-memory copy only.
- [views.py](../../rsc/freeagents/views.py) holds the two confirmation views.
- The free agent lists come from `paged_players(status=FA or PermFA, tier_name=...)` in [members](./members.md), not a separate endpoint.
- The check-in eligibility test uses `players(discord_id=...)` from [members](./members.md). The match-day test is `is_match_day` in [matches](./matches.md), which checks today's weekday against `match_nights` on the current season's first tier schedule.
- `update_freeagent_visibility` is called by `/transactions sub` to hide the subbed-in player without deleting their check-in.

## Gotchas

- A check-in is not cleared at the end of the match day. It is cleared at the next 17:00 UTC loop run on a later date, so a player who checks in in the evening stays listed until the following day's run.
- `/freeagent checkin` fails with an exception if the current season has no match nights configured (`is_match_day` raises `AttributeError`).
- The tier argument goes through `str.capitalize()`, and `/freeagents` checks it against the tier autocomplete cache. If that cache is empty (API down at startup), every tier is rejected as invalid.
- The "already checked in" check runs before the confirmation prompt, not right before the save. Two prompts confirmed in parallel can store two check-ins for one player.
