#!/usr/bin/env python3

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from enum import StrEnum
from operator import attrgetter
from typing import AsyncIterator, TypedDict, cast

import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table
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

console = Console()



API_KEY = os.environ.get("RSC_API_KEY")
# API_HOST = "https://staging-api.rscna.com/api/v1"
API_HOST = "https://api.rscna.com/api/v1"

CONF = Configuration(
    host=API_HOST,
    api_key={"Api-Key": API_KEY},
    api_key_prefix={"Api-Key": "Api-Key"},
)

class CountKeeper(TypedDict):
    player: LeaguePlayer
    count: int
    keeper: int


class TransactionType(StrEnum):
    NONE = "NON"  # Invalid Transaction
    CUT = "CUT"  # Cut
    PICKUP = "PKU"  # Pickup
    TRADE = "TRD"  # Trade
    PLAYER_TRADE = "PTD"  # Player Trade
    SUBSTITUTION = "SUB"  # Substitution
    TEMP_FA = "TMP"  # Temporary Free Agent
    PROMOTION = "PRO"  # Promotion
    RELEGATION = "RLG"  # Relegation
    RESIGN = "RES"  # Re-sign
    INACTIVE_RESERVE = "IR"  # Inactive Reserve
    RETIRE = "RET"  # Retire
    WAIVER_RELEASE = "WVR"  # Waiver Release
    AGM_IR = "AIR"  # AGM Inactive Reserve
    IR_RETURN = "IRT"  # IR Return
    DRAFT = "DFT"  # Draft Player

    @property
    def full_name(self) -> str:
        return self.name.replace("_", " ").title()

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

async def transaction_history(
    player: int | None = None,
    executor: int | None = None,
    season: int | None = None,
    trans_type: TransactionType | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TransactionResponse]:
    """Fetch transaction history based on specified criteria"""
    async with ApiClient(CONF) as client:
        api = TransactionsApi(client)
        player_id = player or None
        executor_id = executor or None
        t_type = str(trans_type) if trans_type else None
        trans_list = await api.transactions_history_list(
            league=1,
            player=player_id,
            executor=executor_id,
            transaction_type=t_type,
            season_number=season,
            limit=limit,
            offset=offset,
        )
        return trans_list.results

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

async def player_status(name: str) -> None:
    """Fetch a list of tiers"""
    async with ApiClient(CONF) as client:
        api = LeaguePlayersApi(client)

        resp = await api.league_players_list(league=1, name=name)
        lplayers = resp.results
        console.print(f"Player: {name} - Status: {lplayers[0].status}")


async def tier_players(tier_name: str, status: Status|None=None) -> list[LeaguePlayer]:
    """Fetch a list of tiers"""
    async with ApiClient(CONF) as client:
        api = LeaguePlayersApi(client)

        resp = await api.league_players_list(league=1, tier_name=tier_name, limit=1000)
        console.print(f"Resp Count: {resp.count}")
        lplayers = resp.results
        console.print(f"Total Results: {len(lplayers)}")

        while any((remove:= p).status in [Status.FORMER, Status.BANNED, Status.PERM_FA, Status.PERMFA_W] for p in lplayers):
            console.print(f"\nRemoving {remove} players")
            lplayers.remove(remove)

        dropped_players = [p for p in lplayers if p.status == Status.DROPPED]
        for dropped in dropped_players:
            console.print(f"\nValidating dropped player: {remove.player.name}")
            history = await transaction_history(player=dropped.player.discord_id, season=23, trans_type=TransactionType.RETIRE)

            if not history:
                raise ValueError(f"Player {dropped.player.name} has no retirement history")

            console.print(f"History Count: {len(history)}")
            console.print(f"History[0]: {history[0]}")
            history.sort(key=lambda x: x.var_date, reverse=True)
            h = history.pop(0)
            console.print(f"History: {h.var_date} - {h.type} - {h.player_updates[0].player.player.name}")
            if h.var_date < datetime.fromisoformat("2025-04-21T00:00:00").replace(tzinfo=h.var_date.tzinfo):
            # if h.var_date < datetime.fromisoformat("2025-04-01:00:00").replace(tzinfo=h.var_date.tzinfo):
                console.print(f"Removing {dropped.player.name} - {dropped.status}")
                lplayers.remove(dropped)
            else:
                console.print(f"LEAVING DROPPED PLAYER IN {dropped.player.name} - {dropped.status}")


        lplayers.sort(key=lambda lp: (-lp.current_mmr, lp.player.name))
        console.print(f"Post filter: {len(lplayers)}")

        # Populate cache
        if not lplayers:
            raise ValueError(f"No league players found for tier: {tier_name}")
        return lplayers


async def current_season() -> Season:
    """Fetch a list of tiers"""
    async with ApiClient(CONF) as client:
        api = SeasonsApi(client)
        season = await api.seasons_league_season(league=1)

        # Populate cache
        if not season:
            raise ValueError("No league season found.")
        return season


async def print_count_keeper(data: list[CountKeeper]) -> None:
    """Print count keeper"""
    # for k, v in data.items():
    tier_name = data[0]["player"].tier.name
    table = Table(title=f"{tier_name} Count/Keeper")
    table.add_column("RSC ID", justify="left", style="cyan")
    table.add_column("Player Name", justify="left", style="magenta")
    table.add_column("Base MMR", justify="left", style="green")
    table.add_column("Current MMR", justify="left", style="green")
    table.add_column("Count", justify="left", style="green")
    table.add_column("Keeper", justify="left", style="green")

    for d in data:
        p: LeaguePlayer = d["player"]
        # if p.status == Status.DROPPED:
        #     continue
        table.add_row(p.player.rsc_id, p.player.name, str(p.base_mmr), str(p.current_mmr), str(d["count"]), str(d["keeper"]))

    console.print(table)

async def calculate_rounds(tier: str | None = None) -> None:
    """Calculate rounds for a given tier"""
    season = await current_season()

    # results: dict[int, list[dict]] = {}
    promos = {}
    for t in season.season_tier_data:
        results: list[CountKeeper] = []

        if tier and t.tier != tier:
            continue

        console.print("=" * 20)
        console.print(f"Tier: {t.tier}")
        tcount = t.team_number
        if not tcount:
            raise AttributeError(f"Tier {t.tier} has no team count")

        players = await tier_players(t.tier)
        console.print("=" * 20)
        console.print(f"Player Count: {len(players)}")
        console.print("=" * 20)
        console.print(f"Players[0]: {players[0].player.name} - {players[0].current_mmr}")

        idx = 0
        for i in range(1, 6):
            console.print(f"Index: {idx}")
            console.print(f"Round {i} - Players: {tcount}")
            # console.print(f"Pulling {len(players[idx:idx+tcount])}")
            nextup = players[idx:idx+tcount]
            # print(f"Nextup Len: {len(nextup)}")
            for n in nextup:
                results.append({
                    "player": n,
                    "count": i,
                    "keeper": i
                })
                idx += 1


            # Bump index
            # idx += tcount
            if idx >= (len(players) - 1):
                console.print("Hit end of tier players early")
                break

            last_player = results[-1]["player"]
            # print(f"Last Player: {last_player.id} - {last_player.player.name} - {last_player.current_mmr}")
            # print(f"Index Player: {players[idx].id} - {players[idx].player.name} - {players[idx].current_mmr}")
            while last_player.current_mmr == players[idx].current_mmr and last_player.id != players[idx].id:
                console.print(f"Duplicate MMR: {last_player.current_mmr} - {players[idx].player.name}")

                results.append({
                    "player": players[idx],
                    "count": i + 1,
                    "keeper": i
                })

                last_player = players[idx]
                idx += 1
                console.print(f"idx: {idx}")
                if idx >= (len(players)-1):
                    break

        # rest go to rd 6
        if idx < (len(players)-1):
            console.print(f"Adding remaining players to round 6")
            for n in players[idx:]:
                results.append({
                    "player": n,
                    "count": 6,
                    "keeper": 6
                })


        console.log(f"Total CountKeepers: {len(players)}")
        await print_count_keeper(results)

        rd5 = [x["player"] for x in results if x["keeper"] == 5]
        promo_mmr = max(rd5, key=lambda x: x.current_mmr)
        promos[t.tier] = promo_mmr.current_mmr

    for t, v in promos.items():
        console.print(f"{t} Promotion MMR: {v}")

        # test = [x["player"].player.name for x in results[:32]]
        # print("\n".join(sorted(test)))



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
