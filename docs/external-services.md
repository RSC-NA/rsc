# External services

Everything the bot talks to besides Discord, what it uses each one for, and where it's configured. All of these are outbound HTTPS calls, except the website's lobby webhooks, which come in on `localhost:8008`.

| Service | Used for | Configured by | Modules |
|---|---|---|---|
| RSC website API | Almost everything: members, league players, teams, franchises, tiers, seasons, matches, transactions, stats, trackers, staff positions, events | `/rsc url`, `/rsc key`, `/rsc league` per guild | Nearly all |
| Dev League / Combines website | Combines check-in and lobby lookups; Dev League check-in and status; lobby webhooks into the bot | `/combinemanager api` per guild; Dev League URL hard-coded | [combines](modules/combines.md), [devleague](modules/devleague.md), [lobbies](modules/lobbies.md) |
| ballchasing.com | Uploading match replays into groups, deduplicating them, linking results | `/ballchasing key`, `/ballchasing toplevelgroup` per guild | [ballchasing](modules/ballchasing.md) |
| OpenAI | The rules assistant (`/ask`, mentions) and ticket summaries | `/llm apikey`, `/llm organization` per guild | [llm](modules/llm.md) |
| Sentry | Error reporting from the production bot | `SENTRY_DSN` environment variable on the host | [rsc/\_\_init\_\_.py](../rsc/__init__.py) |

## RSC website API

- **Client:** `rscapi`, generated from the website's OpenAPI schema and maintained in [RSC-NA/rsc-api-client](https://github.com/RSC-NA/rsc-api-client). Installed from git (see `[tool.uv.sources]` in [pyproject.toml](../pyproject.toml)).
- **Hosts:** production `https://api.rscna.com/api/v1`, staging `https://staging-api.rscna.com/api/v1`. Each guild points at one with `/rsc url`.
- **Auth:** an `Api-Key` header, set per guild with `/rsc key`. The key's permissions on the website decide what the bot may change.
- **Connection:** one long-lived client per guild with automatic retries on server and connection errors (never on `POST`). See [Architecture: talking to the RSC API](architecture.md#talking-to-the-rsc-api).
- **Events feed:** the bot polls `GET /api/v1/integrations/events/` to mirror website activity into Discord and react to it, for example announcing trades made on the website. See [events](modules/events.md) and the hand-off record in [integrations/events-api-requests.md](integrations/events-api-requests.md).
- **Website links:** match and standings links on cards are built from the API URL with its `/api/...` path removed ([rsc/utils/website.py](../rsc/utils/website.py)).
- **When the API changes:** regenerate `rsc-api-client`, bump it here (`uv lock --upgrade-package rscapi`), and run the integration tests (`uv run pytest -m integration`). The unit test [tests/test_api_endpoint_contracts.py](../tests/test_api_endpoint_contracts.py) scans the bot's source and fails if any `rscapi` method it calls no longer exists in the installed client, so a regenerated client that renamed an endpoint is caught without network access.

## Dev League and Combines website

Combines and Dev League run on `devleague.rscna.com`, a separate site from the main RSC website.

- **Into the bot:** when a lobby starts or a game finishes, the site posts to the bot's web server: `/combines_match`, `/combines_event`, `/devleague_match`, `/devleague_event` on `localhost:8008`. These routes have no authentication, so the port must not be exposed publicly. See [lobbies](modules/lobbies.md) and [Deployment: network](deployment.md#network-and-the-webhook-server).
- **From the bot:** Combines calls `check_in`, `check_out`, `active` and `lobby/<id>` on the URL set with `/combinemanager api`. Dev League calls `/api/status`, `/api/check_in` and `/api/check_out` on the hard-coded `https://devleague.rscna.com`.
- Sample webhook payloads for testing are in [data/combines/](../data/combines/) and [data/devleague/](../data/devleague/).

## ballchasing.com

- **Client:** `python-ballchasing`, from [xentrick/python-ballchasing](https://github.com/xentrick/python-ballchasing).
- **Auth:** an API token per guild, `/ballchasing key`. Reload the cog after setting it.
- **Layout:** replays go under the guild's top-level group, organised into sub-groups per match. The bot fingerprints replays (with `replay-parser`, from [xentrick/python-replay-parser](https://github.com/xentrick/python-replay-parser)) so the same game isn't uploaded twice.
- Many maintenance scripts work against ballchasing groups directly; see [Scripts](scripts.md#ballchasingcom).

## OpenAI

- **Client:** the official `openai` Python SDK, default endpoint.
- **Auth:** an API key per guild (`/llm apikey`), plus an organization (`/llm organization`) for ticket summaries.
- **Calls:** the Responses API for the rules assistant and its rules sub-agent (`store=False`), Chat Completions for `/llm summarize`. Models are set in [rsc/llm/config.py](../rsc/llm/config.py).
- **Data:** questions and the rule text and league data the assistant looks up are sent to OpenAI. This is stated in the cog's end-user data statement in [rsc/info.json](../rsc/info.json).
- **Cost control:** per-user cooldown and daily caps, a per-guild daily cap, and token ceilings per question. See [llm](modules/llm.md).

## Sentry

- **Client:** the `sentry-sdk` Python package, started in `init_sentry()` in [rsc/\_\_init\_\_.py](../rsc/__init__.py) when the cog loads.
- **Project:** `rsc-discord-bot` in the `individual-s2` Sentry organization.
- **Enabled by:** the `SENTRY_DSN` environment variable. Only the production host sets it, so dev instances report nothing. `SENTRY_ENVIRONMENT` overrides the environment tag (default `production`).
- **What it reports:** errors only, no tracing. Every error-level log record becomes an event, which covers command and slash command errors (Red logs them with `log.exception`) and failures the cog logs itself. Lower-level log lines go along as breadcrumbs.
- **Data:** `send_default_pii` is off, so Sentry doesn't attach user IPs or request bodies. Exception messages and log lines are sent as written.

## Google Cloud Storage

Used only by [scripts/bot_backup.sh](../scripts/bot_backup.sh), which uploads Red's data directory to `gs://rsc-storage-bucket`. Not used by the bot itself.

## Fixed links

A few links shown to members are hard-coded in [rsc/const.py](../rsc/const.py) and module code: the behaviour rules Google Doc, the tracker Google Sheet, and the RSC website's replay upload page. Update them there if they move.
