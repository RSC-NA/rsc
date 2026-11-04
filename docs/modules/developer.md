# Developer

**Package:** [rsc/developer/](../../rsc/developer/) · **Mixin(s):** `DeveloperMixIn`

Debugging helpers for whoever runs the bot. `/logs tail` shows the end of the bot's current log file in Discord, and `/logs traceback` shows the full traceback of a recent exception, so you can see what went wrong without a shell on the host. `/devtest` is a no-op command for checking that slash commands reach the bot.

## Using it

- After something fails, run `/logs traceback` to see the newest exception the bot logged, privately. Pick an older one from the `exception` autocomplete, which lists each by age, logger and exception line. A traceback too long for one message shows its end, where the raise site is, with the full text attached as a file.
- Run `/logs tail` to see the last 1984 bytes of the log, privately, for the lines around an error.
- `/devtest` replies "Developer test successful!" if the bot is receiving commands.

## Commands

| Command | Who can run it | What it does |
|---|---|---|
| `/devtest` | Manage Server | Private "Developer test successful!" reply. |
| `/logs tail` | Manage Server | Private code block with the last 1984 bytes of Red's latest log file, starting at a whole line. |
| `/logs traceback [exception]` | Manage Server | Private reply with a recent exception's logger, time, message and traceback. Without `exception`, the newest. |

## Configuration

None.

## Background work

None.

## How it works

- [developer.py](../../rsc/developer/developer.py): `DeveloperMixIn` and `tail_code_block()`.
- [recorder.py](../../rsc/developer/recorder.py): `ExceptionRecorder` and `CapturedException`.

`get_latest_log_file()` walks the root logger's handlers for Red's own `RotatingFileHandler` (from `redbot.logging`) whose `baseStem` is `latest`, and returns its file path. `/logs tail` reads the last 1984 bytes plus one, drops everything up to the first newline so the block starts on a whole line, and decodes it as UTF-8 with replacement characters, since the cut can land mid-character.

`ExceptionRecorder` is a `logging.Handler` that `DeveloperMixIn.__init__` adds to the root logger and `RSC.cog_unload()` removes. It keeps the last 25 log records that carry an exception (`log.exception(...)`, or `exc_info=` as discord.py passes for task loop and view errors), from any logger, with an id, time, logger name, message and formatted traceback. Red's `[p]traceback` only sees command errors and failed package loads; every one of those is also logged with the exception, so the recorder sees them too. 25 is the most choices Discord autocomplete shows.

Both commands render through `tail_code_block()`, which keeps the end of the text, cuts at a line boundary to fit Discord's 2000-character message limit, and puts a zero-width space between backticks so a log line can't close the code block early.

## Gotchas

- Anyone with Manage Server can read the tail of the bot's log and the stored tracebacks, which can include API request and response details.
- `/logs traceback` only sees exceptions logged while the cog is loaded. Its history starts empty when the cog loads or reloads, and holds the last 25.
