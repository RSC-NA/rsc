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
    SeasonsApi,
    TeamList,
    TeamsApi,
    TiersApi,
    TransactionResponse,
    TransactionsApi,
)
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.season import Season
from rscapi.models.tier import Tier

API_KEY = os.environ.get("RSC_API_KEY")
# API_HOST = "https://staging-api.rscna.com/api/v1"
API_HOST = "https://api.rscna.com/api/v1"

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
        else:
            raise ValueError("No tiers found.")
        return tiers

async def tier_players(tier_name: str, status: Status|None=None) -> None:
    """Fetch a list of tiers"""
    async with ApiClient(CONF) as client:
        api = LeaguePlayersApi(client)


        for s in Status:
            resp = await api.league_players_list(league=1, tier_name=tier_name, status=s)
            print(f"Status: {s} - Players: {resp.count}")




async def current_season() -> Season:
    """Fetch a list of tiers"""
    async with ApiClient(CONF) as client:
        api = SeasonsApi(client)
        season = await api.seasons_league_season(league=1)

        # Populate cache
        if not season:
            raise ValueError("No league season found.")
        return season



async def calculate_rounds(tier: str | None = None) -> None:
    """Calculate rounds for a given tier"""
    season = await current_season()


    for t in season.season_tier_data:
        print("=" * 20)
        print(f"Tier: {t.tier}")

        tcount = t.team_number
        await tier_players(t.tier)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Test RSC draft on staging')
    parser.add_argument(
        '-t', '--tier', type=str, default=None,
        help='Tier')
    argv = parser.parse_args()


    loop = asyncio.get_event_loop()
    loop.run_until_complete(calculate_rounds(tier=argv.tier))
    # loop.run_until_complete(get_rostered_players())
    loop.close()
