#!/usr/bin/env python3
"""Read-only probe of the live RSC API. It shows who a sync treats as a league player around a season change.

It sends GET requests only, and never connects to Discord.

The probe runs the checkout's own league player read against the live API, then
checks the result against rows it fetched itself. On a checkout that predates
`effective_players` it runs the default-season read.

    RSC_API_KEY=... uv run python scripts/sync_season_probe.py
    RSC_API_KEY=... uv run python scripts/sync_season_probe.py --lane regression
    RSC_API_KEY=... uv run python scripts/sync_season_probe.py --lane agms
    RSC_API_KEY=... uv run python scripts/sync_season_probe.py --time
"""

import argparse
import asyncio
import importlib
import os
import sys
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import discord
from rscapi import ApiClient, Configuration
from rscapi.api.franchises_api import FranchisesApi
from rscapi.api.league_players_api import LeaguePlayersApi
from rscapi.api.leagues_api import LeaguesApi
from rscapi.api.seasons_api import SeasonsApi
from rscapi.exceptions import NotFoundException
from rscapi.models.error_code_enum import ErrorCodeEnum
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.season import Season
from rscapi.rest import RESTResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rsc.core import RSC
from rsc.exceptions import NotFoundError

LEAGUE = 1
UNKNOWN_LEAGUE = 999_999
GUILD_ID = 395806681994493964
HOST = "https://api.rscna.com/api/v1"
ROSTERED = {"RO", "RN", "IR", "AR", "UG"}
GONE = {"DR", "FR", "BN"}
WAITING = {"FA", "PF", "PW", "DE", "WV", "WC", "WR"}


class GetOnlyClient(ApiClient):
    def __init__(self, configuration: Configuration):
        super().__init__(configuration)
        self.requests: list[str] = []

    async def call_api(
        self,
        method: str,
        url: str,
        header_params: dict | None = None,
        body: object = None,
        post_params: list | None = None,
        _request_timeout: object = None,
    ) -> RESTResponse:
        if method != "GET":
            raise RuntimeError(f"The probe is read-only. It refused {method} {url}")
        self.requests.append(url)
        return await super().call_api(method, url, header_params, body, post_params, _request_timeout)

    def count(self, path: str) -> int:
        return sum(path in url for url in self.requests)


class ProbeCog(RSC):
    def __init__(self, client: GetOnlyClient):
        self._league = {GUILD_ID: LEAGUE}
        self._api_clients = {GUILD_ID: client}


class ClosedSignupsCog(ProbeCog):
    async def next_signup_season(self, guild: discord.Guild) -> Season | None:
        raise NotFoundError(404, "Signups are closed. Set in memory by the probe.", code=ErrorCodeEnum.NO_SIGNUP_SEASON)


class UnknownLeagueSignupCog(ProbeCog):
    async def next_signup_season(self, guild: discord.Guild) -> Season | None:
        async with self.api_client(guild) as client:
            return await SeasonsApi(client).seasons_signup_season_retrieve(league=UNKNOWN_LEAGUE)


def status(row: LeaguePlayer) -> str:
    return str(getattr(row.status, "value", row.status))


def trunk_is_playing(row: LeaguePlayer | None) -> bool:
    return row is not None and status(row) != "DR"


def load_rule() -> ModuleType | None:
    try:
        return importlib.import_module("rsc.leagues.effective")
    except ImportError:
        return None


@dataclass
class Facts:
    client: GetOnlyClient
    cog: ProbeCog
    guild: discord.Guild
    rule: ModuleType | None
    now: datetime
    old: Season
    new: Season
    by_old: dict[int, LeaguePlayer]
    by_new: dict[int, LeaguePlayer]
    declared: set[int]
    unanswered: set[int]
    synced: dict[int, LeaguePlayer]

    @property
    def old_only_active(self) -> set[int]:
        return {d for d, row in self.by_old.items() if d not in self.by_new and status(row) not in GONE}

    def playing(self, row: LeaguePlayer | None) -> bool:
        return self.rule.is_playing(row) if self.rule else trunk_is_playing(row)

    def pick(self, discord_id: int, seasons: list[Season], signups_open: bool) -> LeaguePlayer | None:
        if self.rule is None:
            raise SystemExit("This lane needs a checkout that has rsc/leagues/effective.py.")
        rows = [by[discord_id] for by in (self.by_old, self.by_new) if discord_id in by]
        return self.rule.pick_effective_row(rows, seasons, self.now, signups_open, discord_id in self.declared)


def read(cog: ProbeCog, guild: discord.Guild, rule: ModuleType | None):
    return cog.effective_players(guild) if rule else cog.paged_players(guild)


async def season_rows(client: ApiClient, season: Season) -> dict[int, LeaguePlayer]:
    api = LeaguePlayersApi(client)
    out: dict[int, LeaguePlayer] = {}
    offset = 0
    while True:
        page = await api.league_players_list(league=LEAGUE, season=season.id, limit=500, offset=offset)
        out.update({row.player.discord_id: row for row in page.results if row.player.discord_id})
        offset += len(page.results)
        if not page.next:
            return out


async def lane_regression(f: Facts) -> bool:
    stripped = {d for d in f.old_only_active if not f.playing(f.synced.get(d))}
    wrongly = stripped - f.declared
    undeclared = f.old_only_active - f.declared
    expected = 0 if f.rule else len(undeclared)
    print(f"members with an active S{f.old.number} row and no S{f.new.number} row:", len(f.old_only_active))
    print('  of those, declared "not returning":', len(f.old_only_active & f.declared))
    print("  of those, treated as non-playing by this checkout:", len(stripped))
    print("stripped by nonplaying while sign-ups are open:", len(wrongly), f"(expected {expected} on this checkout)")
    return len(wrongly) == expected


async def lane_newest_wins(f: Facts) -> bool:
    wrong = [d for d, row in f.by_new.items() if f.synced.get(d) is None or f.synced[d].id != row.id]
    print(f"members with an S{f.new.number} row:", len(f.by_new))
    print(f"  not resolved to their S{f.new.number} row:", len(wrong))
    return bool(f.by_new) and not wrong


async def lane_gone(f: Facts) -> bool:
    gone = {d for d, row in f.by_old.items() if d not in f.by_new and status(row) in GONE}
    playing = [d for d in gone if f.playing(f.synced.get(d))]
    print(f"members whose only row is S{f.old.number} with DR, FR or BN:", len(gone))
    print("  counted as playing:", len(playing))
    return bool(gone) and not playing


async def lane_preflip(f: Facts) -> bool:
    unfinished = f.old.model_copy(update={"end_date": f.now + timedelta(days=30)})
    picked: Counter[tuple[str, str, int | None]] = Counter()
    wrong = 0
    for d in f.by_old.keys() & f.by_new.keys():
        row = f.pick(d, [unfinished, f.new], signups_open=True)
        old_status, new_status = status(f.by_old[d]), status(f.by_new[d])
        picked[old_status, new_status, row.season if row else None] += 1
        want = f.old.number if old_status in ROSTERED else f.new.number
        wrong += row is None or row.season != want
    print(f"S{f.old.number} end date moved to {unfinished.end_date:%Y-%m-%d} in memory. Members with a row in both seasons:")
    for (old_status, new_status, season), n in sorted(picked.items(), key=lambda kv: -kv[1]):
        print(f"  {old_status} -> {new_status}: {n} resolve to S{season}")
    print(f"  not on the S{f.old.number} row while rostered there, or not on the S{f.new.number} row otherwise:", wrong)
    return bool(picked) and not wrong


async def lane_closed(f: Facts) -> bool:
    members = f.by_old.keys() | f.by_new.keys()
    by_rule = [f.pick(d, [f.old, f.new], signups_open=False) for d in members]
    old_by_rule = sum(row is not None and row.season == f.old.number for row in by_rule)
    by_read = [row async for row in ClosedSignupsCog(f.client).effective_players(f.guild)]
    old_by_read = sum(row.season == f.old.number for row in by_read)
    print("sign-ups marked closed in memory.")
    print(f"  rule: {len(members)} members, {old_by_rule} resolve to an S{f.old.number} row")
    print(f"  read: {len(by_read)} rows, {old_by_read} from S{f.old.number}")
    return bool(by_read) and not old_by_rule and not old_by_read


async def lane_other_404(f: Facts) -> bool:
    print(f"sign-up season lookup sent for league {UNKNOWN_LEAGUE}, which the API does not have.")
    try:
        rows = [row async for row in UnknownLeagueSignupCog(f.client).effective_players(f.guild)]
    except NotFoundError as exc:
        print(f"  the read stopped: {exc}")
        return exc.code is not None and exc.code is not ErrorCodeEnum.NO_SIGNUP_SEASON
    print(f"  the read went on as if sign-ups were closed, and returned {len(rows)} rows")
    return False


async def lane_not_returning(f: Facts) -> bool:
    leaving = f.old_only_active & f.declared
    still_playing = [d for d in leaving if f.playing(f.synced.get(d))]
    silent = f.old_only_active & f.unanswered
    stripped = [d for d in silent if not f.playing(f.synced.get(d))]
    print(f'members with an S{f.old.number}-only active row and a declared "not returning":', len(leaving))
    print("  still counted as playing:", len(still_playing))
    print(f"members with an S{f.old.number}-only active row and an unanswered intent (missing true):", len(silent))
    print("  counted as non-playing:", len(stripped))
    return bool(leaving) and not still_playing and not stripped


async def lane_agms(f: Facts) -> bool:
    franchises = await FranchisesApi(f.client).franchises_list(league=LEAGUE)
    agm_of = {a.discord_id: fr for fr in franchises for a in (fr.agms or []) if a.discord_id}
    by_status = Counter(status(f.synced[d]) if d in f.synced else "no row" for d in agm_of)
    waiting = sorted((d for d in agm_of if d in f.synced and status(f.synced[d]) in WAITING), key=lambda d: agm_of[d].name or "")
    no_prefix = [d for d in waiting if not agm_of[d].prefix]
    print("AGMs:", len(agm_of), "by effective row status:", ", ".join(f"{st} {n}" for st, n in by_status.most_common()))
    print("AGMs with a non-rostered effective row:", len(waiting))
    for d in waiting:
        row, fr = f.synced[d], agm_of[d]
        print(f"  {status(row)} S{row.season} {row.player.name}: {fr.prefix} | {fr.name}")
    print("  whose franchise has no prefix:", len(no_prefix))
    return bool(waiting) and not no_prefix


LANES: dict[str, Callable[[Facts], Awaitable[bool]]] = {
    "regression": lane_regression,
    "newest-wins": lane_newest_wins,
    "gone": lane_gone,
    "preflip": lane_preflip,
    "closed": lane_closed,
    "other-404": lane_other_404,
    "not-returning": lane_not_returning,
    "agms": lane_agms,
}


async def gather_facts(client: GetOnlyClient, cog: ProbeCog, guild: discord.Guild, rule: ModuleType | None) -> Facts:
    seasons_api = SeasonsApi(client)
    default = await LeaguesApi(client).leagues_current_season_retrieve(LEAGUE)
    try:
        new = await seasons_api.seasons_signup_season_retrieve(league=LEAGUE)
    except NotFoundException:
        raise SystemExit("No season is taking sign-ups, so there is no overlap to probe.")
    old = (await seasons_api.seasons_list(league=LEAGUE, number=(new.number or 0) - 1))[0]
    for season in (old, new):
        print(f"S{season.number} id {season.id} ends {season.end_date} sign-ups {season.signups_open} to {season.signup_close}")
    print(f"default season S{default.number}, sign-up season S{new.number}")

    by_old, by_new = await season_rows(client, old), await season_rows(client, new)
    both = by_old.keys() & by_new.keys()
    print(f"S{old.number} rows {len(by_old)}, S{new.number} rows {len(by_new)}, in both {len(both)}")
    cross = Counter((status(by_old[d]), status(by_new[d])) for d in both)
    print("cross-tab:", ", ".join(f"{a}->{b} {n}" for (a, b), n in cross.most_common()))

    intents = await seasons_api.seasons_player_intents_list(new.id or 0)
    declared = {i.player.player.discord_id for i in intents if i.player and i.missing is False and i.returning is False}
    unanswered = {i.player.player.discord_id for i in intents if i.player and i.missing}
    print(f'S{new.number} intents {len(intents)}, declared "not returning" {len(declared)}, unanswered {len(unanswered)}')

    synced = {row.player.discord_id: row async for row in read(cog, guild, rule) if row.player.discord_id}
    return Facts(client, cog, guild, rule, datetime.now(UTC), old, new, by_old, by_new, declared, unanswered, synced)


async def open_connection(client: GetOnlyClient) -> None:
    await LeaguesApi(client).leagues_retrieve(LEAGUE)
    client.requests.clear()


async def timed_read(client: GetOnlyClient, cog: ProbeCog, guild: discord.Guild, rule: ModuleType | None) -> None:
    await open_connection(client)
    start = time.perf_counter()
    rows = [row async for row in read(cog, guild, rule)]
    wall = time.perf_counter() - start
    pages, intents = client.count("/league-players"), client.count("/player_intents")
    print(
        f"rows {len(rows)} | league player pages {pages} | intents requests {intents} "
        f"| other requests {len(client.requests) - pages - intents} | wall {wall:.2f} s"
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lane", choices=LANES, action="append", help="Run one lane. Repeat for more. Default: every lane.")
    parser.add_argument("--time", action="store_true", help="Time the league player read of one sync, and count its requests.")
    args = parser.parse_args()

    conf = Configuration(host=HOST, api_key={"Api-Key": os.environ["RSC_API_KEY"]}, api_key_prefix={"Api-Key": "Api-Key"})
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    rule = load_rule()
    async with GetOnlyClient(conf) as client:
        cog = ProbeCog(client)
        print("now UTC", datetime.now(UTC).isoformat(timespec="seconds"))
        print("read under test:", "effective_players" if rule else "paged_players, default season only")
        if args.time:
            await timed_read(client, cog, guild, rule)
            return 0

        facts = await gather_facts(client, cog, guild, rule)
        failed = []
        for name in args.lane or LANES:
            print(f"\n[{name}]")
            ok = await LANES[name](facts)
            print("PASS" if ok else "FAIL")
            if not ok:
                failed.append(name)
        print(f"\n{len(client.requests)} requests, all GET.", f"failed: {', '.join(failed)}" if failed else "every lane passed")
        return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
