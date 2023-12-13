import aiohttp
import asyncio
import aiofiles
import logging
import random
from datetime import datetime
from pathlib import Path

from rscapi.models.tracker_link import TrackerLink

from typing import List, Optional

log = logging.getLogger("red.trackers.scraper")


class TrackerScraper:
    def __init__(self):
        self.agents = Path(__file__).parent.parent / "resources/user_agents.txt"
        self.bans: list[datetime] = []
        self.trackers: list[TrackerLink] = []

    async def queue(self, trackers: list[TrackerLink]):
        self.trackers.extend(trackers)

    async def agent(self) -> str:
        async with aiofiles.open(self.agents, "r") as fd:
            data = await fd.readlines()
            idx = random.randint(0, len(data))
            return data[idx]

    async def clear(self):
        self.trackers = []

    async def remove(self, tracker: TrackerLink):
        self.trackers.remove(tracker)

    async def add(self, tracker: TrackerLink):
        if tracker not in self.trackers:
            self.trackers.append(tracker)

    async def next(self) -> Optional[TrackerLink]:
        try:
            return self.trackers.pop(0)
        except IndexError:
            return None

    async def start(self, count: int = 10):
        for idx in range(0, count):
            tracker = await self.next()
            if not tracker:
                return

            await self.scrape(tracker)
            seconds = float(random.randint(10, 20))
            log.debug(f"Sleeping for {seconds} seconds before next pull.")
            await asyncio.sleep(seconds)

    async def scrape(self, tracker: TrackerLink) -> bool:
        return True
