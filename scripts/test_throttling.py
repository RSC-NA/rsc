#!/usr/bin/env python3
import argparse

import asyncio
import os
import sys
import time
from typing import AsyncIterator

from rscapi import ApiClient, Configuration, LeaguePlayersApi
from rscapi.models.league_player import LeaguePlayer


NUM_CALLS = 200


API_KEY = os.environ.get("RSC_API_KEY")
API_HOST = "https://staging-api.rscna.com/api/v1"
# API_HOST = "http://127.0.0.1:8000/api/v1"

CONF = Configuration(
    host=API_HOST,
    api_key={"Api-Key": API_KEY},
    api_key_prefix={"Api-Key": "Api-Key"},
    retries=0,
)

NO_KEY_CONF = Configuration(
    host=API_HOST,
)

async def players(
    client: ApiClient,
    num: int|None=None,
) -> int:
    try:
        api = LeaguePlayersApi(client)
        response = await api.league_players_list_with_http_info(
            league=1,
            discord_id=138778232802508801,
            limit=1,
        )
        if response.status_code == 429:
            print(f"Call {num}: Rate limit exceeded")
        return response.status_code
    except Exception as exc:
        return exc.status if hasattr(exc, "status") else -1




async def test_throttling(conf: Configuration, count: int = NUM_CALLS):
    start = time.time()

    async with ApiClient(conf) as client:
        tasks = [
            players(client, num=i)
            for i in range(count)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        codes = {}
        for r in results:
            codes.setdefault(r, 0)
            codes[r] += 1

        for code, count in codes.items():
            print(f"Status Code {code}: {count} occurrences")

        duration = time.time() - start
        print(f"Completed {len(results)} calls in {duration:.2f} seconds")



async def main(count: int = NUM_CALLS):
    print(f"Call Limit: {count}")

    print("Starting authenticated API call test...")
    await test_throttling(CONF, count=count)

    print("Starting anonymous API call test...")
    await test_throttling(NO_KEY_CONF, count=count)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test RSC API throttling behavior")
    parser.add_argument("-c", "--count", type=int, default=NUM_CALLS, help="Number of API calls to make")
    args = parser.parse_args()
    asyncio.run(main(count=args.count))
