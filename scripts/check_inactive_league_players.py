#!/usr/bin/env python3

import argparse
import asyncio
import os
from typing import AsyncIterator

from rscapi import ApiClient, Configuration, LeaguePlayersApi, MembersApi
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.member import Member

API_KEY = os.environ.get("RSC_API_KEY")
API_HOST = "https://api.rscna.com/api/v1"

CONF = Configuration(
    host=API_HOST,
    api_key={"Api-Key": API_KEY},
    api_key_prefix={"Api-Key": "Api-Key"},
)


async def paged_players(
    season_number: int,
    per_page: int = 100,
) -> AsyncIterator[LeaguePlayer]:
    offset = 0
    while True:
        async with ApiClient(CONF) as client:
            api = LeaguePlayersApi(client)
            print(f"Fetching league players at offset: {offset}")
            players = await api.league_players_list(
                league=1,
                season_number=season_number,
                limit=per_page,
                offset=offset,
            )

            if not players.results:
                break

            for player in players.results:
                yield player

        if not players.next:
            break

        offset += per_page


async def get_member(discord_id: int) -> Member | None:
    async with ApiClient(CONF) as client:
        api = MembersApi(client)
        result = await api.members_list(discord_id=discord_id, limit=1)
        if result and result.results:
            return result.results[0]
    return None


async def check_inactive(season_number: int):
    total = 0
    flagged = 0

    async for lp in paged_players(season_number=season_number):
        if lp.status in ["FN", "DR", "BN"]:
            continue

        total += 1

        if not lp.player.discord_id:
            flagged += 1
            print(
                f"NO DISCORD ID: {lp.player.name} "
                f"(RSC ID: {lp.player.rsc_id}, LP ID: {lp.id}, Status: {lp.status})"
            )
            continue

        member = await get_member(lp.player.discord_id)

        if not member:
            flagged += 1
            print(
                f"MEMBER NOT FOUND: {lp.player.name} "
                f"(RSC ID: {lp.player.rsc_id}, "
                f"Discord ID: {lp.player.discord_id}, "
                f"LP ID: {lp.id}, Status: {lp.status})"
            )
            continue

        active = getattr(member, "active", None)
        if active is not True:
            flagged += 1
            print(
                f"INACTIVE: {lp.player.name} "
                f"(RSC ID: {lp.player.rsc_id}, "
                f"Discord ID: {lp.player.discord_id}, "
                f"LP ID: {lp.id}, "
                f"Status: {lp.status}, "
                f"active={active})"
            )

    print(f"\nTotal players: {total}")
    print(f"Flagged inactive: {flagged}")


def main():
    parser = argparse.ArgumentParser(description="Check for inactive league players")
    parser.add_argument("season", type=int, help="Season number to check")
    args = parser.parse_args()

    asyncio.run(check_inactive(args.season))


if __name__ == "__main__":
    main()
