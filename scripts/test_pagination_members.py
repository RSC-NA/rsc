#!/usr/bin/env python3

import asyncio
import os
import sys
from typing import AsyncIterator

from rscapi import ApiClient, Configuration, MembersApi
from rscapi.models.league_player import LeaguePlayer

API_KEY = os.environ.get("RSC_API_KEY")
API_HOST = "https://api.rscna.com/api/v1"
#API_HOST = "http://127.0.0.1:8000/api/v1"

CONF = Configuration(
    host=API_HOST,
    api_key={"Api-Key": API_KEY},
    api_key_prefix={"Api-Key": "Api-Key"},
)

async def paged_members(
    rsc_name: str | None = None,
    discord_username: str | None = None,
    discord_id: int | None = None,
    per_page: int = 100,
    maximum: int = 1000,
):
    offset = 0
    while True:
        async with ApiClient(CONF) as client:
            api = MembersApi(client)
            members = await api.members_list(
                rsc_name=rsc_name,
                discord_username=discord_username,
                discord_id=discord_id,
                limit=per_page,
                offset=offset,
            )

            if not members:
                break

            if not members.results:
                break

            for member in members.results:
                yield member

            if not members.next:
                break

            offset += per_page

            if offset > maximum:
                print(f"Reached maximum number of players to fetch: {maximum}")
                break



async def get_paged_members_list():
    total = 0
    seen = []
    async for api_member in paged_members():
        total += 1
        if api_member.rsc_id in seen:
            print(f"Duplicate player found: {api_member.rsc_id} - {api_member.rsc_name} ({api_member.discord_id})")
            sys.exit(1)
        else:
            print(f"New Player: {api_member.rsc_id} - {api_member.rsc_name} ({api_member.discord_id})")
            seen.append(api_member.rsc_id)

    print(f"Total players returned from paged players: {total}")




if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(get_paged_members_list())
    # loop.run_until_complete(get_rostered_players())
    loop.close()
