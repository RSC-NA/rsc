---
name: update-module-docs
description: Keep the docs/ wiki and the in-package README.md files in step with code changes. Use after changing anything under rsc/ (commands, options, permissions, Config keys, task loops, webhooks, DMs, env vars, behaviour staff would notice), when adding or removing a feature package, or when the user asks to update or check the docs for a module.
---

# Update module docs

The bot is documented in two places that must agree with the code:

- **The wiki** in `docs/`: one page per feature package in `docs/modules/<package>.md`, plus cross-cutting pages (`architecture.md`, `configuration.md`, `staff-guide.md`, `development.md`, `deployment.md`, `operations.md`, `external-services.md`, `scripts.md`). `docs/README.md` is the index.
- **Package READMEs** in `rsc/<package>/README.md`, where they exist: a short command reference for that package. The wiki page links to it.

When code changes, update both in the same change. The code is the source of truth: if a doc disagrees with the code, fix the doc, never the other way round.

## Step 1: find what changed

Look at the diff (`git diff` and `git diff --staged`, or the files you just edited). For each changed file, work out its package from the path: `rsc/<package>/...`. Files directly under `rsc/` (`core.py`, `abc.py`, `checks.py`, `settings.py`, `logs.py`, `const.py`, `embeds.py`, `views.py`, `exceptions.py`, `pagination.py`) are cross-cutting and map to `docs/architecture.md`.

Special cases:

| Code | Docs |
|---|---|
| `rsc/lobbies/` | `docs/modules/lobbies.md`, and check `combines.md` and `devleague.md`, which describe the same flow |
| `rsc/moderator/thread.py` (`ThreadMixIn`) | `docs/modules/moderator.md` |
| `rsc/utils/trophy.py` (`TrophyMixIn`) | `docs/modules/utils.md` |
| `rsc/llm/` and `rsc/resources/rules/` | `docs/modules/llm.md` |
| `scripts/` | `docs/scripts.md` |
| `pyproject.toml`, `.pre-commit-config.yaml`, `tests/conftest.py` | `docs/development.md` |
| `tests/` only | No doc change unless test commands or setup changed |

## Step 2: decide which sections are affected

Read the changed code, then the current module page and README. Use this table to find every place a kind of change shows up:

| Kind of change | Module page section | Package README | Also update |
|---|---|---|---|
| Slash command added, removed, renamed, or its options changed | Commands | Yes | `staff-guide.md` if staff use it |
| Who can run a command (`default_permissions`, `bot_owner_required`, `elevated_role_required`, role checks) | Commands, "Who can run it" column | Yes, if it states permissions | `staff-guide.md` |
| New or changed day-to-day workflow | Using it | If it describes workflows | `staff-guide.md` |
| Config key added, removed, or default changed (`register_guild`, `init_custom`) | Configuration | If it lists settings | `configuration.md` |
| `tasks.loop` added, removed, or reschedule | Background work | No | `architecture.md` loop table; also add `.cancel()` in `cog_unload()` |
| Listener, persistent view, `DynamicItem`, or DMs sent | Background work | No | `architecture.md` if it's a new `DYNAMIC_ITEMS` entry |
| Webhook route or payload | Background work, How it works | If it documents webhooks | `architecture.md` web server table, `deployment.md` if networking changed |
| New external service, API endpoint, or env var | How it works | No | `external-services.md`; `development.md` `.env` table for env vars |
| Internal refactor with no visible effect | How it works, only if a named file, class or flow moved | No | Nothing else |
| A Gotcha fixed, or a new surprising behaviour | Gotchas | No | Nothing else |

If nothing in the table applies, the docs don't need changing. Say so and stop.

## Step 3: edit

- Edit only the sections that changed. Keep the page's existing order and headings.
- Use real names from the code: the `app_commands.Group` name plus the command `name=`, parameter names as declared, Config keys as registered.
- Take "Who can run it" from the actual checks in code, not from the README or the description string.
- Plain, direct prose. No emoji. Tables for commands. Link code with paths relative to the doc (`../../rsc/<package>/file.py` from `docs/modules/`).
- READMEs follow their existing style: a command list per group, one line each. Don't expand them into wiki pages.
- If the change removes the last thing a Gotcha described, delete that Gotcha.

### New package

Create `docs/modules/<package>.md` from the template below, add it to the table in `docs/modules/README.md`, add its settings to `docs/configuration.md`, and add its staff workflows to `docs/staff-guide.md`. A package README is optional; if you add one, link it from the page header.

```markdown
# <Module name>

**Package:** [rsc/<package>/](../../rsc/<package>/) · **Mixin(s):** `XMixIn` · **Details:** [package README](../../rsc/<package>/README.md)

One or two paragraphs: what this module does for the league, in plain terms.

## Using it
## Commands
## Configuration
## Background work
## How it works
## Gotchas
```

Omit a section only when it would be empty.

### Removed package

Delete its page, remove it from `docs/modules/README.md`, and remove its rows from `configuration.md`, `staff-guide.md`, `architecture.md` and `external-services.md`.

## Step 4: check

- `grep -rn "<old command or key name>" docs rsc/*/README.md` returns nothing stale.
- Every relative link you added points at a file that exists.
- Tell the user which doc files you changed and why, in one or two lines. Don't commit unless they ask.
