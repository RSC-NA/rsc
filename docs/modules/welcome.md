# Welcome

**Package:** [rsc/welcome/](../../rsc/welcome/) · **Mixin(s):** `WelcomeMixIn`

Greets people who join the server. When a member joins, the bot gives them the configured welcome roles and posts the welcome message in the welcome channel. The welcome roles also double as the league's "default roles": other modules re-add them whenever they resync a member's Discord roles.

## Using it

An admin sets it up once:

1. `/welcome channel` to pick the text channel for the message.
2. `/welcome message` to write the message. `{member.mention}` pings the new member; other attributes of the member, such as `{member.name}`, also work.
3. `/welcome roles` to choose up to four roles every new member gets.
4. `/welcome settings` to check the result.

After that it runs on its own for every join.

## Commands

**`/welcome`** (default permission: **Manage Roles**)

| Command | Who can run it | What it does |
|---|---|---|
| `/welcome settings` | Manage Roles | Show the enabled flag, channel, roles and message (private). |
| `/welcome toggle` | Manage Roles | Turn the welcome message on or off. New members get the welcome roles either way. |
| `/welcome channel channel` | Manage Roles | Set the welcome channel (text channels only). |
| `/welcome message msg` | Manage Roles | Set the welcome message, 1 to 512 characters. |
| `/welcome roles role1 [role2] [role3] [role4]` | Manage Roles | Replace the welcome role list with these roles. |

## Configuration

Stored in the custom Config group `Welcome`, keyed by guild ID.

| Key | Default | Set by |
|---|---|---|
| `WelcomeChannel` | `None` | `/welcome channel` |
| `WelcomeMsg` | `None` | `/welcome message` |
| `WelcomeRoles` | `[]` | `/welcome roles` |
| `WelcomeStatus` | `True` | `/welcome toggle` |

## Background work

- **`on_member_join` listener.** Adds the welcome roles to the new member. Then, if the message is on (`/welcome toggle`) and a welcome channel and a welcome message are both set, it posts the message with `str.format(member=member)` and user mentions allowed. The [members](./members.md) module has its own join listener that creates or renames the member in the RSC API; the two run independently.

## How it works

- [welcome.py](../../rsc/welcome/welcome.py): `WelcomeMixIn`, the listener, the `/welcome` commands, and the Config getters and setters.

`_get_welcome_roles()` drops any stored role ID that no longer exists in the guild and saves the cleaned list back. It is called from other modules as the "default roles" source: `rsc/transactions/transactions.py` (after a cut), `rsc/admin/admin.py`, `rsc/admin/agm.py` and `rsc/admin/sync.py` pass it into the role sync helpers in `rsc/transactions/roles.py`, which add any default role the member is missing.

## Gotchas

- The message is a Python format string. A stray `{` or `}`, or an unknown placeholder, makes the listener fail and no message is sent.
- `/welcome roles` replaces the whole list. Changing the welcome roles also changes the default roles that cuts and admin syncs re-add.
