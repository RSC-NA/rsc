#!/usr/bin/env python3

import asyncio
import os
from enum import StrEnum
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



async def validate_league_players():
    print("Validating RSC IDs")
    c = 0
    async for p in paged_players():
        c += 1
        if (c % 100) == 0:
            print(f"Count: {c}")

        # Check MMR attached
        if not p.base_mmr and p.current_mmr:
            print(f"RSC{p.id} ({p.player.discord_id}) missing MMR value")

        if not (p.tier and p.tier.name) and p.status not in (Status.PERMFA_W, Status.DROPPED):
                print(f"RSC{p.id} ({p.player.discord_id}) has no tier data")

        # Check Rostered but no team
        if p.status == Status.ROSTERED:
            if not (p.team and p.team.name):
                print(f"RSC{p.id} ({p.player.discord_id}) is Rostered but has no team")
            if not p.contract_length:
                print(f"RSC{p.id} ({p.player.discord_id}) is rostered with no contract length")

        # Check if FA and on team
        if p.status == Status.FREE_AGENT:
            if (p.team and p.team.name):
                print(f"RSC{p.id} ({p.player.discord_id}) is a Free Agent but has a team")

            if p.contract_length:
                print(f"RSC{p.id} ({p.player.discord_id}) is free agent with a contract length")

        # Check contract length



if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(validate_league_players())
    loop.close()
