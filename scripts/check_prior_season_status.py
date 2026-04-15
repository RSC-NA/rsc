#!/usr/bin/env python3

import argparse
import asyncio
import os
from typing import AsyncIterator

from rscapi import ApiClient, Configuration, LeaguePlayersApi
from rscapi.models.league_player import LeaguePlayer

API_KEY = os.environ.get("RSC_API_KEY")
API_HOST = "https://api.rscna.com/api/v1"

CONF = Configuration(
    host=API_HOST,
    api_key={"Api-Key": API_KEY},
    api_key_prefix={"Api-Key": "Api-Key"},
)

ACTIVE_STATUSES = {"RO", "RN", "IR", "AGM_IR",  "FA"}


async def paged_players(
    season_number: int,
    status: str | None = None,
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
                status=status,
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


async def get_league_player(discord_id: int, season_number: int, status: str | None = None) -> LeaguePlayer | None:
    async with ApiClient(CONF) as client:
        api = LeaguePlayersApi(client)
        result = await api.league_players_list(
            league=1,
            discord_id=discord_id,
            season_number=season_number,
            status=status,
            limit=1,
        )
        if result and result.results:
            return result.results[0]
    return None


async def check_prior_season(season_number: int):
    prior_season = season_number - 1
    print(f"Checking season {season_number} players for prior season status (season {prior_season})")

    total = 0
    found = 0
    not_found = 0

    async for lp in paged_players(season_number=season_number, status="DE"):
        total += 1

        if not lp.player.discord_id:
            continue

        prior_lp = await get_league_player(lp.player.discord_id, prior_season)

        if not prior_lp:
            not_found += 1
            continue

        print(f"PriorLP Status: {prior_lp.status}")
        if prior_lp.status in ACTIVE_STATUSES:
            found += 1
            print(
                f"ACTIVE PRIOR SEASON: {lp.player.name} "
                f"(RSC ID: {lp.player.rsc_id}, "
                f"Discord ID: {lp.player.discord_id}, "
                f"LP ID: {lp.id}, "
                f"Current Status: {lp.status}, "
                f"Prior Status: {prior_lp.status}, "
                f"Prior Season: {prior_season})"
            )

    print(f"\nTotal members checked: {total}")
    print(f"Had active prior season status (RO/RN/FA): {found}")
    print(f"No league player record in season {prior_season}: {not_found}")


def main():
    parser = argparse.ArgumentParser(
        description="Check if members had an active status (RO/RN/FA) in the prior season"
    )
    parser.add_argument("season", type=int, help="Current season number (will check season - 1)")
    args = parser.parse_args()

    asyncio.run(check_prior_season(args.season))


if __name__ == "__main__":
    main()
