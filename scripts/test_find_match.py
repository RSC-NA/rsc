#!/usr/bin/env python3

import asyncio
import os
import sys
from datetime import datetime
from enum import StrEnum
from typing import AsyncIterator

from rscapi import ApiClient, Configuration, MembersApi, MatchesApi, ApiException
from rscapi.models import LeaguePlayer, Match

API_KEY = os.environ.get("RSC_API_KEY")
API_HOST = "https://api.rscna.com/api/v1"
#API_HOST = "http://127.0.0.1:8000/api/v1"

CONF = Configuration(
    host=API_HOST,
    api_key={"Api-Key": API_KEY},
    api_key_prefix={"Api-Key": "Api-Key"},
)


class MatchType(StrEnum):
    REGULAR = "REG"  # Regular Season
    PRESEASON = "PRE"  # Pre-season
    POSTSEASON = "PST"  # Post-Season
    FINALS = "FNL"  # Finals
    ANY = "ANY"  # All Match Types

    @property
    def full_name(self):
        match self:
            case MatchType.REGULAR:
                return "Regular Season"
            case MatchType.PRESEASON:
                return "Pre-season"
            case MatchType.POSTSEASON:
                return "Post Season"
            case MatchType.FINALS:
                return "Finals"
            case MatchType.ANY:
                return "Any"


class MatchFormat(StrEnum):
    GAME_SERIES = "GMS"  # Game Series
    BEST_OF_THREE = "BO3"  # Best of Three
    BEST_OF_FIVE = "BO5"  # Best of Five
    BEST_OF_SEVEN = "BO7"  # Best of Seven

async def find_match(
    teams: list[str],
    date_lt: datetime | None = None,
    date_gt: datetime | None = None,
    season: int | None = None,
    season_number: int | None = None,
    day: int | None = None,
    match_type: MatchType | None = None,
    match_format: MatchFormat | None = None,
    limit: int = 0,
    offset: int = 0,
) -> list[Match]:
    async with ApiClient(CONF) as client:
        api = MatchesApi(client)
        teams_fmt = ",".join(teams)
        resp = await api.matches_find_match(
            teams=teams_fmt,
            date__lt=date_lt,
            date__gt=date_gt,
            season=season,
            season_number=season_number,
            day=day,
            match_type=str(match_type) if match_type else None,
            match_format=str(match_format) if match_format else None,
            league=1,
            limit=limit,
            offset=offset,
        )
        return resp.results

if __name__ == "__main__":
    matches = asyncio.run(find_match(
        teams=["Raptors", "Orochi"],
        season_number=25,
        day=12,
        limit=1,
        offset=0,
    ))

    for match in matches:
        print(match)
