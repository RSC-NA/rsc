#!/usr/bin/env python3

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


async def paged_players(
    status: str | None = None,
    name: str | None = None,
    tier: int | None = None,
    tier_name: str | None = None,
    season: int | None = None,
    season_number: int | None = None,
    team_name: str | None = None,
    franchise: str | None = None,
    discord_id: int | None = None,
    per_page: int = 100,
) -> AsyncIterator[LeaguePlayer]:
    offset = 0
    while True:
        async with ApiClient(CONF) as client:
            api = LeaguePlayersApi(client)
            print(f"Offset: {offset}")
            players = await api.league_players_list(
                status=str(status) if status else None,
                name=name,
                tier=tier,
                tier_name=tier_name,
                season=season,
                season_number=season_number,
                league=1,
                team_name=team_name,
                franchise=franchise,
                discord_id=discord_id,
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


async def players(
    status: str | None = None,
    name: str | None = None,
    tier: int | None = None,
    tier_name: str | None = None,
    season: int | None = None,
    season_number: int | None = None,
    team_name: str | None = None,
    franchise: str | None = None,
    discord_id: int | None = None,
) -> list[LeaguePlayer]:
    async with ApiClient(CONF) as client:
        api = LeaguePlayersApi(client)
        players = await api.league_players_list(
            status=str(status) if status else None,
            name=name,
            tier=tier,
            tier_name=tier_name,
            season=season,
            season_number=season_number,
            league=1,
            team_name=team_name,
            franchise=franchise,
            discord_id=discord_id,
            limit=2000,
            offset=0,
        )
        return players.results


async def get_paged_rostered_players():
    total = 0
    async for api_player in paged_players(season_number=25):
        total += 1

    print(f"Total players returned from paged players: {total}")


async def get_rostered_players():
    total = 0
    synced = 0
    for api_player in await players(season_number=25):
        total += 1

    print(f"Total players returned from non-paged players: {total}")


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(get_paged_rostered_players())
    loop.run_until_complete(get_rostered_players())
    loop.close()
