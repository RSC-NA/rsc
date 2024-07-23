#!/usr/bin/env python3

import asyncio
import os
from typing import AsyncIterator

from rscapi import ApiClient, Configuration, MembersApi
from rscapi.models.member import Member as RSCMember

API_KEY = os.environ.get("RSC_API_KEY")
API_HOST = "https://api.rscna.com/api/v1"

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
) -> AsyncIterator[RSCMember]:
    offset = 0
    async with ApiClient(CONF) as client:
        api = MembersApi(client)
        while True:
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


async def validate_rsc_ids():
    print("Validating RSC IDs")
    dupes: dict[str, list[RSCMember]] = {}
    c = 0
    async for member in paged_members():
        c += 1
        if (c % 100) == 0:
            print(f"Count: {c}")
        if not member.rsc_id:
            print(f"Member has no RSCID: {member.rsc_name} ({member.discord_id})")
            continue
        if dupes.get(member.rsc_id):
            dupes[member.rsc_id].append(member)
        else:
            dupes[member.rsc_id] = [member]

    # Find dupes
    print("Finding duplicate RSC IDs")
    for k, v in dupes.items():
        if len(v) > 1:
            print(f"{len(v)} duplicate members with ID {k}: {v}")

    print("Checking league status for RSC000000")
    zeroids = dupes.get("RSC000000", [])
    for m in zeroids:
        if m.player_leagues:
            print(f"{m.rsc_name} is playing in the league!")


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(validate_rsc_ids())
    loop.close()
