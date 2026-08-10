#!/usr/bin/env python3
"""Dump the header properties we rely on from one or more .replay files.

Duplicate detection keys off the MatchGUID header property, which every player's
recording of the same online match shares. Rocket League renamed that key once
already (build 241014 switched "MatchGuid" to "MatchGUID") and older builds omit
it entirely, so use this to check real files when something stops deduplicating.

    ./scripts/dump_replay_header.py a.replay b.replay
"""

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path

from replay_parser import ReplayParser

sys.path.insert(0, str(Path(__file__).parent.parent))

from rsc.ballchasing.process import MATCH_GUID_KEYS, match_guid  # noqa: E402

INTERESTING = ("Id", "Date", "MapName", "BuildVersion", "TeamSize", "MatchType")


def dump(path: Path) -> str | None:
    print(f"\n{'=' * 78}\n{path.name}\n{'=' * 78}")

    try:
        parsed = ReplayParser(debug=False).parse(replay_file=str(path), net_stream=False)
    except Exception as exc:
        print(f"  PARSE FAILED: {exc}")
        return None

    props = parsed.header.properties

    found_key = next((k for k in MATCH_GUID_KEYS if props.get(k)), None)
    guid = match_guid(parsed)
    print(f"  {'MatchGUID':<14}: {guid or '<MISSING>'}" + (f"  (header key: {found_key})" if found_key else ""))

    for key in INTERESTING:
        print(f"  {key:<14}: {props.get(key, '<MISSING>')}")

    players = props.get("PlayerStats") or []
    print(f"  {'Players':<14}: {len(players)}")
    for p in players:
        print(
            f"      team={p.get('Team')} score={str(p.get('Score')):>4} "
            f"platform={str(p.get('Platform')):<24} {p.get('Name')}"
        )
    return guid


def main(paths: list[Path]) -> None:
    by_guid: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        guid = dump(path)
        by_guid[guid or "<MISSING>"].append(path.name)

    print(f"\n{'=' * 78}\nGrouped by MatchGUID\n{'=' * 78}")
    for guid, names in by_guid.items():
        marker = "  <-- same match" if len(names) > 1 and guid != "<MISSING>" else ""
        print(f"  {guid}{marker}")
        for name in names:
            print(f"      {name}")


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description="Dump Rocket League replay header properties.")
    parser.add_argument("replays", type=Path, nargs="+", help="Replay files to inspect")
    args = parser.parse_args()
    main(args.replays)
