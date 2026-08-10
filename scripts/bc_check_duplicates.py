#!/usr/bin/env python3
"""Find replays of the same game sitting in one ballchasing group.

Two players' recordings of the same match share a MatchGUID but differ in every
other respect, so before GUID based deduplication existed both copies could end
up in the group. This reports those pairs.

It also prints each replay's rocket_league_id alongside its match_guid. If the
two duplicates share a rocket_league_id, the bot could dedup from the cheap
shallow listing (1 request) instead of a deep fetch (1 + N requests), since
rocket_league_id is the only identifier ballchasing returns in a group listing.

    ./scripts/bc_check_duplicates.py <match_group_id>
    ./scripts/bc_check_duplicates.py <match_day_group_id> --recurse
"""

import argparse
import asyncio
import os
import sys
from collections import defaultdict

import ballchasing
from dotenv import load_dotenv

BALLCHASING_URL = "https://ballchasing.com/group/"


async def leaf_groups(bapi: ballchasing.Api, group: str, recurse: bool) -> list[tuple[str, str]]:
    """Groups to inspect, as (id, name)."""
    if not recurse:
        return [(group, group)]

    children = [g async for g in bapi.get_groups(group=group)]
    if not children:
        return [(group, group)]
    return [(c.id, c.name) for c in children]


async def check(bapi: ballchasing.Api, group_id: str, name: str) -> tuple[int, int]:
    replays = [r async for r in bapi.get_group_replays(group_id=group_id, deep=True)]

    by_guid: dict[str, list[ballchasing.models.Replay]] = defaultdict(list)
    for r in replays:
        by_guid[r.match_guid or f"<no-guid:{r.id}>"].append(r)

    dupes = {guid: rs for guid, rs in by_guid.items() if len(rs) > 1 and not guid.startswith("<no-guid")}
    if not dupes:
        return len(replays), 0

    print(f"\n{name}  ({BALLCHASING_URL}{group_id})")
    for guid, rs in dupes.items():
        print(f"  match_guid {guid} appears {len(rs)}x")
        for r in rs:
            print(f"      id={r.id}  rocket_league_id={r.rocket_league_id}")
            # date is informational only: two players in different timezones
            # record the same game with different local timestamps.
            print(f"          date={r.date}  date_has_tz={r.date_has_timezone}")
            print(f"          {_fingerprint(r)}")

        rl_ids = {r.rocket_league_id for r in rs}
        if len(rl_ids) == 1:
            print("      -> SHARED rocket_league_id: shallow listing is enough to dedup these")
        else:
            print("      -> rocket_league_id differs per copy: deep fetch is required")

        # If these really are one game, every copy must agree on how long it ran
        # and on every player's box score. If they disagree, a shared MatchGUID
        # does NOT imply the same game and GUID based deduplication would be
        # discarding legitimate replays.
        if len({_fingerprint(r) for r in rs}) == 1:
            print("      -> VERIFIED same game (duration and every box score agree)")
        else:
            print("      -> WARNING: same GUID but the games differ. GUID dedup would be unsafe.")
    return len(replays), len(dupes)


def _goals(team: ballchasing.models.Team | None) -> str:
    if not (team and team.stats and team.stats.core):
        return "?"
    return str(team.stats.core.goals)


def _fingerprint(r: ballchasing.models.Replay) -> str:
    """Timezone independent identity of a game: length, result, and box scores."""
    players = []
    for team in (r.blue, r.orange):
        if not team:
            continue
        for p in team.players:
            score = p.stats.core.score if p.stats and p.stats.core else "?"
            goals = p.stats.core.goals if p.stats and p.stats.core else "?"
            players.append(f"{p.name}:{score}/{goals}")
    return f"duration={r.duration}s ot={r.overtime} score={_goals(r.blue)}-{_goals(r.orange)}  " + "  ".join(sorted(players))


async def main(group: str, recurse: bool) -> None:
    bckey = os.environ.get("BALLCHASING_KEY")
    if not bckey:
        print("Unable to find Ballchasing API key (BALLCHASING_KEY)")
        sys.exit(1)

    bapi = await ballchasing.Api.create(auth_key=bckey)
    total_replays = 0
    total_dupes = 0
    try:
        targets = await leaf_groups(bapi, group, recurse)
        print(f"Checking {len(targets)} group(s)...")
        for group_id, name in targets:
            replays, dupes = await check(bapi, group_id, name)
            total_replays += replays
            total_dupes += dupes
    finally:
        await bapi.close()

    print(f"\n{total_replays} replays inspected, {total_dupes} duplicated game(s) found.")


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser(description="Find duplicate recordings of the same game in a ballchasing group.")
    parser.add_argument("group", help="Ballchasing group id (a match group, or a match day group with --recurse)")
    parser.add_argument("-r", "--recurse", action="store_true", help="Treat the group as a parent and check each child")
    args = parser.parse_args()
    asyncio.run(main(args.group, args.recurse))
