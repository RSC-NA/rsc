# Development

How to get a working copy running, how to test it, and the conventions the codebase follows.

## Prerequisites

- Python 3.12 (the repo pins `3.12.12` in [.python-version](../.python-version); `pyproject.toml` allows 3.11 and up).
- [uv](https://docs.astral.sh/uv/). Every command below goes through it. Don't use pip: `requirements.txt` mixes hashes with git dependencies, and pip refuses that combination.
- A Discord application and bot token for a **test** bot, plus a test server you control. Never develop against the production bot.
- An RSC API key for the staging API (`https://staging-api.rscna.com/api/v1`), if you want the bot to do anything league-related.

## Set up the environment

```sh
git clone git@github.com:RSC-NA/rsc.git
cd rsc
uv sync                    # creates .venv with runtime + dev dependencies
uv run pre-commit install  # ruff, ty, codespell, and uv lock/export hooks
```

`uv sync --group scripts` adds the extra packages the one-off utilities in [scripts/](../scripts/) need (OpenCV, matplotlib, and so on). The bot doesn't need them.

Three dependencies come from git rather than PyPI (see `[tool.uv.sources]` in [pyproject.toml](../pyproject.toml)):

| Package | Repo | Used for |
|---|---|---|
| `rscapi` | [RSC-NA/rsc-api-client](https://github.com/RSC-NA/rsc-api-client) | Generated client for the RSC website API |
| `python-ballchasing` | [xentrick/python-ballchasing](https://github.com/xentrick/python-ballchasing) | ballchasing.com API client |
| `replay-parser` | [xentrick/python-replay-parser](https://github.com/xentrick/python-replay-parser) | Reading Rocket League `.replay` headers |

`[tool.ty.environment] extra-paths` points at local checkouts of `python-replay-parser` and `rsc-api-client` next to this repo, so `ty` can see their source. If you don't have them checked out there, `ty` still runs against the installed packages; adjust the paths if your layout differs.

## Run a development bot

The bot is a [Red-DiscordBot](https://docs.discord.red/en/stable/) cog, so you run Red and load the cog into it.

1. Create a Red instance once. The name `rsc` matches the VS Code launch config:

   ```sh
   uv run redbot-setup
   ```

2. Start it:

   ```sh
   uv run redbot rsc --dev --debug
   ```

   Or use the **Python: RedBot** configuration in [.vscode/launch.json](../.vscode/launch.json), which runs the same thing under the debugger.

3. In Discord, point Red at your working copy and load the cog. The path is the repo root, because the cog package is the `rsc/` folder inside it:

   ```
   [p]addpath /path/to/rsc
   [p]load rsc
   ```

4. Enable and sync the slash commands. Red keeps cog app commands disabled until you enable them:

   ```
   [p]slash enablecog RSC
   [p]slash sync
   ```

   Re-sync whenever a command's name, options, choices or description change. Code changes inside a command body need only a reload.

5. Configure the server (see [Configuration](configuration.md)): `/rsc url`, `/rsc key`, `/rsc league`. These commands are restricted to the bot owner, which on a dev instance is you.

After editing code, `[p]reload rsc` picks it up. A reload runs `cog_unload()` then `cog_load()`, which cancels and restarts every task loop and re-registers the persistent buttons. See [Architecture: lifecycle](architecture.md#lifecycle).

### Testing the website webhooks locally

Combines and Dev League lobbies are driven by the website posting to the bot's web server on `localhost:8008`. Two scripts fake those posts with the sample payloads in [data/combines/](../data/combines/) and [data/devleague/](../data/devleague/):

```sh
uv run --group scripts scripts/combines_lobby.py start <guild_id>
uv run --group scripts scripts/combines_lobby.py teardown <guild_id> <lobby_id>
uv run --group scripts scripts/devleague_lobby.py start <guild_id>
```

Run them with `--help` for options such as the number of games to start. Combines must be started in the guild (`/combinemanager start`) or the bot answers `503`.

## Tests

```sh
uv run pytest                     # unit tests only (the default)
uv run pytest tests/test_dm.py    # one file
uv run pytest --cov               # with coverage, written to /tmp/rsc.coverage
uv run pytest -m integration      # live calls to the staging API
```

- Unit tests mock Discord and the API. They need no network and have a 10 second per-test timeout.
- Integration tests (the `tests/test_*_api.py` files and a few others marked `integration`) call the real staging API. They read credentials from `.env` and are excluded unless you pass `-m integration`. If staging is down or answers 5xx they are reported as skipped, not failed.
- To test against an API change that isn't on staging yet, run the website locally and point the tests at it:

  ```sh
  RSC_TEST_API_URL=http://127.0.0.1:8000/api/v1 uv run pytest -m integration
  ```

### `.env`

`.env` is git-ignored. Tests and most scripts load it with `python-dotenv`.

| Variable | Used by |
|---|---|
| `RSC_API_KEY` | Integration tests, scripts |
| `RSC_API_URL` | Integration tests, scripts |
| `RSC_TEST_API_URL` | Optional. Overrides the staging URL for integration tests |
| `OPENAI_API_KEY`, `OPENAI_API_ORG` | LLM tests that call OpenAI |
| `BALLCHASING_KEY` | ballchasing scripts |

The running bot doesn't read `.env`. In Discord, its credentials live in Red's per-guild config, set with commands.

## Checks

The pre-commit hooks run all of these. To run them by hand:

```sh
uv run ruff check .
uv run ruff format .
uv run ty check            # the type checker; mypy config in pyproject is legacy, don't use it
uv run pre-commit run --all-files
```

The uv hooks also keep `uv.lock` in sync with `pyproject.toml` and regenerate [requirements.txt](../requirements.txt) and [requirements-dev.txt](../requirements-dev.txt) from the lock. Commit those files whenever dependencies change; production installs from `requirements.txt`.

`uv audit` is not a hook: Red pins several packages with `==` (aiohttp, click, idna, markdown, orjson, pygments), so the audit can never pass. Run it by hand to see whether Red has relaxed those pins.

## Conventions

These are the house rules visible across the codebase. Follow the surrounding code where it is more specific.

- **One mixin per feature.** New features go in a package under `rsc/` with a `XMixIn(RSCMixIn)` class, added to the base list of `RSC` in [rsc/core.py](../rsc/core.py). Anything another mixin needs to call is declared as an abstract method on `RSCMixIn` in [rsc/abc.py](../rsc/abc.py). See [Architecture](architecture.md).
- **Slash commands.** Commands are `app_commands`, grouped with `app_commands.Group`. Set `default_permissions` for visibility, and use the checks in [rsc/checks.py](../rsc/checks.py) for real enforcement: `bot_owner_required()` for operator-only settings, `elevated_role_required(...)` for league staff positions held in the API.
- **API calls** go through `async with self.api_client(guild) as client:`, never a new `ApiClient`. Catch `ApiException` at the call site and re-raise it as an `RscException` (or, for transactions, the specific subclass `translate_api_error()` in [rsc/exceptions.py](../rsc/exceptions.py) picks from the API's `detail` message), so callers get a clean error.
- **Logging.** Use `GuildLogAdapter` from [rsc/logs.py](../rsc/logs.py) and pass `guild=` (and `match=`) so lines are prefixed with the server name. Loggers are named `red.rsc.<module>`.
- **Direct messages** always go through the one shared queue, `self._dm_helper.enqueue(...)`. Never create a second `DMHelper`; mark time-sensitive DMs `urgent=True`.
- **Discord UI.** New cards use Components V2 (`discord.ui.LayoutView`). Mentions meant to ping must be in message content or a V2 `TextDisplay`, never only inside an embed. Error and cancelled states use a red accent, timeouts yellow. See [plans/discord-ui-refresh.md](plans/discord-ui-refresh.md) for the full rules.
- **Persistent buttons** that must survive a restart are `DynamicItem`s with the state encoded in the `custom_id`, registered in `DYNAMIC_ITEMS` in [rsc/core.py](../rsc/core.py).
- **Typing.** Code is fully annotated and checked with `ty`. Narrow types with `isinstance`, generics or enums, not `typing.cast()`.
- **Preview/test commands** take a free-text option and dispatch on its value, so adding a case doesn't change the command signature and force a re-sync.
- **Tests.** Every behaviour change gets a unit test in `tests/test_<module>_*.py`. API contract changes get an integration test in the matching `*_api.py`.
- **Module READMEs.** Each feature package can carry a `README.md` with its command list. Update it in the same change as the commands.
