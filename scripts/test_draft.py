#!/usr/bin/env python3

import argparse
import asyncio
import logging
import os
import sys
from enum import StrEnum
from typing import cast

import numpy as np
import pandas as pd
from rich.console import Console
from rich.logging import RichHandler
from rscapi.exceptions import BadRequestException
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
LOG_LEVEL = os.environ.get("RSC_DRAFT_LOG_LEVEL", "INFO").upper()

console = Console()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(message)s",
    datefmt="[%X]",
    handlers=[
        RichHandler(
            console=console,
            rich_tracebacks=True,
            markup=True,
            show_path=False,
        )
    ],
)
logger = logging.getLogger("rsc.scripts.test_draft")

#  Manually skip a pick for whatever reason
MANUAL_SKIP = [
    ("Master", 7, 97)
]

if not API_KEY:
    logger.error("RSC API key not found in environment variable RSC_API_KEY")
    sys.exit(1)

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

    # Skip partially empty CSV rows where Tier is missing/blank.
    df["Tier"] = df["Tier"].astype("string").str.strip()
    df = df.loc[df["Tier"].notna() & (df["Tier"] != "")]

    if tier:
        df = df.loc[df["Tier"].str.casefold() == tier.casefold()]

    # df["Player Id"] = df["Player Id"].apply(lambda x: int(x) if not pd.isna(x) else None)
    df["Discord ID"] = df["Discord ID"].astype('Int64')
    df["Pick #"] = df["Pick #"].astype(int)
    df["Round #"] = df["Round #"].astype(int)
    df["Pick / Round"] = df["Pick / Round"].astype(int)

    logger.debug("Parsed draft CSV:\n%s", df.to_string(index=False))
    # with pd.option_context('display.max_rows', None, 'display.max_columns', None):  # more options can be specified also
    #     print(df["Player Id"])
    # print(df.dtypes)
    return df

async def process_tier_random(season: int, layout: pd.DataFrame, tier: str, pick:int, dry:bool=False) -> None:
    tier_layout = layout.loc[layout["Tier"].astype("string").str.casefold() == tier.casefold()].copy()
    manual_skip_for_tier = {
        (skip_round, skip_pick)
        for skip_tier, skip_round, skip_pick in MANUAL_SKIP
        if skip_tier.casefold() == tier.casefold()
    }

    logger.info("Getting player list for %s", tier)
    resp = await players(tier_name=tier, season_number=season)
    resp.sort(key=lambda p: p.id)

    blocked_statuses = {Status.DROPPED, Status.FORMER, Status.UNSIGNED_GM, Status.BANNED}
    original_count = len(resp)
    plist = [lp for lp in resp if lp.status not in blocked_statuses]
    filtered_count = original_count - len(plist)
    if filtered_count:
        logger.info("Filtered out %s blocked-status players from draft pool", filtered_count)

    tdata = await teams(tier=tier)
    logger.debug("Team[0]: %s", tdata[0])

    logger.info("Total draft picks in tier: %s", len(tier_layout))
    logger.info("Found %s players in %s", len(plist), tier)
    eligible: list[LeaguePlayer] = []
    for p in plist:
        if p.status == Status.FREE_AGENT:
            eligible.append(p)
        if p.status == Status.DRAFT_ELIGIBLE:
            eligible.append(p)

    eligible.sort(key=lambda p: p.id)
    logger.info("Total FA/DE players: %s", len(eligible))

    is_redraft = True if len(eligible) < len(plist) else False
    if is_redraft:
        logger.warning("Redraft detected. Drafting from entire player list instead of eligible pool")

    logger.info("Starting draft at pick: %s", pick)
    for idx, pos in tier_layout.iterrows():
        logger.info("[%s] Round: %s Pick: %s", tier, pos["Round #"], pos["Pick #"])
        # print(type(pos["Pick"]))
        if pos["Pick #"] < pick:
            logger.debug("Skipping pick %s because it is less than the specified starting pick %s", pos["Pick #"], pick)
            continue

        round_no = int(pos["Round #"])
        pick_no = int(pos["Pick #"])
        if (round_no, pick_no) in manual_skip_for_tier:
            logger.warning("Manually skipping [%s] Round %s Pick %s", tier, round_no, pick_no)
            continue

        gm = pos["Pick Owner"]

        if gm == "-":
            logger.debug("Skipping empty red square")
            continue

        # gm = "Tinsel"
        logger.debug("Pick Owner: %s", gm)
        dst = None
        for t in tdata:
            if t.franchise.gm.rsc_name.lower() == gm.lower():
                dst = t
                break

        if not dst:
            logger.error("Could not find team for GM: %s", gm)
            sys.exit(1)

        pid = None
        pname = None
        draftee = None
        if not pd.isna(pos["Discord ID"]):
            pname = pos["Player Name"]
            pid = int(pos["Discord ID"])

            # Remove keeper from the pool so this player is not drafted again.
            for lp_idx, lp in enumerate(plist):
                lp_player = getattr(lp, "player", None)
                lp_discord_id = getattr(lp_player, "discord_id", None)
                if lp_discord_id is not None and lp_discord_id == pid:
                    plist.pop(lp_idx)
                    break
        else:

            try:
                if is_redraft:
                    draftee = plist.pop(0)
                else:
                    draftee = eligible.pop(0)
            except IndexError:
                logger.warning("No more eligible players. Finished draft.")
                break

            if not draftee:
                logger.warning("No more eligible players. Finished draft.")
                break
            pname = draftee.player.name if draftee.player else None
            pid = int(draftee.player.discord_id) if draftee.player and draftee.player.discord_id else None
            logger.info("Player Status in API: %s", draftee.status)


        if not pname or not pid:
            logger.error("Player name or ID is missing for pick at Round %s Pick %s", pos["Round #"], pos["Pick #"])
            sys.exit(1)

        logger.info(
            "[%s] Round %s Pick %s - Drafting %s (%s) to %s (%s)",
            tier,
            pos["Round #"],
            pos["Pick #"],
            pname,
            pid,
            dst.name,
            draftee.status if draftee else "KEEPER",
        )



        if not dry:
            try:
                resp = await draft(player=pid, team=dst.name, round=pos["Round #"], pick=pos["Pick #"], override=True)
                # resp = await draft(player=pid, team=dst.name, round=pos["Round #"], pick=pos["Pick #"])
                if not resp:
                    logger.error("No transaction response from server...")
                    sys.exit(1)
            except BadRequestException as exc:
                if dst:
                    logger.error(
                        "Failed to draft %s (%s) to %s (%s) at Round %s Pick %s",
                        pname,
                        pid,
                        dst.name,
                        dst.franchise.name,
                        pos["Round #"],
                        pos["Pick #"],
                    )
                if hasattr(exc, "body") and exc.body:
                    logger.error("Response body: %s", exc.body)
                sys.exit(1)




async def test_draft(season: int, draftcsv: str, tier: str, pick: int, dry:bool=False):
    layout = await parse_csv(draftcsv, tier=tier)
    tierlist = await tiers()

    if tier and not any(t.name.lower() == tier.lower() for t in tierlist):
        logger.error("[!] Tier does not exist: %s", tier)
        sys.exit(1)

    for t in tierlist:
        if tier and t.name.lower() != tier.lower():
            continue
        await process_tier_random(season=season, layout=layout, tier=t.name, pick=pick, dry=dry)



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Test RSC draft on staging')
    parser.add_argument(
        'season', type=int, default=None,
        help='Season Number')
    parser.add_argument(
        'draftcsv', type=str, default=None,
        help='CSV file from Draft Layout (Bot Command Tab)')

    parser.add_argument(
        "-t", "--tier", type=str, default=None,
        help='Tier')
    parser.add_argument(
        '-p', '--pick', dest="pick", type=int, default=1,
        help='Start at pick within tier (Resume from error)')
    parser.add_argument(
        '--dry', action="store_true", default=False,
        help='Dry run. (Do not send draft pick to API)')
    argv = parser.parse_args()

    if argv.pick < 1:
        logger.error("Pick must be greater than 0")
        sys.exit(1)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(test_draft(argv.season, argv.draftcsv, tier=argv.tier, pick=argv.pick, dry=argv.dry))
    # loop.run_until_complete(get_rostered_players())
    loop.close()
