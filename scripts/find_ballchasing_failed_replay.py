#!/usr/bin/env python3

import argparse
import asyncio
import os
import sys

import ballchasing
from dotenv import load_dotenv

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find failed replay in ballchasing group.")
    parser.add_argument("group", type=str, help="Ballchasing group")
    parser.add_argument("-d", "--delete", action="store_true", help="Delete the failed replays")
    argv = parser.parse_args()

    group: str = argv.group

    load_dotenv()
    bckey = os.environ.get("BALLCHASING_KEY")
    if not bckey:
        print("Unable to find Ballchasing API key (BALLCHASING_KEY)")
        sys.exit(1)

    bapi = ballchasing.Api(auth_key=bckey, patreon_type=ballchasing.PatreonType.ORG)

    with asyncio.Runner() as runner:
        r: ballchasing.models.ReplayGroup = runner.run(bapi.get_group(group))

        if not r.failed_replays:
            print("No failed replays found!")
            runner.run(bapi.close())
            sys.exit(0)

        for failed in r.failed_replays:
            print(f"Found failed replay: {failed}")
            if argv.delete:
                print(f"Deleting replay: {failed}")
                runner.run(bapi.delete_replay(failed))

        runner.run(bapi.close())
