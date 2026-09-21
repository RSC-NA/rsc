#!/usr/bin/env python3

import argparse
import asyncio
import collections
import logging
import os
import sys
from enum import StrEnum
from pprint import pformat

import numpy as np
import pandas as pd
from rich.console import Console
from rich.logging import RichHandler
from rscapi.exceptions import BadRequestException
from rscapi import (
    ApiClient,
    Configuration,
    DraftInput,
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

#  Manually skip a pick for whatever reason. Entries are (tier, round, pick).
#  Clear this out between seasons -- a stale entry silently drops a real pick.
MANUAL_SKIP: list[tuple[str, int, int]] = [
    ("Prospect", 3, 55),
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
        tiers.sort(key=lambda t: t.position, reverse=True)

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
    dry: bool = False,
) -> TransactionResponse | None:
    """Fetch transaction history based on specified criteria"""
    draft_pick = DraftInput(
        league=1,
        player=player,
        executor=138778232802508801,
        team=team,
        round=round,
        number=pick,
        admin_override=override,
    )
    # Built and logged before the dry check so a dry run still shows the exact
    # payload -- that is the whole point of pairing --dry with --debug.
    logger.debug(
        "Draft Schema%s: %s",
        " (dry run, not sent)" if dry else "",
        pformat(draft_pick),
    )
    if dry:
        return None

    async with ApiClient(CONF) as client:
        api = TransactionsApi(client)
        return await api.transactions_draft_create(draft_pick)

async def teams(
    seasons: list[int] | None = None,
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
        # The API caps a page at 500 rows, so follow `next` instead of asking for one big `limit`.
        results: list[LeaguePlayer] = []
        while True:
            page = await api.league_players_list(
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
                limit=500,
                offset=len(results),
            )
            results.extend(page.results)
            if not page.results or not page.next:
                return results



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

    logger.debug("Parsed draft CSV:\n%s", df.to_string(index=False))
    # with pd.option_context('display.max_rows', None, 'display.max_columns', None):  # more options can be specified also
    #     print(df["Player Id"])
    # print(df.dtypes)
    return df

async def process_tier_random(season: int, layout: pd.DataFrame, tier: str, pick:int, dry:bool=False, delay:float=0.0, override:bool=False) -> None:
    tier_layout = layout.loc[layout["Tier"].astype("string").str.casefold() == tier.casefold()].copy()
    manual_skip_for_tier = {
        (skip_round, skip_pick)
        for skip_tier, skip_round, skip_pick in MANUAL_SKIP
        if skip_tier.casefold() == tier.casefold()
    }

    logger.info("Getting player list for %s", tier)
    resp = await players(tier_name=tier, season_number=season)
    resp.sort(key=lambda p: p.id or 0)

    # PERM_FA/PERMFA_W are rejected outright by the API ("Player is a permanent
    # free agent. Cannot be drafted."), so they have to go before a redraft
    # pulls them out of plist -- unlike RO, which a redraft legitimately reuses.
    blocked_statuses = {
        Status.DROPPED,
        Status.FORMER,
        Status.UNSIGNED_GM,
        Status.BANNED,
        Status.PERM_FA,
        Status.PERMFA_W,
    }
    original_count = len(resp)
    plist = [lp for lp in resp if lp.status not in blocked_statuses]
    filtered_count = original_count - len(plist)
    if filtered_count:
        dropped = collections.Counter(
            getattr(lp.status, "value", str(lp.status)) for lp in resp if lp.status in blocked_statuses
        )
        logger.info(
            "Filtered out %s blocked-status players from draft pool (%s)",
            filtered_count,
            ", ".join(f"{status}={count}" for status, count in sorted(dropped.items())),
        )

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

    eligible.sort(key=lambda p: p.id or 0)
    logger.info("Total FA/DE players: %s", len(eligible))

    is_redraft = True if len(eligible) < len(plist) else False
    if is_redraft:
        logger.warning("Redraft detected. Drafting from entire player list instead of eligible pool")

    # Every keeper in the layout is pre-assigned, so all of them have to leave
    # the pool before the first pick is made. Removing a keeper only when their
    # own row comes up is too late: an auto-pick at an earlier pick can draft a
    # player who is a keeper further down the layout, and that player then gets
    # drafted twice.
    keeper_ids = {int(kid) for kid in tier_layout["Discord ID"].dropna().tolist()}
    if keeper_ids:
        reserved: set[int] = set()
        for pool in (plist, eligible):
            kept = []
            for lp in pool:
                lp_player = getattr(lp, "player", None)
                lp_discord_id = getattr(lp_player, "discord_id", None)
                if lp_discord_id is not None and int(lp_discord_id) in keeper_ids:
                    reserved.add(int(lp_discord_id))
                    continue
                kept.append(lp)
            pool[:] = kept
        logger.info(
            "Reserved %s of %s layout keepers out of the draft pool",
            len(reserved),
            len(keeper_ids),
        )
        missing = keeper_ids - reserved
        if missing:
            logger.debug("Keepers not present in the pool (already rostered elsewhere): %s", sorted(missing))

    logger.info("Starting draft at pick: %s", pick)
    unfilled: list[int] = []
    for idx, pos in tier_layout.iterrows():
        logger.info("[%s] Round: %s Pick: %s", tier, pos["Round #"], pos["Pick #"])

        round_no = int(pos["Round #"])
        pick_no = int(pos["Pick #"])

        # Neither of these ever took a player, so they are dropped before the
        # pool is touched: a manual skip never happened, and an empty red square
        # is not a pick at all.
        if (round_no, pick_no) in manual_skip_for_tier:
            logger.warning("Manually skipping [%s] Round %s Pick %s", tier, round_no, pick_no)
            continue

        gm = pos["Pick Owner"]

        if gm == "-":
            logger.debug("Skipping empty red square")
            continue

        # Picks before --pick already happened, so they still have to be
        # replayed against the pool. Skipping the row outright left the pool at
        # index 0, which handed pick 6 the player pick 1 already took.
        resume_skip = pick_no < pick

        pid = None
        pname = None
        draftee = None
        if not pd.isna(pos["Discord ID"]):
            # No pool removal needed here -- every keeper was already reserved
            # out of both pools before the loop started.
            pname = pos["Player Name"]
            pid = int(pos["Discord ID"])
        elif resume_skip and not is_redraft:
            # `eligible` holds only FA/DE. An already-drafted player is now RO,
            # so the pool dropped them on its own -- consuming here too would
            # skip that many live players.
            logger.debug("Pick %s already drafted, eligible pool self-corrected", pick_no)
            continue
        else:
            draft_pool = plist if is_redraft else eligible
            if not draft_pool:
                # Auto-picks are exhausted, but keeper picks further down the
                # layout name their player in the CSV and can still be made.
                # Ending the tier here abandoned them -- a layout can hold more
                # auto-picks than the pool has players and still have keepers
                # queued behind them.
                unfilled.append(pick_no)
                if not resume_skip:
                    logger.warning(
                        "[%s] Round %s Pick %s - no draftable players left, skipping this pick",
                        tier,
                        round_no,
                        pick_no,
                    )
                continue

            draftee = draft_pool.pop(0)
            pname = draftee.player.name if draftee.player else None
            pid = int(draftee.player.discord_id) if draftee.player and draftee.player.discord_id else None
            if not resume_skip:
                logger.info("Player Status in API: %s", draftee.status)

        if resume_skip:
            logger.debug(
                "Skipping pick %s (before --pick %s), advanced pool past %s",
                pick_no,
                pick,
                pname or "keeper",
            )
            continue

        # gm = "Tinsel"
        logger.debug("Pick Owner: %s", gm)
        dst = None
        for t in tdata:
            gm_name = t.franchise.gm.rsc_name if t.franchise and t.franchise.gm else None
            if gm_name and gm_name.lower() == gm.lower():
                dst = t
                break

        if not dst:
            logger.error("Could not find team for GM: %s", gm)
            sys.exit(1)

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



        try:
            tresp = await draft(player=pid, team=dst.name, round=pos["Round #"], pick=pos["Pick #"], override=override, dry=dry)
            if not dry and not tresp:
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

        # Pace picks so each one can be watched landing on the draft page. Only
        # real picks reach here -- every skip path continues above -- so the
        # delay tracks what actually shows up on the site.
        if delay:
            await asyncio.sleep(delay)

    if unfilled:
        logger.warning(
            "[%s] %s pick(s) had no draftable player left and were skipped: %s",
            tier,
            len(unfilled),
            ", ".join(str(p) for p in unfilled),
        )


async def test_draft(season: int, draftcsv: str, tier: str, pick: int, dry:bool=False, delay:float=0.0, override:bool=False):
    layout = await parse_csv(draftcsv, tier=tier)
    tierlist = await tiers()

    if tier and not any(t.name.lower() == tier.lower() for t in tierlist):
        logger.error("[!] Tier does not exist: %s", tier)
        sys.exit(1)

    for t in tierlist:
        if tier and t.name.lower() != tier.lower():
            continue
        await process_tier_random(season=season, layout=layout, tier=t.name, pick=pick, dry=dry, delay=delay, override=override)



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
    parser.add_argument(
        '-d', '--delay', dest="delay", type=float, default=0.0, metavar="SECONDS",
        help='Wait SECONDS between picks so each one can be watched land on the draft page (e.g. 2 or 1.5). Default: no delay')
    parser.add_argument(
        '-o', '--override', action="store_true", default=False,
        help='Send picks with admin_override so the API skips draft validation. Needed to re-run a draft without resetting the staging DB. Default: off')
    parser.add_argument(
        '--debug', action="store_true", default=False,
        help='Enable debug logging, including the DraftInput payload sent for each pick. Overrides RSC_DRAFT_LOG_LEVEL')
    argv = parser.parse_args()

    if argv.pick < 1:
        logger.error("Pick must be greater than 0")
        sys.exit(1)

    if argv.delay < 0:
        logger.error("Delay must not be negative")
        sys.exit(1)

    # Raise only this script's logger so the payload shows up without dragging
    # in aiohttp/urllib3 debug chatter from the root logger.
    if argv.debug:
        logger.setLevel(logging.DEBUG)

    if argv.override:
        logger.warning("Admin override enabled. API-side draft validation will be skipped.")

    asyncio.run(test_draft(argv.season, argv.draftcsv, tier=argv.tier, pick=argv.pick, dry=argv.dry, delay=argv.delay, override=argv.override))
