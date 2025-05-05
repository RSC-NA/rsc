#!/usr/bin/env python3

import asyncio
import json
import os
from enum import StrEnum
from pathlib import Path
from typing import AsyncIterator

import aiofiles
from rscapi import ApiClient, ApiException, Configuration, TrackerLinksApi
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.tracker_link import TrackerLink

API_KEY = os.environ.get("RSC_API_KEY")
API_HOST = "https://api.rscna.com/api/v1"

CONF = Configuration(
    host=API_HOST,
    api_key={"Api-Key": API_KEY},
    api_key_prefix={"Api-Key": "Api-Key"},
)

class TrackerLinksStatus(StrEnum):
    NEW = "NEW"  # New
    STALE = "STL"  # Stale
    PULLED = "PLD"  # Pulled
    FAILED = "FLD"  # Failed
    MISSING = "MSG"  # "Missing"
    REPULL = "RPL"  # "Repull Needed"

    @property
    def full_name(self) -> str:
        return self.name.capitalize()

async def paged_trackers(
    status: TrackerLinksStatus | None = None,
    discord_id: int | None = None,
    name: str | None = None,
    per_page: int = 100,
) -> AsyncIterator[TrackerLink]:
    offset = 0
    while True:
        async with ApiClient(CONF) as client:
            api = TrackerLinksApi(client)
            # print(f"Offset: {offset}")
            trackers = await api.tracker_links_list(
                status=str(status) if status else None,
                discord_id=discord_id,
                member_name=name,
                limit=per_page,
                offset=offset,
            )

            if not trackers.results:
                break

            for tracker in trackers.results:
                # print(f"Yielding tracker: {tracker.id} - {tracker.link}")
                yield tracker

        if not trackers.next:
            break

        offset += per_page


async def validate_trackers():
    print("Validating RSC Trackers")
    c = 1
    trackers = {}
    async for t in paged_trackers():
        # print(f"Tracker: {t.id} - {t.link}")
        if c % 500 == 0:
            print(f"Count: {c}")

        trackers[t.id] = t.link.lower()
        c += 1

    print(f"Total Trackers: {len(trackers)}")

    await save_trackers(trackers)
    await check_dupliates(trackers)

async def save_trackers(trackers: dict[int|None, str]):
    async with aiofiles.open(Path("./data/trackers.json").resolve(), "w") as f:
        await f.write(json.dumps(trackers, indent=4))

async def check_dupliates(trackers: dict[int|None, str]):
    for k, v in trackers.items():
        for k2, v2 in trackers.items():
            if v2.lower() == v.lower() and k != k2:
                print(f"Duplicate Found: {k} - {v}")
                print(f"Duplicate Found: {k2} - {v2}")

if __name__ == "__main__":
    print("Starting event loop.")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(validate_trackers())
    loop.close()
