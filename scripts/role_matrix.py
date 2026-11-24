#!/usr/bin/env python3
"""Run every role function against fake members and report what each member ends up with.

    uv run python scripts/role_matrix.py [--agm] [--json out.json]
    uv run python scripts/role_matrix.py --compare before.json after.json

Each column is one role function call: every league status, a member with no
league player row, a non-playing GM, a sign, a cut, a cut of the franchise's GM,
and a captain gained or lost. Each column runs for five members:

    all     holds every role in ROLE_NAMES, nickname "OLD | Player"
    none    holds no role, nickname "Player"
    owner   holds no role and owns the server, so Discord refuses a nickname
    higher  holds a role above the bot's top role, so Discord refuses a nickname
    nonick  holds no role, and the bot lacks Manage Nicknames

The fake member applies each write the way Discord would, whichever way the
code sends it, and counts one request per role added or removed and one per
member edit. A case is run twice, and the second run's request count is
reported as the repeat. `--agm` runs every case for a member the API lists as
an AGM of franchise Beta.

The table prints R or K for a role the `all` member lost or kept, then A or .
for a role the `none` member gained or did not.

The code under test is the first `rsc` package on the path, so another checkout
runs without editing this file:

    git archive <ref> rsc | tar -x -C /tmp/base
    PYTHONPATH=/tmp/base uv run python scripts/role_matrix.py --json base.json

`--compare` prints final state differences and request counts separately, and
exits 1 when any member's final roles, nickname or error differ.

The fake's refusals are a model of Discord's rules, not a recording of them.
"""

import argparse
import asyncio
import json
import logging
import sys
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
from rscapi.models.team_player import TeamPlayer
from rscapi.models.tier import Tier
from rscapi.models.transaction_franchise import TransactionFranchise
from rscapi.models.transaction_response import TransactionResponse
from rscapi.models.transaction_team import TransactionTeam

# Appended, so a checkout named in PYTHONPATH is imported instead of this one.
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
    member.roles = [guild.default_role, *(role for role in guild.roles if role.name in variant.held)]
    member.requests = 0
    type(member).top_role = property(lambda self: max(self.roles, key=lambda role: role.position))

    def refuse() -> None:
        raise discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "Missing Permissions")

    def change_role(role: MagicMock) -> None:
        member.requests += 1
        if role >= guild.me.top_role:
            refuse()

    async def remove_roles(*removed: MagicMock, reason: str | None = None) -> None:
        for role in removed:
            change_role(role)
            member.roles = [held for held in member.roles if held is not role]

    async def add_roles(*added: MagicMock, reason: str | None = None) -> None:
        for role in added:
            change_role(role)
            if role not in member.roles:
                member.roles = [*member.roles, role]

    async def edit(*, nick: str = MISSING, roles: Iterable[MagicMock] = MISSING, reason: str | None = None) -> None:
        member.requests += 1
        nickname_refused = guild.owner_id == member.id or member.top_role >= guild.me.top_role or not variant.manage_nicknames
        if nick is not MISSING and nickname_refused:
            refuse()
        if roles is not MISSING:
            listed = list(roles)
            if guild.default_role in listed:
                raise ValueError("The request listed @everyone as a role.")
            held = member.roles[1:]
            if any(role >= guild.me.top_role for role in (*listed, *held) if (role in listed) != (role in held)):
                refuse()
            member.roles = [guild.default_role, *listed]
        if nick is not MISSING:
            member.display_name = nick

    member.remove_roles = AsyncMock(side_effect=remove_roles)
    member.add_roles = AsyncMock(side_effect=add_roles)
    member.edit = AsyncMock(side_effect=edit)
    guild.get_member = MagicMock(side_effect={MEMBER_ID: member}.get)
    return member


def league_player(status: Status) -> LeaguePlayer:
    franchise = PlayerFranchise(name="Alpha", prefix="ALP", gm=FranchiseGM(rsc_name="GmA", discord_id=OTHER_GM_ID))
    return LeaguePlayer.model_construct(
        status=LeaguePlayerStatusEnum(status.value),
        captain=False,
        tier=TIERS[0],
        team=PlayerTeam(name="Team", franchise=franchise),
        player=LeaguePlayerMember(name="Player", discord_id=MEMBER_ID),
    )


Run = Callable[[MagicMock, MagicMock, FranchiseList | None], Awaitable[None]]


def status_sync(status: Status | None) -> Run:
    async def run(guild: MagicMock, member: MagicMock, agm_franchise: FranchiseList | None) -> None:
        await roles.update_league_player_discord(
            guild=guild,
            player=member,
            league_player=league_player(status) if status else None,
            tiers=TIERS,
            franchise=ALPHA,
            agm_franchise=agm_franchise,
        )

    return run


async def nonplaying_gm(guild: MagicMock, member: MagicMock, _agm_franchise: FranchiseList | None) -> None:
    await roles.update_nonplaying_gm_discord(guild=guild, player=member, franchise=ALPHA, tiers=TIERS)


async def sign(guild: MagicMock, member: MagicMock, _agm_franchise: FranchiseList | None) -> None:
    ptu = PlayerTransactionUpdates.model_construct(
        player=league_player(Status.ROSTERED), new_team=TransactionTeam.model_construct(name="Team", tier="Premier"), old_team=None
    )
    await roles.update_signed_player_discord(guild=guild, player=member, ptu=ptu, tiers=TIERS)


def cut(gm_id: int) -> Run:
    async def run(guild: MagicMock, member: MagicMock, _agm_franchise: FranchiseList | None) -> None:
        ptu = PlayerTransactionUpdates.model_construct(
            player=league_player(Status.FREE_AGENT), old_team=TransactionTeam.model_construct(name="Team", tier="Premier"), new_team=None
        )
        franchise = TransactionFranchise.model_construct(name="Alpha", prefix="ALP", gm=FranchiseGM(rsc_name="GmA", discord_id=gm_id))
        response = TransactionResponse.model_construct(first_franchise=franchise)
        await roles.update_cut_player_discord(guild=guild, player=member, response=response, ptu=ptu)

    return run


def captain(flag: bool) -> Run:
    async def run(guild: MagicMock, _member: MagicMock, _agm_franchise: FranchiseList | None) -> None:
        await roles.update_team_captain_discord(
            guild=guild, players=[TeamPlayer.model_construct(name="Player", discord_id=MEMBER_ID, captain=flag)]
        )

    return run


CASES: dict[str, Run] = {
    **{status.value: status_sync(status) for status in Status},
    "no-LP": status_sync(None),
    "npGM": nonplaying_gm,
    "sign": sign,
    "cut": cut(OTHER_GM_ID),
    "cutGM": cut(MEMBER_ID),
    "capt+": captain(True),
    "capt-": captain(False),
}


async def requests_sent(run: Run, guild: MagicMock, member: MagicMock, agm_franchise: FranchiseList | None) -> tuple[int, str | None]:
    before = member.requests
    error = None
    try:
        await run(guild, member, agm_franchise)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return member.requests - before, error


async def measure(agm: bool) -> dict:
    agm_franchise = BETA if agm else None
    results: dict[str, dict[str, dict]] = {}
    for label, run in CASES.items():
        results[label] = {}
        for name, variant in VARIANTS.items():
            guild = make_guild(variant)
            member = make_member(guild, variant)
            requests, error = await requests_sent(run, guild, member, agm_franchise)
            final_roles = sorted(role.name for role in member.roles[1:])
            final_nick = member.display_name
            repeat_requests, _repeat_error = await requests_sent(run, guild, member, agm_franchise)
            results[label][name] = {
                "roles": final_roles,
                "nick": final_nick,
                "error": error,
                "requests": requests,
                "repeat_requests": repeat_requests,
            }
    return {"roles_py": roles.__file__, "agm": agm, "results": results}


def print_matrix(matrix: dict) -> None:
    results = matrix["results"]
    labels = list(results)
    width = 6
    print(f"rsc code      {matrix['roles_py']}")
    print(f"member        {'an AGM of Beta' if matrix['agm'] else 'not an AGM'}")
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
    if before["agm"] != after["agm"]:
        return ["One file is an --agm run and the other is not."]
    differences = []
    for label in sorted(before["results"].keys() | after["results"].keys()):
        for name in VARIANTS:
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


def print_comparison(before: dict, after: dict) -> bool:
    print(f"before        {before['roles_py']}")
    print(f"after         {after['roles_py']}")
    print(f"member        {'an AGM of Beta' if after['agm'] else 'not an AGM'}")
    differences = state_differences(before, after)
    cases = sum(len(variants) for variants in after["results"].values())
    print()
    print(f"Final state differences: {len(differences) or 'none'}, across {cases} cases")
    for difference in differences:
        print(f"  {difference}")

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
    parser.add_argument("--json", type=Path, metavar="FILE", help="Also write the whole result to FILE.")
    parser.add_argument("--compare", type=Path, nargs=2, metavar=("BEFORE", "AFTER"), help="Compare two files written by --json.")
    args = parser.parse_args()

    if args.compare:
        before, after = (json.loads(path.read_text()) for path in args.compare)
        return 0 if print_comparison(before, after) else 1

    logging.disable(logging.CRITICAL)
    matrix = asyncio.run(measure(args.agm))
    print_matrix(matrix)
    if args.json:
        args.json.write_text(json.dumps(matrix, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
