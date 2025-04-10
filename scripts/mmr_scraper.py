#!/usr/bin/env python3
import asyncio
import logging
import os
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import AsyncIterator

import aiohttp
import pandas as pd
import undetected_chromedriver as uc
from fake_useragent import UserAgent
from rich.logging import RichHandler
from rscapi import ApiClient, ApiException, Configuration, TrackerLinksApi
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.tracker_link import TrackerLink
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

FORMAT = "%(message)s"
logging.basicConfig(
    level="NOTSET", format=FORMAT, datefmt="[%X]", handlers=[RichHandler()]
)
log = logging.getLogger(__name__)

# API

API_KEY = os.environ.get("RSC_API_KEY")
#API_HOST = "https://api.rscna.com/api/v1"
API_HOST = "https://staging-api.rscna.com/api/v1"

CONF = Configuration(
    host=API_HOST,
    api_key={"Api-Key": API_KEY},
    api_key_prefix={"Api-Key": "Api-Key"},
)


# User-Agents
UA = UserAgent()

TRN_API_KEY = os.environ.get("TRN_API_KEY")


# Navigate to the MMR page
TRACKER_URL = "https://abrahamjuliot.github.io/creepjs/"

TRACKER_LIMIT = 5 # Total to pull at one time


RL_SEASONS = {
	# '33': { "start": '2025-06-06', "end": '2025-09-05' },
	'32': { "start": '2025-03-05', "end": '2025-06-05' },
	'31': { "start": '2024-12-05', "end": '2025-03-04' },
	'30': { "start": '2024-09-05', "end": '2024-12-05' },
	'29': { "start": '2024-06-06', "end": '2024-09-05' },
	'28': { "start": '2024-03-06', "end": '2024-06-05' },
	# '27': { "start": '2023-12-07', "end": '2024-03-05' },
	# '26': { "start": '2023-09-07', "end": '2023-12-07' },
	# '25': { "start": '2023-06-07', "end": '2023-09-06' },
	# '24': { "start": '2023-03-08', "end": '2023-06-06' },
	# '23': { "start": '2022-12-07', "end": '2023-03-07' },
	# '22': { "start": '2022-09-07', "end": '2022-12-06' },
	# '21': { "start": '2022-06-15', "end": '2022-09-06' },
	# '20': { "start": '2022-03-09', "end": '2022-06-14' },
	# '19': { "start": '2021-11-17', "end": '2022-03-08' },
	# '18': { "start": '2021-08-11', "end": '2021-11-16' },
	# '17': { "start": '2021-04-07', "end": '2021-08-10' },
	# '16': { "start": '2020-12-09', "end": '2021-04-06' },
	# '15': { "start": '2020-09-23', "end": '2020-12-08' }
}

@dataclass
class PlaylistPull:
    rating: int
    games_played: int
    peak: int

@dataclass
class SeasonPull:
    season: int
    threes: PlaylistPull
    twos: PlaylistPull
    ones: PlaylistPull

@dataclass
class TrackerPull:
    id: int
    link: str
    seasons: list[SeasonPull]


class PlaylistID(IntEnum):
    CASUAL = 0
    ONES = 10
    TWOS = 11
    THREES = 13
    HOOPS = 27
    RUMBLE = 28
    DROPSHOT = 29
    SNOWDAY = 30
    TOURNAMENT = 34

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



async def get_trackers(limit: int = TRACKER_LIMIT) -> list[TrackerLink]:
    async with ApiClient(CONF) as client:
        api = TrackerLinksApi(client)
        return await api.tracker_links_next(limit=limit)

async def parse_link(link: str) -> tuple[str|None, str|None]:
    """ Get platform and ID from tracker link """
    split = link.split("/profile/")
    if not split or len(split) != 2:
        return None, None

    split = split[1].split("/")

    if not split or len(split) < 2:
        return None, None

    platform = split[0]
    trackerid = split[1]
    return platform, trackerid


async def pull_tracker(driver: webdriver.Chrome, link: str):

    platform, trackerid = await parse_link(link)
    if not (platform and trackerid):
        log.warning(f"Unable to parse platform and tracker ID from link: {link}")
        return None


    # https://api.tracker.gg/api/v2/rocket-league/player-history/mmr/${RTN_player_id} - HISTORY of peak per season
    # https://api.tracker.gg/api/v2/rocket-league/standard/profile/${api_path}?
    # https://api.tracker.gg/api/v2/rocket-league/standard/profile/steam/nickm/
    # https://api.tracker.gg/api/v2/rocket-league/standard/profile/steam/nickm/segments/playlist?season=32
    # https://rocketleague.tracker.network/rocket-league/profile/steam/nickm/overview

    # driver.get()
    async with aiohttp.ClientSession() as session:
        for snum in RL_SEASONS.keys():
            headers = {
                "TRN-Api-Key": TRN_API_KEY,
            #     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            #     "Accept-Encoding": "gzip, deflate, br, zstd",
            #     "Accept-Language": "en-US,en;q=0.5",
            #     "Connection": "keep-alive",
            #     # "Referrer": "https://rocketleague.tracker.network/",
            #     # "ReferrerPolicy": "strict-origin-when-cross-origin",
            #     "Host": "api.tracker.gg",
            #     "Sec-Fetch-Dest": "document",
            #     "Sec-Fetch-Mode": "navigate",
            #     "Sec-Fetch-Site": "none",
            #     "Sec-Fetch-User": "?1",
            #     "Upgrade-Insecure-Requests": "1",
            #     "Alt-Used": "api.tracker.gg",
            #     "Priority": "u=0, i",
            #     # "User-Agent": UA.random,
            #     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/137.0",
            #     "Cookie": "cf_clearance=Ra6r5lwsmZ37oVq0ZuN4KMTH8CKb7e1Z3qDHCeBhOKk-1744224473-1.2.1.1-EWHQSFOB1iWh.IxiXRLjVrzv9Q.p0jmxeZIH.o.wHp6dFc16r8sDkaeueQjcaM2nlxFFPZpDzhDXoUCq4eBP1.IbN4Bzu1y4kvljGd3k0tZrp176d84x4Md9HFOUkzsKt1izjTb8cx5J2.49Mru1teWShTJ.RYk5H5aauVrrTj3B9MPHqcE8Oti6O1u4E3eDmcii4Rsi64H7TH1EqdySkmuCWAIWBKQ8cpN7OJcY_NXqZXQecawv.dZZCN.H3lYS2QomHf5RaRl55_cUzWP9nPFKo3f20YJKW5J6A4bqrZMdYLrQu8mySdYwbUGZierAn9bfgrPMTrLtO22l.SSXQMv.VKn4H9nyvzGzPeruZNg; __cflb=02DiuFQAkRrzD1P1mdjW28WYn2UPf2uFAH7725tEDSpbn; __stripe_mid=31626bc0-1731-41e4-9029-d8b5ddfaa9cf5aa660; __cf_bm=hZTRfzl0Yp0MHXiTr1CnNXB3H0NBlAyp8zo9MonrkrM-1744226356-1.0.1.1-Bh.PYxhEwuOPaU0sAWf5ufFjk.3SddRJHQS1qDpGBjnz59OuVSQqjG6T_oVqqCwSR8zGcNljGHwzA9hAasTb0Ke2yewNUacxQfCABP7.JbkPq9XFFMjxNklTkzkQxFNQ"
            }
            api_url = f"https://api.tracker.gg/api/v2/rocket-league/standard/profile/{platform}/{trackerid}/segments/playlist?season={snum}"
            # api_url = f"https://public-api.tracker.gg/api/v2/rocket-league/standard/profile/{platform}/{trackerid}/segments/playlist?season={snum}"
            # log.debug(f"Pulling: {api_url}")
            # log.debug(f"Headers: {headers}")
            # async with session.get(api_url, headers=headers) as resp:
            #     log.debug(f"Status: {resp.status}")
            #     if resp.status not in [200, 304]:
            #         log.error(f"Failed to fetch tracker data: {resp.status}")
            #         exit(2)

            #     data = await resp.json()
            #     log.debug(f"Data: {data}")
            #     exit(1)
            # Get the season data
            if not link.startswith("https://"):
                driver.get(f"http://{link}")
            else:
                driver.get(link)
            driver.get(api_url)

        # Wait for the page to load and the table to be present

        # try:
        #     WebDriverWait(driver, 10).until(
        #         EC.presence_of_element_located((By.CSS_SELECTOR, "table"))
        #     )
        #     print("Page loaded successfully.")
        # except Exception as e:
        #     print(f"Error loading page: {e}")
        #     driver.quit()
        #     exit(1)

        # # Find the table element
        # table = driver.find_element(By.CSS_SELECTOR, "table")

        # # Extract data from the table
        # rows = table.find_elements(By.TAG_NAME, "tr")
        # data = []
        # for row in rows:
        #     cols = row.find_elements(By.TAG_NAME, "td")
        #     cols = [col.text for col in cols]
        #     data.append(cols)

        # # Convert to DataFrame
        # df = pd.DataFrame(data[1:], columns=data[0])




async def main(driver: webdriver.Chrome):


    # Get unpulled trackers
    trackers = await get_trackers()
    if not trackers:
        log.warning("No new trackers provided by API.")
        return

    log.info(f"Found {len(trackers)} trackers to pull.")
    for t in trackers:
        log.info(f"Tracker: {t.id} - {t.link}")
        await pull_tracker(driver, t.link)

    # Log

    # Pull
    #driver.get(url)

    # Wait for the page to load and the table to be present
    # try:
    #     WebDriverWait(driver, 10).until(
    #         EC.presence_of_element_located((By.CSS_SELECTOR, "table"))
    #     )
    #     print("Page loaded successfully.")
    # except Exception as e:
    #     print(f"Error loading page: {e}")
    #     driver.quit()
    #     exit(1)

    # # Find the table element
    # table = driver.find_element(By.CSS_SELECTOR, "table")

    # # Extract data from the table
    # rows = table.find_elements(By.TAG_NAME, "tr")
    # data = []
    # for row in rows:
    #     cols = row.find_elements(By.TAG_NAME, "td")
    #     cols = [col.text for col in cols]
    #     data.append(cols)

    # # Convert to DataFrame
    # df = pd.DataFrame(data[1:], columns=data[0])  # Skip header row

    # Save to CSV file
    #df.to_csv("mmr_data.csv", index=False)

    #print("Data saved to mmr_data.csv")


if __name__ == "__main__":
    # Set up the Chrome driver with undetected_chromedriver
    options = uc.ChromeOptions()
    options.add_argument("--headless")  # Run in headless mode (no GUI)
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    options.add_argument(f"user-agent={UA.random}")

    # Create a new instance of the Chrome driver
    driver = uc.Chrome(options=options)

    print("Starting event loop.")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main(driver=driver))
    loop.close()

    driver.quit()
