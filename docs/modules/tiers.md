# Tiers

**Package:** [rsc/tiers/](../../rsc/tiers/) · **Mixin(s):** `TierMixIn`

Tiers are the skill brackets of the league (for example Elite or Prospect). This module lists them, and gives the rest of the bot a shared way to look tiers up in the RSC API: tier IDs, standings, playoff hunts and season stats. It also keeps the list of tier names that backs tier autocomplete in every command that takes a `tier` argument.

Tiers are created and edited on the RSC website. The bot only reads them.

## Using it

Anyone can run `/tiers` to see the league's tiers as role mentions. Everything else in this module is used by other commands: when a command such as `/freeagents`, `/teams tier` or `/captains tier` offers tier suggestions as you type, those come from here.

Each tier needs a Discord role with exactly the same name as the tier. Most tier features also expect a free agent role named `<Tier>FA` (for example `EliteFA`). Admins create these roles by hand or through the sync tools in [admin](./admin.md).

## Commands

| Command | Who can run it | What it does |
| --- | --- | --- |
| `/tiers` | Anyone (server only) | Lists every tier in the league as a role mention, highest tier first. |

## Configuration

This module stores no settings. The league it reads tiers for is the guild's configured league (see [../configuration.md](../configuration.md)).

## Background work

None of its own. When the bot starts, `_setup_guild` in [core.py](../../rsc/core.py) calls `tiers(guild)` once for each guild that has an API and league configured, which fills the autocomplete cache.

## How it works

Everything lives in [tiers.py](../../rsc/tiers/tiers.py).

- `_tier_cache` is a per-guild list of tier names held in memory. `tiers()` refreshes it on every call through `merge_name_cache` ([utils/cache.py](../../rsc/utils/cache.py)). An unfiltered call replaces the list. A call filtered by name can only add to it. Order follows tier position, highest first, because `tiers()` sorts by `position` descending before caching.
- `tier_autocomplete` matches what the user typed as a case-insensitive substring and returns up to 25 choices. It returns nothing if the cache is empty.
- `is_valid_tier` checks a name against the cache only. It makes no API call.
- `tier_fa_roles` returns the `<Tier>FA` roles that exist in the guild.
- `tier_id_by_name` raises `ValueError` if the name matches no tier, or more than one.

RSC API calls (`TiersApi`):

| Method | Endpoint call | Used by |
| --- | --- | --- |
| `tiers()` | `tiers_list` (filtered by league) | Almost every module |
| `tier_by_id()` | `tiers_retrieve` | No callers in the cog |
| `tier_standings()` | `tiers_standings_list` | [stats](./stats.md), LLM agent tools |
| `tier_playoff_hunt()` | `tiers_playoffs_retrieve` | [stats](./stats.md) |
| `tier_player_stats()` | `tiers_player_stats_list` | Stats and LLM agent tools |
| `tier_team_stats()` | `tiers_team_stats_list` | Stats and LLM agent tools |
| `create_tier()` / `delete_tier()` | `tiers_create` / `tiers_destroy` | No callers in the cog |

`tier_player_stats` returns server-computed ranks (`goals_rank`, `points_rank`, and so on), so callers do not need to sort the league themselves.

## Gotchas

- `/tiers` stops at the first tier that has no matching Discord role and replies with an error instead of a partial list.
- If the API was unreachable when the bot started, the tier cache is empty. Tier autocomplete then offers nothing, and `/freeagents` rejects every tier as invalid until something calls `tiers()` again.
- Some commands that take a tier run `str.capitalize()` on it first (`/freeagents`, `/freeagent availability`, `/captains tier`). That lowercases everything after the first letter, so it only works for tier names with a single leading capital.
