#!/usr/bin/env python3

import argparse
import asyncio
import os

from rscapi import ApiClient, Configuration, Member, MembersApi
from rscapi.models.patched_member_name_change_request import PatchedMemberNameChangeRequest

API_KEY = os.environ.get("RSC_API_KEY", "")
API_HOST = "http://127.0.0.1:8000/api/v1"

CONF = Configuration(
    host=API_HOST,
    api_key={"Api-Key": API_KEY},
    api_key_prefix={"Api-Key": "Api-Key"},
)


async def change_member_name(
    id: int,
    name: str,
    override: bool = False,
) -> Member:
    async with ApiClient(CONF) as client:
        api = MembersApi(client)
        print(f"Override: {override}")
        data = PatchedMemberNameChangeRequest(name=name, admin_override=override)
        return await api.members_name_change_partial_update(id, data)


async def test_name_change(discord_id: int, name: str, force: bool = False):
    member = await change_member_name(discord_id, name, override=force)
    print(f"Member: {member}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Name Change")
    parser.add_argument("discord_id", type=int, help="Discord ID")
    parser.add_argument("name", type=str, help="New Name")
    parser.add_argument("-f", "--force", action="store_true", default=False, help="Admin Override")
    argv = parser.parse_args()

    asyncio.run(test_name_change(argv.discord_id, argv.name, argv.force))
    # asyncio.run(get_rostered_players())
