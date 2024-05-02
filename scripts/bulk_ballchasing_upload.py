#!/usr/bin/env python3

import argparse
import asyncio
import os
import sys
from pathlib import Path

import aiohttp
import ballchasing
import ballchasing.exceptions
from dotenv import load_dotenv

if __name__ == "__main__":
    loop = asyncio.get_event_loop()

    parser = argparse.ArgumentParser(
        description="Bulk upload replays to ballchasing group."
    )
    parser.add_argument("group", type=str, help="Ballchasing group")
    parser.add_argument("directory", type=str, help="Replay directory")
    argv = parser.parse_args()

    group: str = argv.group

    load_dotenv()
    bckey = os.environ.get("BALLCHASING_KEY")
    if not bckey:
        print("Unable to find Ballchasing API key (BALLCHASING_KEY)")
        sys.exit(1)

    replays = Path(argv.directory)

    if not (replays.exists() and replays.is_dir()):
        print(f"Invalid directory: {replays}")
        sys.exit(1)

    bapi = ballchasing.Api(auth_key=bckey, patreon_type=ballchasing.PatreonType.ORG)

    for r in replays.glob(pattern="*.replay"):
        try:
            result: ballchasing.models.ReplayCreated = loop.run_until_complete(
                bapi.upload_replay(replay_file=str(r.absolute()), group=group)
            )
            print(f"Uploaded replay: {r.name}")
        except ValueError as exc:
            if exc.args[0] and isinstance(exc.args[0], aiohttp.ClientResponse):
                print(f"Duplicate replay: {r.name}")
            else:
                raise exc
        except ballchasing.exceptions.BallchasingFault:
            print(f"Ballchasing Parser Error: {r.name}")

    loop.close()
