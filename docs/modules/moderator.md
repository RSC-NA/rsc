# Moderator

**Package:** [rsc/moderator/](../../rsc/moderator/) · **Mixin(s):** `ModeratorMixIn`, `ThreadMixIn`

Two separate pieces live here. `ThreadMixIn` helps staff route modmail tickets: each ticket is a text channel, and the bot moves it between a primary modmail category and per-team "group" categories, pinging the group's role. `ModeratorMixIn` is a placeholder for moderation commands (mute, kick, ban, strikes); every `/mod` command currently replies "not implemented".

## Using it

**Admin setup (once)**

1. `/thread category` to set the primary category where new modmail tickets arrive.
2. `/thread role` to set the management role that owns unassigned tickets.
3. `/thread groups add name category role` for each team that can take tickets, for example a transactions group with its own category and role.
4. `/thread settings` and `/thread groups list` to check.

**Staff handling tickets**

- In a ticket channel, `/assign group` moves the channel to that group's category, syncs its permissions to the category, and posts "This ticket has been assigned to @role".
- `/unassign` moves an assigned ticket back to the primary category and posts "This ticket has been given back to @management-role".
- `/resolve` in an assigned ticket posts `resolved` in a code block in the channel.

The bot does not create or close tickets. It only moves channels that already exist.

## Commands

**`/thread`** (default permission: **Manage Server**)

| Command | Who can run it | What it does |
|---|---|---|
| `/thread settings` | Manage Server | Show the primary category and management role. |
| `/thread category category` | Manage Server | Set the primary modmail category. |
| `/thread role role` | Manage Server | Set the modmail management role. |
| `/thread groups list` | Manage Server | List groups with their role and category. |
| `/thread groups add name category role` | Manage Server | Add a group, or overwrite one with the same name. |
| `/thread groups rm group` | Manage Server | Remove a group (autocompletes group names). |

**Ticket commands** (top level)

| Command | Who can run it | What it does |
|---|---|---|
| `/assign group` | Manage Channels | Move the current ticket to a group's category and ping the group role. Works in the primary category or any group category. |
| `/unassign` | Manage Channels | Move the current ticket back to the primary category and ping the management role. Only works in a group category. |
| `/resolve` | Manage Messages | Post a public `resolved` message. Only works in a group category. |
| `/feet` | Manage Server | In-joke command. Posts a fixed message with all mentions disabled, so nobody is pinged. |

**`/mod`** (default permissions: **Kick Members, Ban Members, Manage Roles**)

| Command | Who can run it | What it does |
|---|---|---|
| `/mod notify member` | Kick + Ban + Manage Roles | Not implemented. |
| `/mod mute member [days] [hours] [minutes]` | Kick + Ban + Manage Roles | Not implemented. |
| `/mod kick member` | Kick + Ban + Manage Roles | Not implemented. |
| `/mod ban member [days] [hours] [minutes]` | Kick + Ban + Manage Roles | Not implemented. |
| `/mod strike member rule [action] [days] [hours] [minutes]` | Kick + Ban + Manage Roles | Not implemented. `action` is Mute, Kick or Ban. |
| `/mod history member [days]` | Kick + Ban + Manage Roles | Not implemented. |
| `/mod recent [days]` | Kick + Ban + Manage Roles | Not implemented. |
| `/mod rules` | Kick + Ban + Manage Roles | Not implemented. |

## Configuration

Stored in the custom Config group `Thread`, keyed by guild ID.

| Key | Default | Set by |
|---|---|---|
| `PrimaryCategory` | `None` | `/thread category` |
| `ManagementRole` | `None` | `/thread role` |
| `Groups` | `{}` | `/thread groups add`, `/thread groups rm`. Maps group name to `{category: id, role: id}`. |

`ModeratorMixIn` stores nothing.

## Background work

None.

## How it works

- [thread.py](../../rsc/moderator/thread.py): `ThreadMixIn`, all `/thread` commands, `/assign`, `/unassign`, `/resolve`, `/feet`, and the Config helpers.
- [moderator.py](../../rsc/moderator/moderator.py): `ModeratorMixIn` and the stub `/mod` group.
- [strikes.py](../../rsc/moderator/strikes.py): lists of offences by severity (minor, normal, serious, other). Nothing imports it yet.

A channel counts as a modmail ticket when its category is the primary category or one of the group categories (`is_modmail_channel`). `is_modmail_thread` only matches group categories. `/assign` uses the first check and `/unassign` the second. The check exists because `channel.move(sync_permissions=True)` overwrites the channel's permissions from the destination category, and without it the command would do that to any channel.

The module calls no RSC API endpoints.

## Gotchas

- `/assign` and `/unassign` replace the ticket's permission overwrites with the destination category's. Anything set by hand on the channel is lost.
- `/resolve` does not work in the primary category, only in group categories.
- `/unassign` refuses to run until both the primary category and the management role are set.
- The ticket commands use `has_permissions` checks, not default permissions, so they show up for everyone in the command list but fail for members without the permission.
