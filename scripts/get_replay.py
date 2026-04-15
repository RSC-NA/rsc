#!/usr/bin/env python3

import argparse
import asyncio
import json
import os
import sys

import aiohttp
import ballchasing
from dotenv import load_dotenv

load_dotenv()


async def main(replay_id: str, output: str | None = None):
    bckey = os.environ.get("BALLCHASING_KEY")
    if not bckey:
        print("Unable to find Ballchasing API key (BALLCHASING_KEY)")
        sys.exit(1)

    bapi = ballchasing.Api(bckey)
    replay = await bapi.get_replay(replay_id)
    bapi.close()


    formatted = json.dumps(replay.model_dump(mode="json"), indent=2)

    if output:
        with open(output, "w") as f:
            f.write(formatted)
        print(f"Saved replay to {output}")
    else:
        print(formatted)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch an individual replay from ballchasing.com")
    parser.add_argument("replay_id", help="Replay GUID to fetch")
    parser.add_argument("-o", "--output", help="Save JSON to this file instead of printing")
    args = parser.parse_args()

    asyncio.run(main(args.replay_id, args.output))
