#!/usr/bin/env python3

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import aiohttp
import ballchasing
import ballchasing.exceptions
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

bckey = os.environ.get("BALLCHASING_KEY")
if not bckey:
    print("Unable to find Ballchasing API key (BALLCHASING_KEY)")
    sys.exit(1)

async def download_group(
    bapi: ballchasing.Api, group_id: str, folder: str, recursive=True
) -> tuple[int, int]:
    """
    Download an entire group.

    :param group_id: the base group id.
    :param folder: the folder in which to create the group folder.
    :param recursive: whether or not to create new folders for child groups.
    """
    folder = os.path.join(folder, group_id)
    group_count = 0
    replay_count = 0
    log.debug("Processing group %s into %s", group_id, folder)
    if recursive:
        os.makedirs(folder, exist_ok=True)
        async for child_group in bapi.get_groups(group=group_id):
            child_group_count, child_replay_count = await download_group(
                bapi, child_group.id, folder, recursive=True
            )
            group_count += child_group_count + 1
            replay_count += child_replay_count
        async for replay in bapi.get_replays(group_id=group_id):
            log.debug("Downloading replay %s", replay.id)
            replay_count += 1
            await bapi.download_replay(replay.id, folder)
    else:
        async for replay in bapi.get_group_replays(group_id, recurse=False):
            log.debug("Downloading replay %s", replay.id)
            group_count += 1
            replay_count += 1
            await bapi.download_replay(replay.id, folder)
    return group_count, replay_count


async def process_group(group: str, output_directory: str, recursive: bool=False) -> tuple[int, int]:
    bapi = ballchasing.Api(auth_key=bckey, patreon_type=ballchasing.PatreonType.ORG)
    log.info("Checking if group exists: %s", group)
    base_group = await bapi.get_group(group)
    if not base_group:
        log.error("Group does not exist: %s", group)
        return 0, 0
    group_count, replay_count = await download_group(
        bapi,
        group_id=group,
        folder=output_directory,
        recursive=recursive
    )
    await bapi.close()
    return group_count, replay_count


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description="Bulk download replays from ballchasing group."
    )
    parser.add_argument("group", type=str, help="Ballchasing group")
    parser.add_argument("output", type=str, help="Output directory")
    parser.add_argument("-r", "--recursive", action="store_true", help="Download replays recursively", default=False)
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging", default=False)
    argv = parser.parse_args()

    group: str = argv.group
    output_dir = Path(argv.output).absolute()

    if argv.debug:
        log.setLevel(logging.DEBUG)

    log.info("Output directory: %s", output_dir)
    log.info("Recursive: %s", argv.recursive)

    group_count, replay_count = asyncio.run(
        process_group(
            group=group,
            output_directory=str(output_dir),
            recursive=argv.recursive,
        )
    )

    log.info("Downloaded %d groups and %d replays", group_count, replay_count)
