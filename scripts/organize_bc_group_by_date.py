#!/usr/bin/env python3

import argparse
import asyncio
import os
import sys

# import aiohttp
import ballchasing
import ballchasing.exceptions
from dotenv import load_dotenv

# from pathlib import Path


async def parse_bc_group():
    raise NotImplementedError()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()

    parser = argparse.ArgumentParser(description="Organize ballchasing groups by date")
    parser.add_argument("group", type=str, help="Ballchasing group")
    parser.add_argument(
        "-n", "--no-dry-run", type=int, default=None, help="Organize the replays."
    )
    argv = parser.parse_args()

    group: str = argv.group

    load_dotenv()
    bckey = os.environ.get("BALLCHASING_KEY")
    if not bckey:
        print("Unable to find Ballchasing API key (BALLCHASING_KEY)")
        sys.exit(1)

    bapi = ballchasing.Api(auth_key=bckey, patreon_type=ballchasing.PatreonType.ORG)

    loop.run_until_complete()

    loop.close()
