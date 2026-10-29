# Franchises

**Package:** [rsc/franchises/](../../rsc/franchises/) · **Mixin(s):** `FranchiseMixIn` · **Details:** [package README](../../rsc/franchises/README.md)

A franchise is an organisation run by a General Manager (GM), optionally with Assistant GMs (AGMs). It owns one team in each tier it plays in. This module lists the league's franchises. It also wraps the RSC API's franchise endpoints so other modules can look up GMs, AGMs and logos, and create, rebrand or transfer franchises.

The admin commands that change franchises (`/admin franchise ...` and `/admin agm ...`) live in the [admin](./admin.md) module. They call the helpers described here.

## Using it

Anyone can run `/franchises` to see every franchise with its prefix and GM. Franchise names you type into other commands (for example `/teams franchise`, `/captains franchise`, `/transactions tools validatefutures`) autocomplete from this module's cache.

Admins create, rebrand, transfer franchises and manage AGMs with `/admin franchise create|rebrand|transfer|logo|addteam|delteam` and `/admin agm add|remove`. See [admin](./admin.md).

## Commands

| Command | Who can run it | What it does |
| --- | --- | --- |
| `/franchises` | Anyone (server only) | Lists every franchise with its prefix, name and GM. The GM is shown as a mention if they are in the server, otherwise by their RSC name, or "None" if the franchise has no GM. |

## Configuration

This module stores no settings. It reads the guild's configured league and API host (see [../configuration.md](../configuration.md)).

## Background work

None of its own. On startup `_setup_guild` in [core.py](../../rsc/core.py) calls `franchises(guild)` for each guild with an API and league configured, which fills the autocomplete cache.

## How it works

Everything lives in [franchises.py](../../rsc/franchises/franchises.py). [views.py](../../rsc/franchises/views.py) is empty.

- `_franchise_cache` is a per-guild list of franchise names, sorted alphabetically. It holds names only. `franchises()` refreshes it on every call through `merge_name_cache`. An unfiltered call replaces the list, while a filtered call can only add to it.
- `franchise_autocomplete` returns the first 25 names when nothing is typed, otherwise up to 25 case-insensitive substring matches.
- `fetch_franchise` and `franchise_gm_by_name` look a franchise up by name and raise `ValueError` if more than one matches.
- `franchise_logo` returns the full logo URL (API host joined with the logo path), or `None` if the franchise has no logo. Team rosters, franchise team lists and transaction cards use it.

AGM helpers:

- `add_agm` / `remove_agm` send both the AGM and the executor by Discord ID. The API requires the executor to hold the Admin elevated role for the league, otherwise it answers 403. Adding an existing AGM is a no-op that still succeeds. Removing someone who is not an AGM of that franchise answers 404.
- `franchises_agm_of`, `agm_franchise_of` and `agm_franchise_map` find AGMs from the `agms` list that `franchises_list` returns inline. The API has no reverse lookup. `agm_franchise_map` builds one map for the whole league from a single request, and bulk role syncs must use it instead of calling `agm_franchise_of` once per member.
- `agm_franchise_map` raises `RuntimeError` if the API returns no franchises at all. Callers treat a missing key as "not an AGM", so an empty answer would otherwise strip every AGM in a bulk sync.
- If one person is listed as AGM on two franchises, the first franchise in list order wins and a warning is logged.

RSC API calls (`FranchisesApi`):

| Method | Endpoint call |
| --- | --- |
| `franchises()` | `franchises_list` (filters: prefix, GM name, GM Discord ID, name, tier, tier name; always the guild's league) |
| `franchise_by_id()` | `franchises_retrieve` |
| `create_franchise()` | `franchises_create` |
| `rebrand_franchise()` | `franchises_rebrand_update` |
| `transfer_franchise()` | `franchises_transfer_franchise_update` |
| `upload_franchise_logo()` | `franchises_upload_logo_update` |
| `add_agm()` / `remove_agm()` | `franchises_add_agm_update` / `franchises_remove_agm_update` |
| `franchise_logo()` | `franchises_logo_retrieve` |

## Gotchas

- The API cannot delete franchises, and `delete_franchise` always raises `RscException("The API does not support deleting franchises.")`. `/admin franchise delete` says so up front; see [admin](./admin.md).
- A franchise with no GM is normal (GMs are staff records now), so `franchise.gm` can be null anywhere.
- `franchises()` with no filter is a live API request every time. The cache only holds names and is not used to answer queries.
