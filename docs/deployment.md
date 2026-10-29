# Deployment

How the production bot is installed and updated. Today it runs on a VPS from a Python virtual environment; a move to Docker is planned (see [Future: Docker](#future-docker)).

## What production consists of

- A Linux VPS.
- A Python 3.12 virtual environment containing Red-DiscordBot 3.5.24 and this cog's dependencies.
- One Red instance (the bot account) that has joined every RSC server it serves. Each server is a guild with its own API URL, key and league configured.
- The cog itself, installed from this GitHub repo through Red's Downloader.
- Red's data directory (`~/.local/share/Red-DiscordBot` by default), which holds the instance config, every guild's `Config` values, and the installed cog code.
- Optionally, the RSC website on the same host or reachable through a local proxy, so it can post lobby webhooks to `localhost:8008`.

## First install

1. **Create the environment.** Install Python 3.12 and uv, then make a venv and install Red into it:

   ```sh
   uv venv ~/redenv --python 3.12
   uv pip install --python ~/redenv/bin/python Red-DiscordBot==3.5.24
   ```

   The Red version must match the `red-discordbot` pin in [pyproject.toml](../pyproject.toml): it pins discord.py, aiohttp and others that the cog is tested against.

2. **Create the Red instance.**

   ```sh
   ~/redenv/bin/redbot-setup
   ```

   Pick an instance name and data location. You need the bot token from the Discord developer portal. Enable the privileged gateway intents for the bot there, as Red's install guide describes; the cog reads member lists and roles.

3. **Install the cog's Python dependencies.** Red's Downloader doesn't install them. Use uv, because `requirements.txt` mixes hashes with git dependencies and pip refuses that:

   ```sh
   uv pip install --python ~/redenv/bin/python -r requirements.txt
   ```

   Run this from a checkout of the repo at the commit you're deploying. Repeat it whenever `requirements.txt` changes.

4. **Start Red** (`~/redenv/bin/redbot <instance>`), then install and load the cog from Discord:

   ```
   [p]load downloader
   [p]repo add RSCBot https://github.com/RSC-NA/rsc.git [branch]
   [p]cog install RSCBot rsc
   [p]load rsc
   [p]slash enablecog RSC
   [p]slash sync
   ```

5. **Configure each server.** See [Configuration](configuration.md). At minimum, in every guild: `/rsc url`, `/rsc key`, `/rsc league`. Then work through the feature settings that guild uses.

### Keeping Red running

Run Red under something that restarts it when it exits and on reboot, so a crash or VPS restart doesn't take the bot down. Red's own guide shows a systemd unit for this ([Linux autostart](https://docs.discord.red/en/stable/autostart_systemd.html)). `[p]restart` and `[p]shutdown` rely on the supervisor to bring the bot back.

## Updating

For most changes:

```
[p]cog update rsc
```

Red pulls the repo and reloads the cog. Then check:

- **Did `requirements.txt` change?** Install it into the venv (step 3 above) *before* updating, or the reload fails on a missing import.
- **Did any slash command's name, options, choices or description change?** Run `[p]slash sync`. Discord clients may take a moment to show the change.
- **Did the Red version pin change?** Upgrade Red in the venv and restart the bot rather than reloading.
- **Is a long DM batch in progress?** A reload discards the queued DMs, it doesn't send them. Wait for the batch to finish.

A reload re-runs setup for every guild. Watch the log for `Finished preparing caches.` and for per-guild setup errors (see [Operations](operations.md)).

To roll back, pin the repo to an earlier commit or branch with Downloader, or check out the earlier commit and reinstall, then reload.

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

This makes the Red data directory sensitive: protect it and its backups accordingly.

## Backups

[scripts/bot_backup.sh](../scripts/bot_backup.sh) archives `~/.local/share/Red-DiscordBot` to `~/backup/rsc_bot_backup.tar.gz` and replaces the copy in the `gs://rsc-storage-bucket` Google Cloud Storage bucket. It needs `gcloud` authenticated on the host. Run it on a schedule (for example from cron). Only one copy is kept in the bucket, so each run overwrites the last.

To restore, stop the bot, extract the archive over the data directory, and start the bot again.

## Future: Docker

Moving to a container is planned but not done. Things the image and compose file will need to handle:

- Python 3.12 with Red pinned to the version in `pyproject.toml`, and `requirements.txt` installed with uv.
- Red's data directory on a persistent volume, since it holds every guild's settings and the installed cog.
- The bot token passed in at runtime, not baked into the image.
- The webhook server: it binds to `localhost` inside the container, so the website can't reach it through a published port until the bind address is made configurable, or the website runs in the same network namespace.
- A restart policy in place of the systemd supervisor.
- The backup script running against the volume.

When this lands, update this page and [Operations](operations.md).
