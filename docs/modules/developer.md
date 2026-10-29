# Developer

**Package:** [rsc/developer/](../../rsc/developer/) · **Mixin(s):** `DeveloperMixIn`

Debugging helpers for whoever runs the bot. `/logs tail` shows the end of the bot's current log file in Discord, so you can check recent errors without a shell on the host. `/devtest` is a no-op command for checking that slash commands reach the bot.

## Using it

- After something fails, run `/logs tail` to see the last 1984 bytes of the log, privately.
- `/devtest` replies "Developer test successful!" if the bot is receiving commands.

## Commands

| Command | Who can run it | What it does |
|---|---|---|
| `/devtest` | Manage Server | Private "Developer test successful!" reply. |
| `/logs tail` | Manage Server | Private code block with the last 1984 bytes of Red's latest log file. |

## Configuration

None.

## Background work

None.

## How it works

- [developer.py](../../rsc/developer/developer.py): `DeveloperMixIn`.

`get_latest_log_file()` walks the root logger's handlers for Red's own `RotatingFileHandler` (from `redbot.logging`) whose `baseStem` is `latest`, and returns its file path. The command seeks to `max(0, size - 1984)`, reads the rest, and decodes it as UTF-8 with replacement characters, since the cut can land mid-character.

## Gotchas

- Anyone with Manage Server can read the tail of the bot's log, which can include API request and response details at debug level.
- If no Red file handler is found, the error reply is public, not private.
