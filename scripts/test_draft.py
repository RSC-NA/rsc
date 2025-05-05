#!/usr/bin/env python3

import argparse
import asyncio
import os
import sys
from enum import StrEnum
from typing import AsyncIterator, cast

import numpy as np
import pandas as pd
from rscapi import (
    ApiClient,
    Configuration,
    DraftAPlayerToATeam,
    LeaguePlayersApi,
    TeamList,
    TeamsApi,
    TiersApi,
    TransactionResponse,
    TransactionsApi,
)
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.tier import Tier

API_KEY = os.environ.get("RSC_API_KEY")
API_HOST = "https://staging-api.rscna.com/api/v1"

CONF = Configuration(
    host=API_HOST,
    api_key={"Api-Key": API_KEY},
    api_key_prefix={"Api-Key": "Api-Key"},
)

class Status(StrEnum):
    DRAFT_ELIGIBLE = "DE"  # Draft Eligible
    FREE_AGENT = "FA"  # Free Agent
    ROSTERED = "RO"  # Rostered
    RENEWED = "RN"  # Renewed
    IR = "IR"  # Inactive Reserve
    WAIVERS = "WV"  # Waivers
    AGMIR = "AR"  # AGM IR
    FORMER = "FR"  # Former
    BANNED = "BN"  # Banned
    UNSIGNED_GM = "UG"  # GM (Unsigned)
    PERM_FA = "PF"  # Permanent Free Agent
    PERMFA_W = "PW"  # Permanent FA in Waiting
    WAIVER_CLAIM = "WC"  # Waiver Claim
    WAIVER_RELEASE = "WR"  # Waiver Release
    DROPPED = "DR"  # Dropped

async def tiers() -> list[Tier]:
    """Fetch a list of tiers"""
    async with ApiClient(CONF) as client:
        api = TiersApi(client)
        tiers = await api.tiers_list(league=1)
        tiers.sort(key=lambda t: cast(int, t.position), reverse=True)

        # Populate cache
        if tiers:
            if not all(t.name for t in tiers):
                raise AttributeError("API returned a tier with no name.")
        return tiers

async def draft(
    player: int,
    # executor: None,
    team: str,
    round: int,
    pick: int,
    override: bool = False,
) -> TransactionResponse:
    """Fetch transaction history based on specified criteria"""
    async with ApiClient(CONF) as client:
        api = TransactionsApi(client)
        draft_pick = DraftAPlayerToATeam(
            league=1,
            player=player,
            executor=138778232802508801,
            team=team,
            round=round,
            number=pick,
            admin_override=override,
        )
        return await api.transactions_draft_create(draft_pick)

async def teams(
    seasons: str | None = None,
    franchise: str | None = None,
    name: str | None = None,
    tier: str | None = None,
) -> list[TeamList]:
    """Fetch teams from API"""
    async with ApiClient(CONF) as client:
        api = TeamsApi(client)
        teams = await api.teams_list(
            seasons=seasons,
            franchise=franchise,
            name=name,
            tier=tier,
            league=1,
        )
        return teams



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



async def parse_csv(csv: str, tier:str|None=None) -> pd.DataFrame:
    df: pd.DataFrame = pd.read_csv(csv, dtype={"Discord ID": str})
    # for idx, row in df.iterrows():
    #     if df[idx]["Player Id"] == "#N/A":
    #         df[idx]["Player Id"] = None

    df.replace("#N/A", np.nan, inplace=True)

    # print(df)
    # df["Player Id"] = (df["Player Id"] == "#N/A").astype(np.int64)
    df.dropna(how="all", inplace=True)

    if tier:
        df = df.loc[df['Tier'] == tier]

    # df["Player Id"] = df["Player Id"].apply(lambda x: int(x) if not pd.isna(x) else None)
    df["Discord ID"] = df["Discord ID"].astype('Int64')
    df["Pick #"] = df["Pick #"].astype(int)
    df["Round #"] = df["Round #"].astype(int)
    df["Pick / Round"] = df["Pick / Round"].astype(int)

    print(df)
    # with pd.option_context('display.max_rows', None, 'display.max_columns', None):  # more options can be specified also
    #     print(df["Player Id"])
    # print(df.dtypes)
    return df

async def process_tier(layout: pd.DataFrame, tier: str, pick:int, dry:bool=False) -> None:
    print(f"Getting player list for {tier}")
    plist = await players(tier_name=tier, season_number=23)
    plist.sort(key=lambda p: p.id)

    tdata = await teams(tier=tier)
    print(f"Team[0]: {tdata[0]}")

    print(f"Total draft picks in tier: {len(layout)}")
    print(f"Found {len(plist)} players in {tier}")
    eligible: list[LeaguePlayer] = []
    for p in plist:
        if p.status == Status.FREE_AGENT:
            eligible.append(p)
        if p.status == Status.DRAFT_ELIGIBLE:
            eligible.append(p)

    eligible.sort(key=lambda p: p.id)
    print(f"Total FA/DE players: {len(eligible)}")

    print(f"Starting draft at pick: {pick}")
    for idx, pos in layout.iterrows():
        print(f"[{tier}] Round: {pos['Round #']} Pick: {pos['Pick #']}")
        # print(type(pos["Pick"]))
        if pos["Pick #"] < pick:
            print(f"Skipping")
            continue

        gm = pos["Pick Owner"]

        if gm == "-":
            print(f"Skipping empty red square")
            continue

        # gm = "Tinsel"
        print(f"Pick Owner: {gm}")
        dst = None
        for t in tdata:
            if t.franchise.gm.rsc_name.lower() == gm.lower():
                dst = t
                break

        if not dst:
            print(f"Could not find team for GM: {gm}")
            sys.exit(1)

        print(f"Row Player Name: {pos['Player Name']} ID: {pos['Discord ID']}")
        if not pd.isna(pos["Discord ID"]):
            print(f"Drafting keeper pick")
            pname = pos["Player Name"]
            pid = pos["Discord ID"]
        else:
            # Sign from eligible
            print(f"Drafting eligible player")
            try:
                draftee = eligible.pop(0)
            except IndexError:
                print("No more eligible players. Finished draft.")
                break

            if not p:
                print("No more eligible players. Finished draft.")
                break
            pname = draftee.player.name
            pid = int(draftee.player.discord_id)
            print(f"Player Status in API: {draftee.status}")


        print(f"[{tier}] Round {pos['Round #']} Pick {pos['Pick #']} - Drafting {pname} ({pid}) to {dst.name}")

        if not dry:
            resp = await draft(player=pid, team=dst.name, round=pos["Round #"], pick=pos["Pick #"], override=True)
            # resp = await draft(player=pid, team=dst.name, round=pos["Round #"], pick=pos["Pick #"])
            if not resp:
                print("No transaction response from server...")
                sys.exit(0)

async def process_tier_random(layout: pd.DataFrame, tier: str, pick:int, dry:bool=False) -> None:
    print(f"Getting player list for {tier}")
    plist = await players(tier_name=tier, season_number=23)
    plist.sort(key=lambda p: p.id)

    tdata = await teams(tier=tier)
    print(f"Team[0]: {tdata[0]}")

    print(f"Total draft picks in tier: {len(layout)}")
    print(f"Found {len(plist)} players in {tier}")
    eligible: list[LeaguePlayer] = []
    for p in plist:
        if p.status == Status.FREE_AGENT:
            eligible.append(p)
        if p.status == Status.DRAFT_ELIGIBLE:
            eligible.append(p)

    eligible.sort(key=lambda p: p.id)
    print(f"Total FA/DE players: {len(eligible)}")

    print(f"Starting draft at pick: {pick}")
    for idx, pos in layout.iterrows():
        print(f"[{tier}] Round: {pos['Round #']} Pick: {pos['Pick #']}")
        # print(type(pos["Pick"]))
        if pos["Pick #"] < pick:
            print(f"Skipping")
            continue

        gm = pos["Pick Owner"]

        if gm == "-":
            print(f"Skipping empty red square")
            continue

        # gm = "Tinsel"
        print(f"Pick Owner: {gm}")
        dst = None
        for t in tdata:
            if t.franchise.gm.rsc_name.lower() == gm.lower():
                dst = t
                break

        if not dst:
            print(f"Could not find team for GM: {gm}")
            sys.exit(1)

        # Sign from eligible
        print(f"Drafting eligible player")
        try:
            draftee = plist.pop(0)
        except IndexError:
            print("No more eligible players. Finished draft.")
            break

        if not p:
            print("No more eligible players. Finished draft.")
            break
        pname = draftee.player.name
        pid = int(draftee.player.discord_id)
        print(f"Player Status in API: {draftee.status}")


        print(f"[{tier}] Round {pos['Round #']} Pick {pos['Pick #']} - Drafting {pname} ({pid}) to {dst.name}")

        if not dry:
            resp = await draft(player=pid, team=dst.name, round=pos["Round #"], pick=pos["Pick #"], override=True)
            # resp = await draft(player=pid, team=dst.name, round=pos["Round #"], pick=pos["Pick #"])
            if not resp:
                print("No transaction response from server...")
                sys.exit(0)




async def test_draft(draftcsv: str, tier: str, pick: int, dry:bool=False):
    layout = await parse_csv(draftcsv, tier=tier)
    tierlist = await tiers()

    if not any(t.name.lower() == tier.lower() for t in tierlist):
        print(f"[!] Tier does not exist: {tier}")
        sys.exit(1)

    # await process_tier(layout=layout, tier=tier, pick=pick, dry=dry)
    await process_tier_random(layout=layout, tier=tier, pick=pick, dry=dry)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Test RSC draft on staging')
    parser.add_argument(
        'tier', type=str, default=None,
        help='Tier')
    parser.add_argument(
        'draftcsv', type=str, default=None,
        help='CSV file from Draft Layout (Bot Command Tab)')
    parser.add_argument(
        '-p', '--pick', dest="pick", type=int, default=1,
        help='Start at pick within tier (Resume from error)')
    parser.add_argument(
        '--dry', action="store_true", default=False,
        help='Dry run. (Do not send draft pick to API)')
    argv = parser.parse_args()

    if argv.pick < 1:
        print("Pick must be greater than 0")
        sys.exit(1)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(test_draft(argv.draftcsv, tier=argv.tier, pick=argv.pick, dry=argv.dry))
    # loop.run_until_complete(get_rostered_players())
    loop.close()
