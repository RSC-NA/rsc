# Trackers

**Package:** [rsc/trackers/](../../rsc/trackers/) · **Mixin(s):** `TrackerMixIn`

Players' Rocket League accounts are recorded in RSC as tracker links (rocketleague.tracker.network profiles). The Numbers Committee pulls MMR from them to place players. This module lets Numbers staff and admins add, link, unlink, delete and merge tracker links, check how current the pulls are, and look up a tracker by ID. Anyone can see a player's accounts with `/accounts`.

## Using it

- **Anyone:** `/accounts <player>` posts a card with the player's tracker accounts grouped by platform, each linked to its profile. Steam accounts are shown by Steam64ID, others by account name. The card also links the RSC tracker links spreadsheet.
- **Numbers staff and admins:**
  1. A player is missing a tracker: `/trackers add player tracker` with the profile link.
  2. Check what a player has: `/trackers list player` (add `ids:True` to see the tracker IDs you need for the other commands).
  3. A tracker belongs to someone else: `/trackers unlink tracker_id player`, then `/trackers link tracker_id player` for the right person.
  4. A duplicate tracker: move its pulls with `/trackers merge source dest`, or delete it with `/trackers delete tracker_id` if it has no pulls.
  5. Monitoring pulls: `/trackers stats` for counts by status, `/trackers recent` for the latest 25 updates, `/trackers old` for how many have not been updated in N days.

Players add their own trackers during `/signup` (see [members](./members.md)).

## Commands

**`/trackers`**

"Numbers staff" below means a member with the Discord **Manage Server** permission, or a member the RSC API lists with the Admin, Numbers or Numbers Head staff position in this league. Everyone else gets "You do not have permission to run this command." The group is visible to all members.

| Command | Who can run it | What it does |
|---|---|---|
| `/trackers add player tracker` | Numbers staff | Create a tracker link for `player`. |
| `/trackers list player [ids]` | Numbers staff | List the player's trackers with status and last pull date. `ids` adds the tracker ID column. |
| `/trackers link tracker_id player` | Numbers staff | Link an existing tracker to `player`. |
| `/trackers unlink tracker_id player` | Numbers staff | Unlink a tracker from `player`. |
| `/trackers delete tracker_id` | Numbers staff | Delete a tracker. Refused if it has any MMR pulls; unlink it instead. |
| `/trackers recent [status]` | Numbers staff | The 25 most recently updated trackers with the given status (default Pulled). |
| `/trackers stats` | Numbers staff | Count of trackers in each status. |
| `/trackers old [status] [days]` | Numbers staff | How many trackers with `status` (default Pulled) have not been updated in `days` (default 90). |
| `/trackers merge source dest` | Numbers staff | Move all MMR pulls from tracker `source` into tracker `dest`. |
| `/trackers byid tracker_id` | Numbers staff | Player, Discord ID, platform, link, status and last update for one tracker. |

Tracker statuses are New, Stale, Pulled, Failed, Missing, Repull and Invalid.

**Top-level command**

| Command | Who can run it | What it does |
|---|---|---|
| `/accounts player` | Anyone | Post the player's tracker accounts. The player is named but not pinged. |

## Configuration

None. Permission comes from Discord's Manage Server permission or the player's staff positions in the RSC API.

## Background work

None of its own. The card built by `tracker_accounts_card` is also used by the Trackers button on the `/playerinfo` card in [members](./members.md).

## How it works

- [trackers.py](../../rsc/trackers/trackers.py): `TrackerMixIn`, the commands, and the `TrackerLinksApi` wrappers.
- [views.py](../../rsc/trackers/views.py): `tracker_accounts_card()`, a Components V2 card shared by `/accounts` and the player card. It shows at most 25 accounts and notes how many more there are.

API calls (`TrackerLinksApi`): `tracker_links_list` (single page via `trackers()`, every page via `paged_trackers()`), `tracker_links_links_stats_list`, `tracker_links_next_list`, `tracker_links_create`, `tracker_links_destroy`, `tracker_links_link_create`, `tracker_links_unlink_create`, `tracker_links_retrieve`, `tracker_links_migrate_pulls_create`. Link and unlink send the running staff member as `executor`.

The permission gate is `elevated_role_required(ADMIN, NUMBERS, NUMBERS_HEAD)` from `rsc/checks.py`. It checks Manage Server first, then asks `elevated_positions()` (cached for 5 minutes in [members](./members.md)). If the API call fails, access is denied.

`/trackers recent` and `/trackers old` fetch every tracker with the given status before filtering, so they can be slow on large statuses. `/trackers old` uses the guild's configured timezone for the cutoff date.

## Gotchas

- Almost every `/trackers` reply is public in the channel, including errors. Run them in a staff channel.
- `/trackers merge` takes tracker IDs, not players. Get them from `/trackers list player ids:True`.
- `/trackers list` sorts by status text. A tracker with no status mixed with ones that have a status can make the sort fail.
