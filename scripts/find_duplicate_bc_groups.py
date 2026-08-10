#!/usr/bin/env python3
"""Find sibling ballchasing groups that share a name.

Group creation used to be an unsynchronised list-then-create, so two reporters
hitting the same match night at once could each create their own "Match Day 05"
(or tier, or match) group and split the replays between them. The bot no longer
does this, but any duplicates it already made are still out there.

    ./scripts/find_duplicate_bc_groups.py <top_level_group_id>
    ./scripts/find_duplicate_bc_groups.py <top_level_group_id> --depth 4
"""

import argparse
import asyncio
import os
import sys
from collections import defaultdict

import ballchasing
from dotenv import load_dotenv

BALLCHASING_URL = "https://ballchasing.com/group/"


async def walk(bapi: ballchasing.Api, group: str, path: str, depth: int, found: list) -> None:
    if depth < 0:
        return

    by_name: dict[str, list[ballchasing.models.ReplayGroup]] = defaultdict(list)
    children = [g async for g in bapi.get_groups(group=group)]
    for child in children:
        by_name[child.name.casefold()].append(child)

    for name, dupes in by_name.items():
        if len(dupes) > 1:
            found.append((f"{path}/{name}", dupes))
            print(f"\nDUPLICATE: {path}/{dupes[0].name}")
            for d in dupes:
                print(f"    {d.id}  created={d.created}  {BALLCHASING_URL}{d.id}")

    for child in children:
        await walk(bapi, child.id, f"{path}/{child.name}", depth - 1, found)


async def main(tlg: str, depth: int) -> None:
    bckey = os.environ.get("BALLCHASING_KEY")
    if not bckey:
        print("Unable to find Ballchasing API key (BALLCHASING_KEY)")
        sys.exit(1)

    bapi = await ballchasing.Api.create(auth_key=bckey)
    found: list = []
    try:
        print(f"Walking {tlg} to depth {depth}...")
        await walk(bapi, tlg, "", depth, found)
    finally:
        await bapi.close()

    if found:
        print(f"\nFound {len(found)} duplicated group name(s). Merge the replays and delete the empty groups.")
    else:
        print("\nNo duplicate sibling group names found.")


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser(description="Find duplicate sibling groups under a ballchasing group.")
    parser.add_argument("tlg", help="Top level ballchasing group id")
    parser.add_argument("-d", "--depth", type=int, default=5, help="How many levels to descend (default: 5)")
    args = parser.parse_args()
    asyncio.run(main(args.tlg, args.depth))
