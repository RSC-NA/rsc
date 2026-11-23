#!/usr/bin/env python3
"""Run one role sync on the test server and print the Discord requests it sent.

The lab logs in over HTTP only. It opens no gateway connection, so no cog runs
and the test bot never shows as online. It builds the league player row itself
and never calls the RSC API. Stop the dev bot first.

    export RSC_LAB_BOT_TOKEN=... RSC_LAB_GUILD_ID=... RSC_LAB_MEMBER_ID=...
    uv run python scripts/sync_lab.py fresh-to-de
    uv run python scripts/sync_lab.py fresh-to-de --repeat 5

Each scenario sets the lab member's starting roles and nickname, runs the
checkout's own `update_league_player_discord`, then fetches the member again
and prints what changed. `reset` only sets the starting state of a new member.
`nick-forbidden` needs the lab member to be the server owner.

On a checkout that predates `rsc/transactions/writer.py` the lab still runs,
without the summary line, so the two can be compared.
"""

import argparse
import asyncio
import contextlib
import importlib
import logging
import os
import statistics
import sys
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace

import aiohttp
import discord
from rscapi.models.franchise_gm import FranchiseGM
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.league_player_member import LeaguePlayerMember
from rscapi.models.league_player_status_enum import LeaguePlayerStatusEnum
from rscapi.models.player_franchise import PlayerFranchise
from rscapi.models.player_team import PlayerTeam
from rscapi.models.tier import Tier

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rsc import const
from rsc.enums import Status
from rsc.transactions import roles
from rsc.utils import utils

PRODUCTION_GUILD_ID = 395806681994493964
ENV = ("RSC_LAB_BOT_TOKEN", "RSC_LAB_GUILD_ID", "RSC_LAB_MEMBER_ID")
LAB_PREFIX = "LAB"
STATUS_ROLES = frozenset(
    {
        const.LEAGUE_ROLE,
        const.SPECTATOR_ROLE,
        const.FORMER_PLAYER_ROLE,
        const.FREE_AGENT_ROLE,
        const.PERM_FA_ROLE,
        const.PERM_FA_WAITING_ROLE,
        const.DRAFT_ELIGIBLE,
        const.IR_ROLE,
        const.CAPTAIN_ROLE,
        const.SUBBED_OUT_ROLE,
        const.AGM_ROLE,
    }
)


class LabError(Exception):
    pass


def refusal(env: Mapping[str, str], bot_running: bool) -> str | None:
    missing = [name for name in ENV if not env.get(name)]
    if missing:
        return f"Set {', '.join(missing)}."
    if not (env["RSC_LAB_GUILD_ID"].isdigit() and env["RSC_LAB_MEMBER_ID"].isdigit()):
        return "RSC_LAB_GUILD_ID and RSC_LAB_MEMBER_ID must be Discord ids."
    if int(env["RSC_LAB_GUILD_ID"]) == PRODUCTION_GUILD_ID:
        return "RSC_LAB_GUILD_ID is the production server. The lab only runs on the test server."
    if bot_running:
        return "A redbot process is running. Stop the dev bot, then run the lab."
    return None


def redbot_running(proc: Path = Path("/proc")) -> bool:
    pids = [entry for entry in proc.iterdir() if entry.name.isdigit()] if proc.is_dir() else []
    if not pids:
        raise LabError(f"The process list at {proc} cannot be read, so the lab cannot tell whether the dev bot is running.")
    for pid in pids:
        try:
            argv = (pid / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if any(Path(os.fsdecode(arg)).name == "redbot" for arg in argv):
            return True
    return False


@dataclass(frozen=True)
class Lab:
    tiers: tuple[str, ...]
    franchise_role: str
    name: str

    @property
    def tier(self) -> str:
        return self.tiers[0]

    @classmethod
    def of(cls, guild: discord.Guild, member: discord.Member) -> "Lab":
        names = {role.name for role in guild.roles}
        tiers = tuple(sorted(name for name in names if f"{name}FA" in names))
        franchise_roles = sorted(name for name in names if utils.FRANCHISE_ROLE_REGEX.match(name))
        if not tiers:
            raise LabError("The server has no tier. The lab needs a role pair such as Premier and PremierFA.")
        if not franchise_roles:
            raise LabError("The server has no franchise role. The lab needs one named like 'The Ocean (gm name)'.")
        return cls(tiers=tiers, franchise_role=franchise_roles[0], name=utils.rsc_name_from_member(member))

    def row(self, member: discord.Member, status: Status) -> LeaguePlayer:
        franchise, gm = self.franchise_role.removesuffix(")").split(" (", 1)
        return LeaguePlayer.model_construct(
            status=LeaguePlayerStatusEnum(status.value),
            captain=False,
            tier=Tier(name=self.tier, position=1),
            team=PlayerTeam(
                name="Lab", franchise=PlayerFranchise(name=franchise, prefix=LAB_PREFIX, gm=FranchiseGM(rsc_name=gm, discord_id=0))
            ),
            player=LeaguePlayerMember(name=self.name, discord_id=member.id),
        )

    def managed(self, member: discord.Member) -> frozenset[str]:
        tier_roles = {name for tier in self.tiers for name in (tier, f"{tier}FA")}
        return frozenset(
            role.name
            for role in member.roles
            if role.name in STATUS_ROLES or role.name in tier_roles or utils.FRANCHISE_ROLE_REGEX.match(role.name)
        )


@dataclass(frozen=True)
class State:
    roles: frozenset[str]
    prefix: str | None

    def nick(self, lab: Lab) -> str:
        return f"{self.prefix} | {lab.name}" if self.prefix else lab.name


def fresh(_lab: Lab) -> State:
    return State(frozenset(), None)


def draft_eligible(lab: Lab) -> State:
    return State(frozenset({const.LEAGUE_ROLE, const.DRAFT_ELIGIBLE, lab.tier}), "DE")


def rostered(lab: Lab) -> State:
    return State(frozenset({const.LEAGUE_ROLE, lab.tier, lab.franchise_role}), LAB_PREFIX)


def free_agent(lab: Lab) -> State:
    return State(frozenset({const.LEAGUE_ROLE, lab.tier, const.FREE_AGENT_ROLE, f"{lab.tier}FA"}), "FA")


@dataclass(frozen=True)
class Scenario:
    start: Callable[[Lab], State]
    status: Status | None
    end: Callable[[Lab], State]
    nickname_refused: bool = False


SCENARIOS = {
    "reset": Scenario(fresh, None, fresh),
    "fresh-to-de": Scenario(fresh, Status.DRAFT_ELIGIBLE, draft_eligible),
    "de-to-rostered": Scenario(draft_eligible, Status.ROSTERED, rostered),
    "rostered-to-fa": Scenario(rostered, Status.FREE_AGENT, free_agent),
    "no-change": Scenario(draft_eligible, Status.DRAFT_ELIGIBLE, draft_eligible),
    "nick-forbidden": Scenario(fresh, Status.DRAFT_ELIGIBLE, draft_eligible, nickname_refused=True),
}


@dataclass(frozen=True)
class Outcome:
    start_roles: frozenset[str]
    start_nick: str
    final_roles: frozenset[str]
    final_nick: str
    expected_roles: frozenset[str]
    expected_nick: str
    wall_s: float
    error: str | None
    summary: str | None
    summary_requests: dict[str, int] | None

    @property
    def matches(self) -> bool:
        return self.error is None and self.final_roles == self.expected_roles and self.final_nick == self.expected_nick


def load_writer() -> ModuleType | None:
    try:
        return importlib.import_module("rsc.transactions.writer")
    except ImportError:
        return None


async def prepare(guild: discord.Guild, fetch_member: Callable[[], Awaitable[discord.Member]], scenario: Scenario) -> Lab:
    member = await fetch_member()
    lab = Lab.of(guild, member)
    if scenario.nickname_refused and guild.owner_id != member.id:
        raise LabError("nick-forbidden needs RSC_LAB_MEMBER_ID to be the server owner, whose nickname no bot can change.")

    state = scenario.start(lab)
    absent = state.roles - {role.name for role in guild.roles}
    if absent:
        raise LabError(f"The server lacks the roles {sorted(absent)}. Run /admin sync requiredroles on the test server.")
    held = lab.managed(member)
    remove = [role for role in member.roles if role.name in held - state.roles]
    add = [role for role in guild.roles if role.name in state.roles - held]
    if remove:
        await member.remove_roles(*remove)
    if add:
        await member.add_roles(*add)
    if not scenario.nickname_refused and member.display_name != state.nick(lab):
        await member.edit(nick=state.nick(lab))
    return lab


async def sync(guild: discord.Guild, fetch_member: Callable[[], Awaitable[discord.Member]], scenario: Scenario, lab: Lab) -> Outcome:
    member = await fetch_member()
    start_roles, start_nick = lab.managed(member), member.display_name
    expected = scenario.end(lab)

    writer = load_writer()
    error = None
    summary = None
    summary_requests = None
    wall_s = 0.0
    if scenario.status:
        row = lab.row(member, scenario.status)
        tiers = [Tier(name=name, position=position) for position, name in enumerate(lab.tiers, start=1)]
        with writer.sync_run(writer.SyncKind.MEMBER, guild) if writer else contextlib.nullcontext() as stats:
            if writer:
                writer.member_visited()
            started = time.perf_counter()
            try:
                await roles.update_league_player_discord(guild=guild, player=member, league_player=row, tiers=tiers, agm_franchise=None)
            except (discord.HTTPException, ValueError, AttributeError) as exc:
                error = f"{type(exc).__name__}: {exc}"
            wall_s = time.perf_counter() - started
        if stats:
            summary = stats.summary()
            summary_requests = {request.value: count for request, count in stats.requests.items()}

    member = await fetch_member()
    return Outcome(
        start_roles=start_roles,
        start_nick=start_nick,
        final_roles=lab.managed(member),
        final_nick=member.display_name,
        expected_roles=expected.roles,
        expected_nick=start_nick if scenario.nickname_refused else expected.nick(lab),
        wall_s=wall_s,
        error=error,
        summary=summary,
        summary_requests=summary_requests,
    )


class Requests:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def trace(self) -> aiohttp.TraceConfig:
        async def on_request_start(
            _session: aiohttp.ClientSession, _context: SimpleNamespace, params: aiohttp.TraceRequestStartParams
        ) -> None:
            self.sent.append((params.method, params.url.path))

        config = aiohttp.TraceConfig()
        config.on_request_start.append(on_request_start)
        return config


def request_kind(method: str, path: str) -> str:
    if "/members/" in path and "/roles/" in path:
        return {"PUT": "add_role", "DELETE": "remove_role"}.get(method, "other")
    if method == "PATCH" and "/members/" in path:
        return "edit"
    return "other"


def readable(method: str, path: str, guild: discord.Guild, member_id: int) -> str:
    # The guild goes in last because the @everyone role shares its id.
    names = {str(role.id): role.name for role in guild.roles} | {str(guild.id): "{guild}", str(member_id): "{member}"}
    segments = [names.get(segment, segment) for segment in path.split("/")]
    return f"{method} /{'/'.join(segments[segments.index('guilds') :])}"


def report(name: str, outcome: Outcome, sent: list[str], kinds: Counter[str]) -> bool:
    print(f"scenario      {name}")
    print(f"rsc code      {roles.__file__}")
    print(f"start roles   {', '.join(sorted(outcome.start_roles)) or '(none)'}")
    print(f"start nick    {outcome.start_nick}")
    print(f"final roles   {', '.join(sorted(outcome.final_roles)) or '(none)'}")
    print(f"final nick    {outcome.final_nick}")
    print(f"requests      {len(sent)}")
    for line in sent:
        print(f"  {line}")
    print(f"wall_s        {outcome.wall_s:.3f}")
    print(f"error         {outcome.error or 'none'}")

    counted = True
    if outcome.summary_requests is None:
        print("summary       none. This checkout has no role writer, or the scenario runs no sync.")
    else:
        counted = outcome.summary_requests == dict(kinds)
        print(f"summary       {outcome.summary}")
        print(f"summary requests equal the lab's count   {'yes' if counted else 'no'}")
    print(f"final state matches the scenario         {'yes' if outcome.matches else 'no'}")
    return counted and outcome.matches


async def run(name: str, repeat: int, token: str, guild_id: int, member_id: int) -> bool:
    requests = Requests()
    client = discord.Client(intents=discord.Intents(guilds=True), http_trace=requests.trace())
    passed = True
    walls: list[float] = []
    request_lists: list[list[str]] = []
    async with client:
        await client.login(token)
        guild = await client.fetch_guild(guild_id, with_counts=False)

        def fetch_member() -> Awaitable[discord.Member]:
            return guild.fetch_member(member_id)

        for _ in range(repeat):
            lab = await prepare(guild, fetch_member, SCENARIOS[name])
            mark = len(requests.sent)
            outcome = await sync(guild, fetch_member, SCENARIOS[name], lab)
            writes = [(method, path) for method, path in requests.sent[mark:] if method != "GET"]
            sent = [readable(method, path, guild, member_id) for method, path in writes]
            kinds = Counter(request_kind(method, path) for method, path in writes)
            passed = report(name, outcome, sent, kinds) and passed
            walls.append(outcome.wall_s)
            request_lists.append(sent)
            print()

    if repeat > 1:
        identical = all(sent == request_lists[0] for sent in request_lists)
        print(f"runs          {repeat}")
        print(f"wall_s        median {statistics.median(walls):.3f}, min {min(walls):.3f}, max {max(walls):.3f}")
        print(f"request lists identical across runs      {'yes' if identical else 'no'}")
        passed = passed and identical
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("--repeat", type=int, default=1, help="Run the scenario this many times and report the median and spread.")
    args = parser.parse_args()

    try:
        refused = refusal(os.environ, redbot_running())
    except LabError as exc:
        refused = str(exc)
    if refused:
        print(f"The lab did not run. {refused}", file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("discord").setLevel(logging.WARNING)
    try:
        passed = asyncio.run(
            run(
                args.scenario,
                max(args.repeat, 1),
                os.environ["RSC_LAB_BOT_TOKEN"],
                int(os.environ["RSC_LAB_GUILD_ID"]),
                int(os.environ["RSC_LAB_MEMBER_ID"]),
            )
        )
    except (LabError, discord.HTTPException) as exc:
        print(f"The lab stopped. {exc}", file=sys.stderr)
        return 2
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
