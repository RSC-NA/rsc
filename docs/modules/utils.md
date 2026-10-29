# Utils

**Package:** [rsc/utils/](../../rsc/utils/) · **Mixin(s):** `UtilsMixIn`, `TrophyMixIn` · **Details:** [package README](../../rsc/utils/README.md)

Shared helpers used across the bot, plus two small sets of commands. `UtilsMixIn` gives staff general Discord tools: look up member IDs, list who reacted to a message or who holds a role, add or remove roles in bulk, and change a channel permission. `TrophyMixIn` gives staff the `/accolades` commands that add championship trophies, stars, Dev League trophies and combine cups to a player's nickname.

The rest of the package is code other modules call: the bot's single rate-limited DM queue, role lookups and nickname handling, website links, image rendering, text sanitising and paging.

## Using it

**Staff**

- Need someone's Discord ID? `/getid <member>`, or `/getmassid` for a list of names or IDs at once.
- Need a list of people? `/getallwithrole` (members who have all of up to four roles) or `/getreactlist` (who reacted to a message, optionally one emoji only, optionally grouped by tier role).
- Giving roles to a batch of players: `/bulkaddrole` with a list of IDs or with another role whose members should all get it; `/bulkremoverole` to take a role from a list, or from everyone who has it. Both ask for confirmation first.
- After a championship: `/accolades addtrophy`, `addstar`, `adddevleague` or `addcombinecup` for one player, or `/accolades masstrophy` and paste one Discord ID per line.

**Developers: which helper to reach for**

| Need | Use |
|---|---|
| Send any DM | `self._dm_helper.enqueue(...)` ([dm.py](../../rsc/utils/dm.py)). Never create a second `DMHelper`; for time-sensitive DMs pass `urgent=True`. |
| A required league role by name | `utils.get_league_role`, `get_gm_role`, `get_agm_role`, `get_free_agent_role`, `get_permfa_role`, `get_devleague_role`, `get_muted_role`, `get_ir_role`, `get_captain_role`, `get_tier_role`, `get_tier_fa_role`, and others in [utils.py](../../rsc/utils/utils.py). Each raises `ValueError` if the role is missing. |
| Set a player's nickname | `update_discord_name(member, name, prefix)`: builds `PREFIX \| name accolades`, raises `DiscordNameTooLong` over 32 characters, and skips the edit if nothing changed. |
| Turn a display name back into an RSC name | `rsc_name_from_display_name` / `rsc_name_from_member` (strip franchise prefix and trailing accolade emoji). Treat the result as a search term, not a key. |
| Read or rewrite accolades in a nickname | `member_accolades`, `strip_discord_accolades`, `format_discord_prefix`. |
| Find a franchise role | `franchise_role_from_name`, `franchise_role_from_league_player`, `franchise_role_from_model`, `franchise_role_from_disord_member`. |
| Defer an interaction that may already be dead | `safe_defer`, which returns False on Discord's "unknown interaction". |
| Who did something, from the audit log | `get_audit_log_reason`. |
| Link to the public website | `website_url(api_url)`, `match_page_url`, `standings_page_url` ([website.py](../../rsc/utils/website.py)). The site URL is the guild's API URL with `/api/...` removed. |
| Split long text into messages | `Pagify` ([pagify.py](../../rsc/utils/pagify.py)), which also escapes `@everyone`/`@here` by default. |
| Escape or sanitise user text | `utils.escape` (mass mentions, markdown) and [filters.py](../../rsc/utils/filters.py) (`filter_urls`, `filter_invites`, `filter_mass_mentions`, `filter_various_mentions`, `escape_spoilers`, `normalize_smartquotes`). |
| Refresh an autocomplete name cache | `merge_name_cache(cached, names, full_refresh=...)` ([cache.py](../../rsc/utils/cache.py)): a full refresh replaces, a filtered one only adds, always de-duplicated. |
| Draw an image | [images.py](../../rsc/utils/images.py): `getProgressBar` (used by admin sync) and `signup_banner_file` (the animated sign-up banner, rendered off the event loop). |
| Resize an uploaded image | `resize_image`, `img_to_thumbnail`. |

## Commands

**General tools (`UtilsMixIn`)**. All are server-only.

| Command | Who can run it | What it does |
|---|---|---|
| `/getid <member>` | anyone | Replies privately with `display name:username:ID`. |
| `/getmassid <members>` | anyone | The same for a space-separated list of names or IDs. |
| `/getreactlist <channel> <message_id> [filter] [by_tier]` | anyone | Lists `ID:display name` of users who reacted to a message, per emoji, privately. `filter` limits to one emoji; `by_tier` groups by tier role, with a "No Tier" group last. |
| `/getallwithrole <role> [role2] [role3] [role4]` | anyone | Lists members who have all the given roles, privately. Falls back to plain text pages when the list is too long for an embed. |
| `/userinfo [member]` | anyone | Posts a public embed with status, Discord and server join dates, roles and current voice channel. |
| `/serverinfo [details]` | anyone | Posts a public embed about the server; `details` adds more. |
| `/addrole <role> <member>` | Manage Roles (and the bot needs Manage Roles) | Adds a role to one member. Refused if the role has permissions you lack or sits at or above the `Admin` role. |
| `/removerole <role> <member>` | Manage Roles (bot too) | Removes a role from one member, same limits. |
| `/bulkaddrole <role> [members] [to_role]` | Manage Roles (bot too) | After a confirm prompt, adds `role` to each listed member, or to everyone in `to_role`. Same limits; reports who failed. |
| `/bulkremoverole <role> [members]` | Manage Roles (bot too) | After a confirm prompt, removes `role` from each listed member, or from everyone who has it if no list is given. |
| `/setchannelperm <channel> <target> <permission> <value>` | Manage Server (bot too) | Sets one permission overwrite (Allow, Deny or Inherit) for a member or role on a text channel. |

"Manage Roles" and "Manage Server" here are runtime checks, not `default_permissions`, so everyone sees these commands but only those with the permission can use them.

**`/accolades` (`TrophyMixIn`)**

| Command | Who can run it | What it does |
|---|---|---|
| `/accolades addtrophy <player>` | Manage Server | Adds a championship trophy to the player's nickname. |
| `/accolades addstar <player>` | Manage Server | Adds an MVP/All-Star star. |
| `/accolades adddevleague <player>` | Manage Server | Adds a Dev League championship trophy. |
| `/accolades addcombinecup <player>` | Manage Server | Adds a combine cup. |
| `/accolades masstrophy <trophy>` | Manage Server | Pick Championship, Star, Dev League or Combine Cup; a form opens for Discord IDs, one per line. Applies to each, with progress every 10 members and a list of failures at the end. |

Manage Server is the group's `default_permissions`.

## Configuration

None. Accolades are stored only in the nickname itself, as emoji counted back by `member_accolades`. The DM queue keeps everything in memory.

Roles looked up by name include `Admin` (the ceiling for role commands), `League`, `General Manager`, `Assistant GM`, `Muted`, `Dev League Interest` and the tier and franchise roles. See [configuration](../configuration.md).

## Background work

**The DM queue (`DMHelper`, [dm.py](../../rsc/utils/dm.py)).** One instance, `self._dm_helper`, is created and started in `RSC.__init__` and shared by every feature that DMs (lobby cards, Intent to Play, activity checks, PermFA polls, scheduled admin DMs).

- Sends one DM at a time, waiting a random 0.75 to 2.25 seconds (1.5 s ± 50%) between sends.
- `urgent=True` DMs go ahead of everything waiting but are still paced. Otherwise first in, first out.
- `send_at` holds a DM until that UTC time; a scheduler checks every 30 seconds and releases due ones into the queue.
- `precheck` runs just before sending and drops the DM if it returns False. If the check itself raises, the DM is sent anyway.
- `on_result` is called with `SENT`, `FAILED` or `SKIPPED` and the sent message, so callers can store message IDs for later edits.
- On a rate limit it retries up to 5 times with backoff. Forbidden (DMs closed) or other HTTP errors count as failed and the member is remembered (last 200) for follow-up.
- Staff see and control it with `/admin dmstatus` and `/admin dmcancel` in [admin](./admin.md).

**Persistent views.** None here. The bulk role confirm view and the mass trophy form are short-lived.

## How it works

- [utils.py](../../rsc/utils/utils.py): most standalone helpers (roles, names, prefixes, accolades, images, audit log, `safe_defer`) and `UtilsMixIn` with its commands.
- [trophy.py](../../rsc/utils/trophy.py): `TrophyMixIn`, the `/accolades` commands and `format_nickname`, which rebuilds a nickname as `name accolades` and refuses names over 32 characters.
- [dm.py](../../rsc/utils/dm.py): `DMHelper`, `DMTask` and `DMOutcome`.
- [website.py](../../rsc/utils/website.py): public website URLs derived from the API URL.
- [cache.py](../../rsc/utils/cache.py): `merge_name_cache`, used by the tier, franchise and team autocomplete caches.
- [filters.py](../../rsc/utils/filters.py) and [pagify.py](../../rsc/utils/pagify.py): text sanitising and paging.
- [images.py](../../rsc/utils/images.py): Pillow drawing for the progress bar and the sign-up banner, using the Apotek fonts in `rsc/resources/fonts/`.
- [views/bulk_role.py](../../rsc/utils/views/bulk_role.py): `BulkRoleConfirmView`. [views/mass_trophy.py](../../rsc/utils/views/mass_trophy.py): `MassTrophyModal`, which resolves IDs from the cache first and then the API, collecting bad lines rather than failing the batch.

Nothing in this package calls the RSC API except `/getreactlist` with `by_tier`, which fetches the league's tier list (`TiersApi.tiers_list` via `self.tiers`).

## Gotchas

- Every four Dev League trophies display as one cookie emoji; `member_accolades` counts each cookie as four.
- `/accolades addstar` replies "Added dev league trophy" even though it added a star.
- A nickname that would exceed 32 characters with the new accolade is not changed; the command replies with the error.
- `/addrole` and `/removerole` skip their permission and Admin-ceiling checks for one hard-coded developer account (`const.NICKM_ID`).
- In `/bulkaddrole` and `/bulkremoverole`, the "role too high" and "role at or above Admin" refusals try to answer an interaction that the confirm prompt already answered, so the user sees a failed command rather than the message.
- `/getallwithrole` ignores `role4` unless `role2` or `role3` is also given.
- `/userinfo` and `/serverinfo` post publicly in the channel, unlike the other lookup commands.
- Scheduled and queued DMs live only in memory. A cog reload or restart discards them without sending.
- `failed_members` covers every feature sharing the queue, not one batch.
- `get_*_role` helpers raise `ValueError` when the role is missing, and some callers (for example `/devleague optin` and `/combinemanager start`) do not catch it.
