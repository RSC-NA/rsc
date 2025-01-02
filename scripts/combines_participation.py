#!/usr/bin/env python3

import argparse
import asyncio
import os
from typing import AsyncIterator

import pandas as pd
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

            print(f"Player result Length: {len(players.results)}")

            if not players.results:
                break

            for player in players.results:
                yield player

        if not players.next:
            break

        offset += per_page


def parse_combines_csv(csv_file: str):
    df = pd.read_csv(csv_file)
    df.set_index('RSC ID', inplace=True)
    print(df)

    return df

async def participation(season: int, csv_file: str):
    # parse combines data
    cdata = parse_combines_csv(csv_file)

    tiers = cdata['Combine Tier'].unique()
    print(tiers)

    total_0_games = cdata.query('Games <= 0')
    print(f"Total 0 Games in CSV: {len(total_0_games)}")


    # Loop players
    total = 0
    stats: dict[int, int] = {}
    stats[30] = 0
    stats[20] = 0
    stats[10] = 0
    stats[5] = 0
    stats[1] = 0
    stats[0] = 0

    print("Looping players...")
    async for api_player in paged_players(season=season):
        print("Player: ", api_player.player.rsc_id)

        # Skip PermFAs
        if api_player.status == "PF":
            continue

        total += 1

        if not api_player.player.rsc_id:
            print(f"Player has no RSC ID: {api_player.player.name}")
            break

        try:
            player = cdata.loc[api_player.player.rsc_id]
        except KeyError:
            stats[0] += 1
            continue

        gp = player["Games"]
        print(f"Games Played: {gp}")
        if gp >= 30:
            stats[30] += 1
        if gp >= 20:
            stats[20] += 1
        if gp >= 10:
            stats[10] += 1
        if gp >= 5:
            stats[5] += 1
        if gp >= 1:
            stats[1] += 1
        if gp == 0:
            stats[0] += 1

        if gp < 0:
            print(f"Unknown games played error: {gp} {api_player.player.rsc_id}")
            break

    print(f"Total non PFA players: {total}")
    print(f"Total combine participants: {len(cdata)}")
    print(f"Players found in combines data: {len(cdata)/total*100:.2f}%")


    print(f"Percent >= 30 combines played: {stats[30]/total*100:.2f}%")
    print(f"Percent >= 20 combines played: {stats[20]/total*100:.2f}%")
    print(f"Percent >= 10 combines played: {stats[10]/total*100:.2f}%")
    print(f"Percent >= 5 combines played: {stats[5]/total*100:.2f}%")
    print(f"Percent >= 1 combines played: {stats[1]/total*100:.2f}%")
    print(f"Percent 0 combines played: {stats[0]/total*100:.2f}%")









if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Check combines participation')
    parser.add_argument(
        'season', type=int, default=None,
        help='RSC Season ID (Not number)')
    parser.add_argument(
        'csv_file', type=str, default=None,
        help='Combines CSV file')

    argv = parser.parse_args()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(participation(season=argv.season, csv_file=argv.csv_file))
    # loop.run_until_complete(get_rostered_players())
    loop.close()
