#!/usr/bin/env python3
"""Compare shallow and deep ballchasing group listings.

`process_match_replays` currently fetches group replays with `deep=True`, which
costs one request per replay on top of the listing. That is only necessary if
the shallow listing omits `match_guid`.

This answers three things against a real group:

  1. Does the shallow listing populate match_guid? If so, deep=True can go.
  2. Is match_guid populated while a replay is still `pending`? If so, the
     upload ledger becomes a backstop rather than the primary dedup signal.
  3. Do the two listings otherwise agree?

    ./scripts/bc_replay_fields.py <group_id>
"""

import argparse
import asyncio
import os
import sys

import ballchasing
from dotenv import load_dotenv


def row(r: ballchasing.models.Replay) -> str:
    return f"  {r.id:<26} {str(r.status):<10} {str(r.match_guid):<34} {str(r.map_code):<16} {r.created}"


HEADER = f"  {'id':<26} {'status':<10} {'match_guid':<34} {'map_code':<16} created"


async def dump_raw(bapi: ballchasing.Api, group: str) -> None:
    """Print the raw JSON keys the list endpoint actually returns.

    Distinguishes "ballchasing omits the field" from "our model drops it".
    """
    resp = await bapi._request(f"{bapi.base_url}/replays", bapi._session.get, params={"group": group, "count": 1})
    data = await resp.json()
    entries = data.get("list") or []
    if not entries:
        print("\nRAW: group listing returned no entries")
        return

    entry = entries[0]
    print(f"\nRAW list entry keys ({len(entry)}):")
    for key in sorted(entry):
        value = entry[key]
        if isinstance(value, dict | list):
            value = f"<{type(value).__name__}>"
        print(f"  {key:<24} {value}")

    for field in ("match_guid", "status", "rocket_league_id"):
        verdict = "PRESENT in raw JSON" if field in entry else "absent from raw JSON"
        print(f"  -> {field}: {verdict}")


async def main(group: str, raw: bool) -> None:
    bckey = os.environ.get("BALLCHASING_KEY")
    if not bckey:
        print("Unable to find Ballchasing API key (BALLCHASING_KEY)")
        sys.exit(1)

    bapi = await ballchasing.Api.create(auth_key=bckey)
    try:
        if raw:
            await dump_raw(bapi, group)
        shallow = [r async for r in bapi.get_group_replays(group_id=group, deep=False)]
        deep = [r async for r in bapi.get_group_replays(group_id=group, deep=True)]
    finally:
        await bapi.close()

    for label, replays in (("SHALLOW (deep=False)", shallow), ("DEEP (deep=True)", deep)):
        print(f"\n{label} - {len(replays)} replays")
        print(HEADER)
        for r in replays:
            print(row(r))

    shallow_guids = {r.id: r.match_guid for r in shallow}
    deep_guids = {r.id: r.match_guid for r in deep}

    print("\nVERDICT")
    missing = [rid for rid, guid in shallow_guids.items() if not guid]
    if not shallow:
        print("  Group is empty - nothing to conclude.")
    elif not missing:
        print("  Shallow listing populates match_guid for every replay.")
        print("  -> process_match_replays can drop deep=True.")
    else:
        print(f"  Shallow listing is missing match_guid for {len(missing)}/{len(shallow)} replays:")
        for rid in missing:
            print(f"      {rid} (deep says: {deep_guids.get(rid)})")
        print("  -> keep deep=True, or deep fetch only the undecided replays.")

    pending = [r for r in deep if r.status == ballchasing.ReplayStatus.PENDING]
    if pending:
        with_guid = sum(1 for r in pending if r.match_guid)
        print(f"  {with_guid}/{len(pending)} pending replays expose a match_guid.")
    else:
        print("  No pending replays in this group (upload one and re-run to test that path).")


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser(description="Compare shallow vs deep ballchasing group listings.")
    parser.add_argument("group", help="Ballchasing group id")
    parser.add_argument("--raw", action="store_true", help="Also dump the raw JSON keys the list endpoint returns")
    args = parser.parse_args()
    asyncio.run(main(args.group, args.raw))
