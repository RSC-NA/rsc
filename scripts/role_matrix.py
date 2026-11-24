#!/usr/bin/env python3
"""Run every role function against fake members and report what each member ends up with.

    uv run python scripts/role_matrix.py [--agm] [--sub-status N] [--random N] [--json out.json]
    uv run python scripts/role_matrix.py --compare before.json after.json
    uv run python scripts/role_matrix.py --bench 1540 [--runs R] [--json out.json]

Each column is one role function call: every league status, a rostered captain,
a Draft Eligible row with no tier, a Free Agent and a Draft Eligible sync with
the Dev League flag, a member with no league player row, the same with a welcome
role, a non-playing GM, a sign, a cut, a cut of the franchise's GM, and a
captain gained or lost. Each column runs for five members:

    all     holds every role in ROLE_NAMES, nickname "OLD | Player"
    none    holds no role, nickname "Player"
    owner   holds no role and owns the server, so Discord refuses a nickname
    higher  holds a role above the bot's top role, so Discord refuses a nickname
    nonick  holds no role, and the bot lacks Manage Nicknames

The fake member applies each write the way Discord would, whichever way the
code sends it, and counts one request per role added or removed and one per
member edit. A case is run twice, and the second run's request count is
reported as the repeat. `--agm` runs every case for a member the API lists as
an AGM of franchise Beta. `--sub-status` sets the sub status on every league
player row: 0 not subbing, 1 subbing out, 2 subbing in. `--random N` adds N
members who each start with a random half of the roles and one of four
nicknames. The same N gives the same members on every run.

The table prints R or K for a role the `all` member lost or kept, then A or .
for a role the `none` member gained or did not.

The code under test is the first `rsc` package on the path, so another checkout
runs without editing this file:

    git archive <ref> rsc | tar -x -C /tmp/base
    PYTHONPATH=/tmp/base uv run python scripts/role_matrix.py --json base.json

`--compare` prints final state differences and request count differences
separately, and exits 1 when any member's final roles, nickname or error differ.

`--bench N` times N status syncs that change nothing instead of printing the
matrix. It settles N members with one sync each, then times a second sync of
all of them, `--runs` times over, and prints the median and spread of the CPU
seconds with the requests sent and errors raised in the timed runs.

The fake's refusals are a model of Discord's rules, not a recording of them.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import statistics
import sys
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.utils import MISSING
from rscapi.models.franchise_gm import FranchiseGM
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.league_player_member import LeaguePlayerMember
from rscapi.models.league_player_status_enum import LeaguePlayerStatusEnum
from rscapi.models.player_franchise import PlayerFranchise
from rscapi.models.player_team import PlayerTeam
from rscapi.models.player_transaction_updates import PlayerTransactionUpdates
from rscapi.models.sub_status_enum import SubStatusEnum
from rscapi.models.team_player import TeamPlayer
from rscapi.models.tier import Tier
from rscapi.models.transaction_franchise import TransactionFranchise
from rscapi.models.transaction_response import TransactionResponse
from rscapi.models.transaction_team import TransactionTeam

sys.path.append(str(Path(__file__).resolve().parent.parent))

from rsc.enums import Status
from rsc.transactions import roles

ROLE_NAMES = [
    "League",
    "Spectator",
    "Former Player",
    "Free Agent",
    "PermFA",
    "PermFA in Waiting",
    "Draft Eligible",
    "IR",
    "Captain",
    "Subbed Out",
    "Assistant GM",
    "General Manager",
    "Dev League Interest",
    "Premier",
    "PremierFA",
    "Elite",
    "EliteFA",
    "LegacyFA",
    "Alpha (GmA)",
    "Beta (GmB)",
    "Server Booster",
    "Muted",
]
EVERYONE = "@everyone"
ADMIN_ROLE = "Admin"
BOT_ROLE = "RSC Bot"
GUILD_ID = 1
MEMBER_ID = 42
OTHER_GM_ID = 7

TIERS = [Tier(name="Premier", position=1), Tier(name="Elite", position=2)]
ALPHA = FranchiseList(name="Alpha", prefix="ALP", gm=FranchiseGM(rsc_name="GmA", discord_id=MEMBER_ID), agms=[])
BETA = FranchiseList(
    name="Beta",
    prefix="BET",
    gm=FranchiseGM(rsc_name="GmB", discord_id=8),
    agms=[FranchiseGM(rsc_name="Player", discord_id=MEMBER_ID)],
)


@dataclass(frozen=True)
class Variant:
    held: tuple[str, ...]
    nick: str
    owner: bool = False
    manage_nicknames: bool = True


VARIANTS = {
    "all": Variant(tuple(ROLE_NAMES), "OLD | Player"),
    "none": Variant((), "Player"),
    "owner": Variant((), "Player", owner=True),
    "higher": Variant((ADMIN_ROLE,), "Player"),
    "nonick": Variant((), "Player", manage_nicknames=False),
}
RANDOM_NICKS = ("Player", "OLD | Player", "FA | Player", "BET | Player")


def coin(*key: object) -> int:
    return hashlib.sha256(repr(key).encode()).digest()[0]


def random_variants(count: int) -> dict[str, Variant]:
    return {
        f"r{number:03}": Variant(
            tuple(name for name in ROLE_NAMES if coin(number, name) % 2), RANDOM_NICKS[coin(number) % len(RANDOM_NICKS)]
        )
        for number in range(count)
    }


@dataclass(frozen=True)
class Setup:
    agm_franchise: FranchiseList | None
    sub_status: int


def make_role(name: str, position: int) -> MagicMock:
    role = MagicMock(spec=discord.Role)
    role.name = name
    role.id = GUILD_ID if name == EVERYONE else position + 100
    role.position = position
    role.__lt__ = lambda self, other: self.position < other.position
    role.__le__ = lambda self, other: self.position <= other.position
    role.__gt__ = lambda self, other: self.position > other.position
    role.__ge__ = lambda self, other: self.position >= other.position
    return role


def make_guild(variant: Variant) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.name = "matrix"
    guild.id = GUILD_ID
    guild.roles = [make_role(name, position) for position, name in enumerate([EVERYONE, *ROLE_NAMES, BOT_ROLE, ADMIN_ROLE])]
    guild.default_role = guild.roles[0]
    guild.owner_id = MEMBER_ID if variant.owner else OTHER_GM_ID
    guild.me = MagicMock(spec=discord.Member)
    guild.me.top_role = next(role for role in guild.roles if role.name == BOT_ROLE)
    return guild


def make_member(guild: MagicMock, variant: Variant) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = MEMBER_ID
    member.guild = guild
    member.display_name = variant.nick
    member.mention = f"<@{MEMBER_ID}>"
    member.requests = 0
    held = {role for role in guild.roles if role.name in variant.held}
    # Discord lists a member's roles lowest first, with @everyone at the bottom.
    type(member).roles = property(lambda self: sorted([guild.default_role, *held], key=lambda role: role.position))
    type(member).top_role = property(lambda self: self.roles[-1])

    def refuse() -> None:
        raise discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "Missing Permissions")

    def change_role(role: MagicMock) -> None:
        member.requests += 1
        if role >= guild.me.top_role:
            refuse()

    async def remove_roles(*removed: MagicMock, reason: str | None = None) -> None:
        for role in removed:
            change_role(role)
            held.discard(role)

    async def add_roles(*added: MagicMock, reason: str | None = None) -> None:
        for role in added:
            change_role(role)
            held.add(role)

    async def edit(*, nick: str = MISSING, roles: Iterable[MagicMock] = MISSING, reason: str | None = None) -> None:
        member.requests += 1
        nickname_refused = guild.owner_id == member.id or member.top_role >= guild.me.top_role or not variant.manage_nicknames
        if nick is not MISSING and nickname_refused:
            refuse()
        if roles is not MISSING:
            listed = set(roles)
            if guild.default_role in listed:
                raise ValueError("The request listed @everyone as a role.")
            if any(role >= guild.me.top_role for role in listed ^ held):
                refuse()
            held.clear()
            held.update(listed)
        if nick is not MISSING:
            member.display_name = nick

    member.remove_roles = AsyncMock(side_effect=remove_roles)
    member.add_roles = AsyncMock(side_effect=add_roles)
    member.edit = AsyncMock(side_effect=edit)
    guild.get_member = MagicMock(side_effect={MEMBER_ID: member}.get)
    return member


def league_player(status: Status, *, sub_status: int = 0, captain: bool = False, tier: Tier | None = TIERS[0]) -> LeaguePlayer:
    franchise = PlayerFranchise(name="Alpha", prefix="ALP", gm=FranchiseGM(rsc_name="GmA", discord_id=OTHER_GM_ID))
    return LeaguePlayer.model_construct(
        status=LeaguePlayerStatusEnum(status.value),
        captain=captain,
        tier=tier,
        team=PlayerTeam(name="Team", franchise=franchise),
        player=LeaguePlayerMember(name="Player", discord_id=MEMBER_ID),
        sub_status=SubStatusEnum(sub_status),
    )


Run = Callable[[MagicMock, MagicMock, Setup], Awaitable[None]]


def status_sync(
    status: Status | None, *, captain: bool = False, tier: Tier | None = TIERS[0], devleague: bool = False, welcome: bool = False
) -> Run:
    async def run(guild: MagicMock, member: MagicMock, setup: Setup) -> None:
        row = league_player(status, sub_status=setup.sub_status, captain=captain, tier=tier) if status else None
        await roles.update_league_player_discord(
            guild=guild,
            player=member,
            league_player=row,
            tiers=TIERS,
            franchise=ALPHA,
            default_roles=[role for role in guild.roles if role.name == "Spectator"] if welcome else None,
            devleague=devleague,
            agm_franchise=setup.agm_franchise,
        )

    return run


async def nonplaying_gm(guild: MagicMock, member: MagicMock, _setup: Setup) -> None:
    await roles.update_nonplaying_gm_discord(guild=guild, player=member, franchise=ALPHA, tiers=TIERS)


async def sign(guild: MagicMock, member: MagicMock, setup: Setup) -> None:
    ptu = PlayerTransactionUpdates.model_construct(
        player=league_player(Status.ROSTERED, sub_status=setup.sub_status),
        new_team=TransactionTeam.model_construct(name="Team", tier="Premier"),
        old_team=None,
    )
    await roles.update_signed_player_discord(guild=guild, player=member, ptu=ptu, tiers=TIERS)


def cut(gm_id: int) -> Run:
    async def run(guild: MagicMock, member: MagicMock, setup: Setup) -> None:
        ptu = PlayerTransactionUpdates.model_construct(
            player=league_player(Status.FREE_AGENT, sub_status=setup.sub_status),
            old_team=TransactionTeam.model_construct(name="Team", tier="Premier"),
            new_team=None,
        )
        franchise = TransactionFranchise.model_construct(name="Alpha", prefix="ALP", gm=FranchiseGM(rsc_name="GmA", discord_id=gm_id))
        response = TransactionResponse.model_construct(first_franchise=franchise)
        await roles.update_cut_player_discord(guild=guild, player=member, response=response, ptu=ptu)

    return run


def captain(flag: bool) -> Run:
    async def run(guild: MagicMock, _member: MagicMock, _setup: Setup) -> None:
        await roles.update_team_captain_discord(
            guild=guild, players=[TeamPlayer.model_construct(name="Player", discord_id=MEMBER_ID, captain=flag)]
        )

    return run


STATUS_SYNCS: dict[str, Run] = {
    **{status.value: status_sync(status) for status in Status},
    "RO+c": status_sync(Status.ROSTERED, captain=True),
    "DE-t": status_sync(Status.DRAFT_ELIGIBLE, tier=None),
    "FA+dv": status_sync(Status.FREE_AGENT, devleague=True),
    "DE+dv": status_sync(Status.DRAFT_ELIGIBLE, devleague=True),
    "no-LP": status_sync(None),
    "no+w": status_sync(None, welcome=True),
    "npGM": nonplaying_gm,
}
CASES: dict[str, Run] = {
    **STATUS_SYNCS,
    "sign": sign,
    "cut": cut(OTHER_GM_ID),
    "cutGM": cut(MEMBER_ID),
    "capt+": captain(True),
    "capt-": captain(False),
}


async def requests_sent(run: Run, guild: MagicMock, member: MagicMock, setup: Setup) -> tuple[int, str | None]:
    before = member.requests
    error = None
    try:
        await run(guild, member, setup)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return member.requests - before, error


async def measure(agm: bool, sub_status: int, random_count: int) -> dict:
    setup = Setup(BETA if agm else None, sub_status)
    variants = VARIANTS | random_variants(random_count)
    results: dict[str, dict[str, dict]] = {}
    for label, run in CASES.items():
        results[label] = {}
        for name, variant in variants.items():
            guild = make_guild(variant)
            member = make_member(guild, variant)
            requests, error = await requests_sent(run, guild, member, setup)
            final_roles = sorted(role.name for role in member.roles[1:])
            final_nick = member.display_name
            repeat_requests, _repeat_error = await requests_sent(run, guild, member, setup)
            results[label][name] = {
                "roles": final_roles,
                "nick": final_nick,
                "error": error,
                "requests": requests,
                "repeat_requests": repeat_requests,
            }
    return {
        "roles_py": roles.__file__,
        "agm": agm,
        "sub_status": sub_status,
        "variants": {name: {"held": list(variant.held), "nick": variant.nick} for name, variant in variants.items()},
        "results": results,
    }


async def bench(count: int, runs: int, agm: bool, sub_status: int) -> dict:
    setup = Setup(BETA if agm else None, sub_status)
    guilds = {name: make_guild(VARIANTS[name]) for name in ("all", "none")}
    labels = list(STATUS_SYNCS)
    members = []
    for number in range(count):
        run = STATUS_SYNCS[labels[number % len(labels)]]
        name = "all" if number // len(labels) % 2 else "none"
        member = make_member(guilds[name], VARIANTS[name])
        await requests_sent(run, guilds[name], member, setup)
        members.append((run, guilds[name], member))
    # Each guild served one member id to many members. With no cached member the writer reads the member's own roles.
    for guild in guilds.values():
        guild.get_member = MagicMock(return_value=None)

    cpu_s, requests, errors = [], 0, 0
    for _ in range(runs):
        started = time.process_time()
        for run, guild, member in members:
            sent, error = await requests_sent(run, guild, member, setup)
            requests += sent
            errors += error is not None
        cpu_s.append(time.process_time() - started)
    return {
        "roles_py": roles.__file__,
        "agm": agm,
        "sub_status": sub_status,
        "syncs": count,
        "cpu_s": cpu_s,
        "requests": requests,
        "errors": errors,
    }


def print_bench(result: dict) -> None:
    cpu_s = result["cpu_s"]
    print(f"rsc code      {result['roles_py']}")
    print(f"member        {'an AGM of Beta' if result['agm'] else 'not an AGM'}")
    print(f"sub status    {result['sub_status']}")
    print(f"syncs         {result['syncs']} per run, each of a member an earlier sync already settled")
    print(f"CPU seconds   median {statistics.median(cpu_s):.3f}, lowest {min(cpu_s):.3f}, highest {max(cpu_s):.3f}, over {len(cpu_s)} runs")
    print(f"requests      {result['requests']} sent in the timed runs")
    print(f"errors        {result['errors']} raised in the timed runs")


def print_matrix(matrix: dict) -> None:
    results = matrix["results"]
    labels = list(results)
    width = 6
    print(f"rsc code      {matrix['roles_py']}")
    print(f"member        {'an AGM of Beta' if matrix['agm'] else 'not an AGM'}")
    print(f"sub status    {matrix['sub_status']}")
    print()
    print(f"{'role':22}" + "".join(f"{label:>{width}}" for label in labels))
    for role in ROLE_NAMES:
        cells = [
            ("K" if role in results[label]["all"]["roles"] else "R") + ("A" if role in results[label]["none"]["roles"] else ".")
            for label in labels
        ]
        print(f"{role:22}" + "".join(f"{cell:>{width}}" for cell in cells))
    for key, title in (("requests", "requests"), ("repeat_requests", "repeat")):
        print()
        for name in VARIANTS:
            print(f"{f'{title}, {name}':22}" + "".join(f"{results[label][name][key]:>{width}}" for label in labels))
    print()
    for label in labels:
        nicks = "  ".join(f"{name} {results[label][name]['nick']!r}" for name in VARIANTS)
        print(f"{label:6} {nicks}")
    for label in labels:
        for name in VARIANTS:
            if results[label][name]["error"]:
                print(f"{label:6} {name:7} raised {results[label][name]['error']}")


def state_differences(before: dict, after: dict) -> list[str]:
    for key in ("agm", "sub_status", "variants"):
        if before[key] != after[key]:
            return [f"The two files were not run the same way. They differ in {key}."]
    differences = []
    for label in sorted(before["results"].keys() | after["results"].keys()):
        for name in after["variants"]:
            old = before["results"].get(label, {}).get(name)
            new = after["results"].get(label, {}).get(name)
            if old is None or new is None:
                differences.append(f"{label}/{name} is in one file only")
                continue
            lost = sorted(set(old["roles"]) - set(new["roles"]))
            gained = sorted(set(new["roles"]) - set(old["roles"]))
            if lost or gained:
                differences.append(f"{label}/{name} roles: no longer held {lost}, newly held {gained}")
            if old["nick"] != new["nick"]:
                differences.append(f"{label}/{name} nickname: {old['nick']!r} became {new['nick']!r}")
            if old["error"] != new["error"]:
                differences.append(f"{label}/{name} error: {old['error']!r} became {new['error']!r}")
    return differences


def request_differences(before: dict, after: dict) -> list[str]:
    differences = []
    for label, variants in after["results"].items():
        for name, new in variants.items():
            old = before["results"].get(label, {}).get(name)
            if old and (old["requests"], old["repeat_requests"]) != (new["requests"], new["repeat_requests"]):
                differences.append(
                    f"{label}/{name} requests {old['requests']} became {new['requests']}, "
                    f"repeat {old['repeat_requests']} became {new['repeat_requests']}"
                )
    return differences


def print_comparison(before: dict, after: dict) -> bool:
    print(f"before        {before['roles_py']}")
    print(f"after         {after['roles_py']}")
    print(f"member        {'an AGM of Beta' if after['agm'] else 'not an AGM'}")
    print(f"sub status    {after['sub_status']}")
    differences = state_differences(before, after)
    cases = sum(len(variants) for variants in after["results"].values())
    print()
    print(f"Final state differences: {len(differences) or 'none'}, across {cases} cases")
    for difference in differences:
        print(f"  {difference}")
    counts = request_differences(before, after)
    print()
    print(f"Request count differences: {len(counts) or 'none'}, across {cases} cases")
    for count in counts:
        print(f"  {count}")

    labels = [label for label in before["results"] if label in after["results"]]
    width = 7
    for key, title in (("requests", "requests"), ("repeat_requests", "repeat")):
        print()
        print(f"{f'{title}, before>after':22}" + "".join(f"{label:>{width}}" for label in labels))
        for name in VARIANTS:
            cells = [f"{before['results'][label][name][key]}>{after['results'][label][name][key]}" for label in labels]
            print(f"{name:22}" + "".join(f"{cell:>{width}}" for cell in cells))
    for name in VARIANTS:
        old = [before["results"][label][name]["requests"] for label in labels]
        new = [after["results"][label][name]["requests"] for label in labels]
        print(f"{name:7} requests per member: before {min(old)} to {max(old)}, after {min(new)} to {max(new)}")
    return not differences


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agm", action="store_true", help="Run every case for a member the API lists as an AGM of franchise Beta.")
    parser.add_argument("--sub-status", type=int, choices=(0, 1, 2), default=0, help="The sub status on every league player row.")
    parser.add_argument("--random", type=int, default=0, metavar="N", help="Also run N members who start with random roles.")
    parser.add_argument("--json", type=Path, metavar="FILE", help="Also write the whole result to FILE.")
    parser.add_argument("--compare", type=Path, nargs=2, metavar=("BEFORE", "AFTER"), help="Compare two files written by --json.")
    parser.add_argument("--bench", type=int, metavar="N", help="Time N status syncs that change nothing, instead of the matrix.")
    parser.add_argument("--runs", type=int, default=5, metavar="R", help="How many times --bench times its N syncs.")
    args = parser.parse_args()

    if args.compare:
        before, after = (json.loads(path.read_text()) for path in args.compare)
        return 0 if print_comparison(before, after) else 1

    logging.disable(logging.CRITICAL)
    if args.bench:
        matrix = asyncio.run(bench(args.bench, args.runs, args.agm, args.sub_status))
        print_bench(matrix)
    else:
        matrix = asyncio.run(measure(args.agm, args.sub_status, args.random))
        print_matrix(matrix)
    if args.json:
        args.json.write_text(json.dumps(matrix, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
