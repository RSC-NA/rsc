# RSC Bot documentation

The RSC bot runs league operations for the [Rocket Soccar Confederation](https://www.rocketsoccarconfederation.com/) Discord servers: sign-ups, rosters and transactions, match reporting, stats, Combines and Dev League lobbies, and a rules assistant. It is a single [Red-DiscordBot](https://docs.discord.red/en/stable/) cog backed by the RSC website's API.

## Start here

| If you are… | Read |
|---|---|
| League staff or a player wanting to know what the bot does | [Staff guide](staff-guide.md) |
| Setting up the bot in a server | [Configuration](configuration.md) |
| Running the production bot | [Deployment](deployment.md), then [Operations](operations.md) |
| A developer new to the codebase | [Development](development.md), then [Architecture](architecture.md) |
| Looking for one feature | [Modules](modules/README.md) |

## Pages

**Using the bot**

- [Staff guide](staff-guide.md): what each role does with the bot, the server setup order, and the season calendar.
- [Configuration](configuration.md): every per-server setting, the roles and channels the bot expects, and the state it keeps.

**Running the bot**

- [Deployment](deployment.md): installing on the VPS, updating, the webhook server, secrets, backups, and the planned Docker move.
- [Operations](operations.md): logs, health checks, and fixes for common problems.
- [External services](external-services.md): the RSC API, the Dev League site, ballchasing.com and OpenAI.
- [Scripts](scripts.md): the one-off utilities in `scripts/`.

**Working on the bot**

- [Development](development.md): local setup, running a dev bot, tests, checks and code conventions.
- [Architecture](architecture.md): how the cog is assembled, its lifecycle, API access, permissions, background work and UI.
- [Modules](modules/README.md): one page per feature package.

**Records**

- [Plans and audits](plans/README.md): the code audit and the Discord UI refresh plan.
- [Integration notes](integrations/README.md): hand-off documents for the systems the bot talks to.

## Conventions in these docs

- Commands are written as Discord shows them, for example `/transactions sign`. `[p]` stands for the bot's text-command prefix, used for Red's own commands such as `[p]reload rsc`.
- "Manage Server" and similar refer to Discord permissions. "Bot owner" means the bot's operator as configured in Red.
- Code links are relative to the repo. The code is the source of truth; if a page disagrees with it, fix the page.
