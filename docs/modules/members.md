# Members

**Package:** [rsc/members/](../../rsc/members/) · **Mixin(s):** `MemberMixIn` · **Details:** [package README](../../rsc/members/README.md)

This module is how players get into the league. It runs the `/signup` and `/permfa` sign-up flows, the intent to play declaration for current players, and the status checks players use to see where they stand for next season. It also shows a player card (`/playerinfo`) and the waiver list.

Behind the commands it is the bot's wrapper for the RSC API's members endpoints: creating members, signing them up, declaring intent, activity checks, name changes, account transfers and staff ("elevated") roles. Other modules, mostly [admin](./admin.md) and [transactions](./transactions.md), call these helpers. The staff permission check used across the bot (`elevated_role_required` in `rsc/checks.py`) reads its answers from this module's elevated role cache.

## Using it

**New players**

1. Run `/signup` while signups are open. If signups are closed the bot says so and stops.
2. Step 1, "Before you start": confirm you can play on match nights (Monday and Wednesday at 10 PM ET for 3v3; Thursday for the 2v2 server) and agree to the behaviour rules. Both buttons must be green before Continue unlocks.
3. Step 2, "About you": choose Draft eligible or Permanent Free Agent, whether you have played in RSC before, your region, main platform, and how you heard about RSC.
4. A form opens for your in-game name (2 to 25 characters) and tracker links, one per line. If RSC already has your name or trackers on file, the form is filled in with them.
5. A review card shows every answer with Edit buttons. Bad tracker links are listed with a Fix button. Press **Submit sign-up**.
6. On success the bot updates your Discord roles and nickname, shows a sign-up banner, and tells you what happens next. Everything in the flow is visible only to you.

Tracker links must be `rocketleague.tracker.network/rocket-league/profile/<platform>/<id>` profile links on Steam, Epic, PlayStation, Xbox or Switch. Steam links need the 17-digit Steam64ID, not a custom name. Repeated links are dropped.

**Returning players**

- Players already in the league declare intent with `/intent declare`: pick "Returning next season" or "Not returning next season" and press Confirm. You have 30 seconds before the prompt times out.
- `/signup` routes current players to the intent prompt automatically. It does this if you already have a league player record for the signup season, or if you played last season and were not dropped. Dropped players go through the full sign-up again, with "played before" already answered.
- Check where you stand with `/signupstatus` (sign-up or intent, depending on your status) or `/intent status`.

**Permanent Free Agents**

- `/permfa` runs the same flow with Permanent Free Agent preselected. If you are already a PermFA, or your PermFA request is still waiting on staff, the bot tells you and stops.
- After you submit, staff process the request. The success message says so.

**Anyone**

- `/playerinfo <player>` shows a private card with the player's status, tier, team, franchise and MMR, plus buttons for the team roster, the franchise's teams, and the player's tracker accounts.
- `/waivers <tier>` posts the players on waivers in a tier and their waiver end dates.
- `/intent search` lists intent to play results filtered by player, franchise, team, returning or missing. GMs can use it to check their roster.

## Commands

**Top-level commands**

| Command | Who can run it | What it does |
|---|---|---|
| `/signup` | Anyone | Sign up for the season currently accepting signups. Routes current and last-season players to intent declaration instead. |
| `/permfa` | Anyone | Sign up as a Permanent Free Agent. |
| `/signupstatus` | Anyone | Your sign-up or intent status for next season (private). |
| `/playerinfo player` | Anyone | Private player card with Team, Franchise and Trackers buttons. |
| `/waivers tier` | Anyone | Public list of players on waivers in `tier`, with end dates. |
| `/staff` | Anyone | Not implemented. Replies with a "not implemented" message. |

**`/intent`**

| Command | Who can run it | What it does |
|---|---|---|
| `/intent declare` | Anyone | Declare whether you are returning next season. |
| `/intent status` | Anyone | Your intent to play status for next season (private). |
| `/intent search [player] [missing] [returning] [franchise] [team]` | Anyone | Intent results matching the filters, up to 50 shown (private). At least one filter is required. |

## Configuration

This module stores no Config keys. It needs the guild's API settings and league ID to be configured (see [../configuration.md](../configuration.md)); without a league ID the status commands reply "Not Configured".

## Background work

- **`on_member_join` listener.** When someone joins a guild with API settings configured, the bot looks them up in the RSC API by Discord ID. If no member exists, it creates one. If one exists, it sets their server nickname to their RSC name. Failures are logged and ignored. This runs alongside the [welcome](./welcome.md) module's own join listener.
- **Dynamic buttons on the `/playerinfo` card.** `PlayerInfoButton` (Team and Franchise) and `PlayerTrackersButton` (Trackers) are `DynamicItem`s registered once in `rsc/core.py` with `bot.add_dynamic_items()`. The team name, franchise name or Discord ID is stored in the button's `custom_id`, so the buttons keep working after a restart. A click that arrives before the cog has finished setup gets "The bot is still starting up".
- **Elevated role cache.** Staff positions looked up from the API are cached per guild and member for 300 seconds. Granting or deleting a role through this module clears that member's entry.

The module sends no DMs.

## How it works

- [members.py](../../rsc/members/members.py): `MemberMixIn`. Commands, the join listener, the sign-up and intent flows, the elevated role cache, and all `MembersApi` wrappers.
- [views/signup.py](../../rsc/members/views/signup.py): `SignupFlowView` (the three-step flow on one ephemeral message), the name/tracker form, the fix-trackers form, the review card, `SignupSuccessView`, and `AlreadySignedUpView`.
- [views/intent.py](../../rsc/members/views/intent.py): `IntentToPlayView`, the returning/not returning prompt.
- [views/player_info.py](../../rsc/members/views/player_info.py): `PlayerCard` and its dynamic buttons.
- [tracker_links.py](../../rsc/members/tracker_links.py): parses and validates the tracker links field.

**Sign-up flow.** `/signup` calls `next_signup_season` (the [seasons](./seasons.md) module). If the API raises `SignupsClosedException`, signups are closed. Otherwise it checks for a league player in the signup season, then in season number minus one, to decide between sign-up and intent. `_signup_flow` starts the view and, at the same time, starts `_signup_prefill` as a task. The prefill looks up the RSC member (creating one if missing) and their existing trackers. The form waits at most 1.5 seconds for it, because Discord needs a modal within 3 seconds; after that it opens empty. On submit the bot calls `members_signup_create` or `members_permfa_signup_create`, depending on the kind the player picked in step 2, not on which command they ran. A 409 shows the "already signed up" card, a 405 shows the API's reason, and anything else shows an API error. After a successful sign-up the bot runs `update_league_player_discord` (in `rsc/transactions/roles.py`) to sync roles and nickname. It also adds the Dev League interest role if `should_get_devleague_role` says the player has never had it. A nickname that is too long for Discord does not fail the sign-up; the success card asks the player to open a modmail ticket. The banner image comes from `rsc/utils/images.py`, and a render failure only drops the banner.

**Status commands** fall back to the current season when signups are closed. `/signupstatus` treats a player whose status is PermFA, Free Agent, Rostered, Unsigned GM, IR, AGM IR or Renewed as a current player and reports their intent instead. A Draft Eligible player is reported as signed up.

**API endpoints used.** `MembersApi`: `members_list`, `members_create`, `members_destroy`, `members_signup_create`, `members_permfa_signup_create`, `members_intent_to_play_create`, `members_activity_check_create`, `members_elevated_roles_list/create/destroy`, `members_name_change_partial_update`, `members_name_changes_list`, `members_stats_retrieve`, `members_transfer_account_create`, `members_make_player_create`, `members_member_league_drop_create`. `ElevatedRolesApi.elevated_roles_list`. It also uses `players()` from [leagues](./leagues.md), `player_intents()` and `next_signup_season()` from [seasons](./seasons.md), and `trackers()` from [trackers](./trackers.md).

**Elevated roles.** `elevated_positions()` returns the set of `StaffPositions` codes a member holds. The API returns display labels such as "Numbers", so they are parsed to codes such as `NUMS` first. GMs and AGMs are not elevated roles; they are franchise staff records on the franchise.

## Gotchas

- `/signup` lets a player pick Permanent Free Agent in step 2, and that submits a PermFA sign-up even though they ran `/signup`.
- The intent prompt times out after 30 seconds. The sign-up flow allows 14 minutes of inactivity.
- `/intent search` has no permission check, so any member can search anyone's intent.
- `/playerinfo` replies privately, but `/waivers` posts publicly.
- `/playerinfo` hides the Team or Franchise button when the name does not fit in Discord's 100-character `custom_id`.
- Starting the sign-up flow creates an RSC member for the player if none exists, even if they then cancel. The prefill task starts as soon as step 1 is shown.
- The 2v2 league is detected by a hard-coded guild ID in `views/signup.py`, which sets the match nights shown.
