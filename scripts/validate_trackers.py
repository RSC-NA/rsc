#!/usr/bin/env python3

import asyncio
import os
from enum import StrEnum
from typing import AsyncIterator

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
    async for t in paged_trackers():
        # print(f"Tracker: {t.id} - {t.link}")
        if c % 500 == 0:
            print(f"Count: {c}")
        if not t.link.strip().startswith("http"):
            print(f"Invalid URL: {t.id} - {t.link}")
        c += 1

if __name__ == "__main__":
    print("Starting event loop.")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(validate_trackers())
    loop.close()
