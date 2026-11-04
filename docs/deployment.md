# Deployment

How the production bot is installed and updated. Today it runs on a VPS from a uv-managed virtual environment under systemd; a move to Docker is planned (see [Future: Docker](#future-docker)).

## What production consists of

- A Debian VPS, with the bot running as the `nickm` user.
- A checkout of this repo at `~/repos/rsc`, and the virtual environment `uv sync --locked --no-dev` builds from it at `~/repos/rsc/.venv`. That venv holds Python 3.11.15, Red-DiscordBot 3.5.24 and every runtime dependency, exactly as [uv.lock](../uv.lock) pins them. 3.11 is the newest Python Red 3.5.24 supports.
- One Red instance, `rscbot2` (the bot account), that has joined every RSC server it serves. Each server is a guild with its own API URL, key and league configured.
- The systemd unit `red2@rscbot2.service`, an instance of the `/etc/systemd/system/red2@.service` template. Its drop-in, `/etc/systemd/system/red2@rscbot2.service.d/override.conf`, sets the interpreter and the Sentry DSN (see [The systemd unit](#the-systemd-unit)).
- The cog itself, installed from this GitHub repo through Red's Downloader.
- Red's data directory (`~/.local/share/Red-DiscordBot`), which holds every guild's `Config` values and the installed cog code, and Red's instance registry (`~/.config/Red-DiscordBot/config.json`), which maps each instance name to its data path.
- Two other Red instances on the same host, `RSCBot` and `RSC6Mans`, run from their own `red@.service` units. They share the instance registry and the data directory root with `rscbot2`, so anything that rewrites `config.json` (such as `redbot-setup`) affects all three.
- Optionally, the RSC website on the same host or reachable through a local proxy, so it can post lobby webhooks to `localhost:8008`.

## First install

1. **Install uv and build the environment.** Clone the repo and let uv build the venv. It downloads Python 3.11.15 (pinned in [.python-version](../.python-version)) if that version isn't installed, then installs Red and the cog's dependencies from `uv.lock`:

   ```sh
   curl -LsSf https://astral.sh/uv/install.sh | sh
   git clone https://github.com/RSC-NA/rsc.git ~/repos/rsc
   cd ~/repos/rsc && uv sync --locked --no-dev
   ```

   `red-discordbot` is a dependency in [pyproject.toml](../pyproject.toml), so this installs Red too. Red's Downloader doesn't install the cog's dependencies, so this venv is the only place they come from.

2. **Create the Red instance.** Back up `~/.config/Red-DiscordBot/config.json` first, because `redbot-setup` rewrites it and other instances on the host depend on it.

   ```sh
   ~/repos/rsc/.venv/bin/redbot-setup
   ```

   Pick an instance name and data location. You need the bot token from the Discord developer portal. Enable the privileged gateway intents for the bot there, as Red's install guide describes; the cog reads member lists and roles.

3. **Run it under systemd** with a drop-in that points at the venv and sets the Sentry DSN. See [The systemd unit](#the-systemd-unit).

4. **Start Red**, then install and load the cog from Discord:

   ```
   [p]load downloader
   [p]repo add RSCBot https://github.com/RSC-NA/rsc.git [branch]
   [p]cog install RSCBot rsc
   [p]load rsc
   [p]slash enablecog RSC
   [p]slash sync
   ```

5. **Configure each server.** See [Configuration](configuration.md). At minimum, in every guild: `/rsc url`, `/rsc key`, `/rsc league`. Then work through the feature settings that guild uses.

### The systemd unit

`red2@.service` sets `User`, `Restart=always` and a default `ExecStart`. The instance's drop-in replaces the interpreter and adds the Sentry DSN, so errors go to the `rsc-discord-bot` Sentry project (see [External services](external-services.md#sentry)):

```
# /etc/systemd/system/red2@rscbot2.service.d/override.conf
[Service]
Environment=SENTRY_DSN=<dsn>
ExecStart=
ExecStart=/home/nickm/repos/rsc/.venv/bin/python -O -m redbot --no-prompt --owner 138778232802508801 %I
```

The empty `ExecStart=` clears the command inherited from the template; without it systemd sees two commands and refuses to start the unit. Leaving the template alone keeps the change to this one instance. After editing the drop-in, run `sudo systemctl daemon-reload`, then check `systemctl show red2@rscbot2.service -p ExecStart` lists only the `.venv` interpreter. Without the DSN the bot runs normally and reports nothing.

`Restart=always` brings the bot back after a crash, a VPS reboot, `[p]restart` and `[p]shutdown`. Logs go to `journalctl -u red2@rscbot2.service` as well as Red's own log files (see [Operations](operations.md)).

### Installing with pip instead

A host without uv can install the same pinned set into any Python 3.11 virtual environment:

```sh
<venv>/bin/python -m pip install --no-deps -r requirements.txt
```

[requirements.txt](../requirements.txt) is exported from `uv.lock` with every package pinned, so pip has nothing to resolve. `--no-deps` is required: `pyproject.toml` overrides some of Red's exact pins (aiohttp and others, for security fixes), and without it pip refuses Red's metadata. Afterwards `pip check` lists those Red pins as mismatches. That is expected.

## Updating

For most changes:

```
[p]cog update rsc
```

Red pulls the repo and reloads the cog. Then check:

- **Did `uv.lock` change?** Run `cd ~/repos/rsc && git pull && uv sync --locked --no-dev` *before* updating, or the reload fails on a missing import.
- **Did any slash command's name, options, choices or description change?** Run `[p]slash sync`. Discord clients may take a moment to show the change.
- **Did the Red version pin change?** Run the same `uv sync`, then `sudo systemctl restart red2@rscbot2.service` rather than reloading.
- **Is a long DM batch in progress?** A reload discards the queued DMs, it doesn't send them. Wait for the batch to finish.

A reload re-runs setup for every guild. Watch the log for `Finished preparing caches.` and for per-guild setup errors (see [Operations](operations.md)).

To roll back, pin the repo to an earlier commit or branch with Downloader, check out the same commit in `~/repos/rsc` and run `uv sync --locked --no-dev`, then reload.

## Network and the webhook server

The cog starts an HTTP server on `localhost:8008` for the website's Combines and Dev League webhooks. It binds to loopback only:

- If the website runs on the same VPS, it posts to `http://localhost:8008/...` directly.
- If it runs elsewhere, put a reverse proxy on the VPS that forwards those routes to `localhost:8008`, and restrict who can reach it. The routes have no authentication of their own.
- Nothing else needs inbound access. Everything else the bot does is outbound HTTPS (Discord, the RSC API, ballchasing.com, OpenAI).

Routes and payloads are described in [Architecture: web server](architecture.md#web-server) and the [lobbies](modules/lobbies.md) page.

## Secrets

The production bot keeps no secrets in files of its own. They live in Red's data directory:

| Secret | Where it's set |
|---|---|
| Discord bot token | `redbot-setup`, stored by Red |
| RSC API key and URL | `/rsc key`, `/rsc url`, per guild |
| ballchasing.com API key | `/ballchasing key`, per guild |
| OpenAI key and organization | `/llm apikey`, `/llm organization`, per guild |
| Combines lobby API URL | `/combinemanager api`, per guild. The Dev League API URL is hard-coded |
| Sentry DSN | `SENTRY_DSN` environment variable on the host. It only allows sending events, but keep it out of the repo |

This makes the Red data directory sensitive: protect it and its backups accordingly.

## Backups

[scripts/bot_backup.sh](../scripts/bot_backup.sh) archives Red's data directory (`~/.local/share/Red-DiscordBot`) and its instance registry (`~/.config/Red-DiscordBot/config.json`, which maps each instance name to its data path) to `~/backup/rsc_bot_backup.tar.gz`, then overwrites the copy in the `gs://rsc-storage-bucket` Google Cloud Storage bucket. If `tar` fails, the bucket keeps the previous backup. It needs `gcloud` authenticated on the host. Run it on a schedule (for example from cron). Only one copy is kept in the bucket, so each run overwrites the last.

To restore, stop the bot, run `tar -xzf rsc_bot_backup.tar.gz -C /` as the bot's user (the archive stores both directories by absolute path), and start the bot again.

## Future: Docker

Moving to a container is planned but not done. Things the image and compose file will need to handle:

- The venv built with `uv sync --locked --no-dev`, which brings Python 3.11.15 and the pinned Red.
- Red's data directory on a persistent volume, since it holds every guild's settings and the installed cog.
- The bot token passed in at runtime, not baked into the image.
- The webhook server: it binds to `localhost` inside the container, so the website can't reach it through a published port until the bind address is made configurable, or the website runs in the same network namespace.
- A restart policy in place of the systemd supervisor.
- The backup script running against the volume.

When this lands, update this page and [Operations](operations.md).
