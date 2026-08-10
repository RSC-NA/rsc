#!/usr/bin/env python3
"""Prove that local replay parsing and ballchasing agree on a game's fingerprint.

Deduplication compares a fingerprint computed from a locally parsed replay
header against one computed from ballchasing's own stats. Those are two entirely
separate parsers reading the same game. If they disagree about a player name or
any box score number, every comparison fails and duplicate detection silently
stops working -- the bot would upload duplicates forever and never say why.

This downloads each replay in a group back from ballchasing, parses it with our
local parser, and checks the two fingerprints match.

    ./scripts/bc_verify_fingerprints.py <group_id>
    ./scripts/bc_verify_fingerprints.py <group_id> --recurse
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import ballchasing
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from rsc.ballchasing import process  # noqa: E402


def _local_lines(parsed) -> list[str]:
    return sorted(
        ":".join([str(p.get("Name")), *[process._stat(p.get(prop)) for prop, _ in process.STAT_FIELDS]])
        for p in parsed.player_stats or []
    )


def _bc_lines(replay: ballchasing.models.Replay) -> list[str]:
    lines = []
    for team in (replay.blue, replay.orange):
        for player in (team.players if team else []):
            core = player.stats.core if player.stats else None
            stats = [process._stat(getattr(core, attr, None)) for _, attr in process.STAT_FIELDS]
            lines.append(":".join([str(player.name), *stats]))
    return sorted(lines)


async def verify(bapi: ballchasing.Api, replay: ballchasing.models.Replay) -> bool:
    bc_fp = process.bc_fingerprint(replay)
    if bc_fp is None:
        print(f"  SKIP  {replay.id}  (status={replay.status}, no comparable stats)")
        return True

    data = await bapi.download_replay_content(replay.id)
    try:
        parsed = await asyncio.to_thread(process._parse_bytes, data)
    except Exception as exc:
        print(f"  FAIL  {replay.id}  local parser could not read it: {exc}")
        return False

    local_fp = process.local_fingerprint(parsed)
    if local_fp == bc_fp:
        print(f"  OK    {replay.id}  {local_fp}")
        return True

    print(f"  FAIL  {replay.id}  local={local_fp} ballchasing={bc_fp}")
    local, remote = _local_lines(parsed), _bc_lines(replay)
    for line in sorted(set(local) - set(remote)):
        print(f"          local only: {line}")
    for line in sorted(set(remote) - set(local)):
        print(f"          bc only   : {line}")
    return False


async def main(group: str, recurse: bool) -> None:
    bckey = os.environ.get("BALLCHASING_KEY")
    if not bckey:
        print("Unable to find Ballchasing API key (BALLCHASING_KEY)")
        sys.exit(1)

    bapi = await ballchasing.Api.create(auth_key=bckey)
    ok = failed = 0
    try:
        replays = [r async for r in bapi.get_group_replays(group_id=group, deep=True, recurse=recurse)]
        print(f"Verifying {len(replays)} replay(s) in {group}\n")
        for replay in replays:
            if await verify(bapi, replay):
                ok += 1
            else:
                failed += 1
    finally:
        await bapi.close()

    print(f"\n{ok} agreed, {failed} disagreed.")
    if failed:
        print("Local parsing and ballchasing DISAGREE. Deduplication will not work against the group listing.")
        sys.exit(1)
    print("Local parsing and ballchasing agree. Fingerprint based deduplication is sound.")


if __name__ == "__main__":
    load_dotenv()
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description="Check local and ballchasing fingerprints agree.")
    parser.add_argument("group", help="Ballchasing group id")
    parser.add_argument("-r", "--recurse", action="store_true", help="Include child groups")
    args = parser.parse_args()
    asyncio.run(main(args.group, args.recurse))
