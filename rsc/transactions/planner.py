from collections.abc import Collection
from dataclasses import dataclass, replace
from enum import Enum, auto

from rsc import const
from rsc.enums import Status
from rsc.utils.utils import FRANCHISE_ROLE_REGEX, rsc_name_from_display_name

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


class NoRow(Enum):
    NON_PLAYING = auto()
    NON_PLAYING_GM = auto()


class SeatSource(Enum):
    ROSTER = auto()
    GM = auto()
    AGM = auto()


class TierRoles(Enum):
    NONE = auto()
    TIER = auto()
    TIER_AND_FA = auto()


@dataclass(frozen=True)
class Rule:
    gives: frozenset[str] = frozenset()
    untouched: frozenset[str] = frozenset()
    prefix: str | None = None
    seat: SeatSource = SeatSource.AGM
    tier: TierRoles = TierRoles.NONE
    takes_every_fa_role: bool = False
    dev_league: bool = False
    in_league: bool = True


ROSTERED = Rule(
    gives=frozenset({const.LEAGUE_ROLE}),
    seat=SeatSource.ROSTER,
    tier=TierRoles.TIER,
    takes_every_fa_role=True,
)
INACTIVE_RESERVE = replace(ROSTERED, gives=frozenset({const.LEAGUE_ROLE, const.IR_ROLE}))
UNSIGNED_GM = Rule(
    gives=frozenset({const.LEAGUE_ROLE}),
    untouched=frozenset({const.AGM_ROLE}),
    seat=SeatSource.GM,
    tier=TierRoles.TIER,
    takes_every_fa_role=True,
)
NON_PLAYING_GM = Rule(
    gives=frozenset({const.LEAGUE_ROLE}),
    untouched=frozenset({const.SUBBED_OUT_ROLE}),
    seat=SeatSource.GM,
    takes_every_fa_role=True,
)
FREE_AGENT = Rule(
    gives=frozenset({const.LEAGUE_ROLE, const.FREE_AGENT_ROLE}),
    prefix="FA",
    tier=TierRoles.TIER_AND_FA,
    dev_league=True,
)
PERM_FA = Rule(
    gives=frozenset({const.LEAGUE_ROLE, const.PERM_FA_ROLE}),
    prefix="PFA",
    tier=TierRoles.TIER_AND_FA,
    dev_league=True,
)
WAIVERS = Rule(
    gives=frozenset({const.LEAGUE_ROLE}),
    prefix="FA",
    tier=TierRoles.TIER_AND_FA,
    dev_league=True,
)
DRAFT_ELIGIBLE = Rule(
    gives=frozenset({const.LEAGUE_ROLE, const.DRAFT_ELIGIBLE}),
    prefix="DE",
    tier=TierRoles.TIER,
    dev_league=True,
)
PERMFA_WAITING = Rule(
    gives=frozenset({const.LEAGUE_ROLE, const.PERM_FA_WAITING_ROLE}),
    prefix="PFW",
)
NON_PLAYING = Rule(untouched=frozenset({const.SPECTATOR_ROLE, const.FORMER_PLAYER_ROLE}), in_league=False)

RULES: dict[Status | NoRow, Rule] = {
    Status.ROSTERED: ROSTERED,
    Status.RENEWED: ROSTERED,
    Status.IR: INACTIVE_RESERVE,
    Status.AGMIR: INACTIVE_RESERVE,
    Status.UNSIGNED_GM: UNSIGNED_GM,
    NoRow.NON_PLAYING_GM: NON_PLAYING_GM,
    Status.FREE_AGENT: FREE_AGENT,
    Status.PERM_FA: PERM_FA,
    Status.WAIVERS: WAIVERS,
    Status.WAIVER_CLAIM: WAIVERS,
    Status.WAIVER_RELEASE: WAIVERS,
    Status.DRAFT_ELIGIBLE: DRAFT_ELIGIBLE,
    Status.PERMFA_W: PERMFA_WAITING,
    Status.DROPPED: NON_PLAYING,
    Status.FORMER: NON_PLAYING,
    Status.BANNED: NON_PLAYING,
    NoRow.NON_PLAYING: NON_PLAYING,
}


@dataclass(frozen=True)
class Seat:
    role: str
    prefix: str | None
    name: str | None = None


@dataclass(frozen=True)
class SeatWithoutRole:
    prefix: str | None
    name: str | None = None


@dataclass(frozen=True)
class Row:
    name: str
    tier: str | None = None
    captain: bool = False
    subbed_out: bool = False
    team: Seat | None = None


@dataclass(frozen=True)
class MemberState:
    roles: frozenset[str]
    nick: str


@dataclass(frozen=True)
class Rename:
    name: str
    prefix: str | None


@dataclass(frozen=True)
class StripPrefix:
    pass


@dataclass(frozen=True)
class Plan:
    final_roles: frozenset[str]
    nickname: Rename | StripPrefix


def plan_member(
    standing: Status | NoRow,
    member: MemberState,
    *,
    row: Row | None = None,
    agm: Seat | SeatWithoutRole | None = None,
    gm: Seat | None = None,
    tiers: Collection[str] = (),
    welcome_roles: Collection[str] = (),
    devleague: bool = False,
) -> Plan:
    rule = RULES[standing]
    if not rule.in_league:
        row = None
    seat = _seat(rule, row, agm, gm)

    roles = (set(member.roles) - (STATUS_ROLES - rule.untouched)) | rule.gives

    if agm:
        roles |= {const.AGM_ROLE, const.LEAGUE_ROLE}
    if row and row.captain and rule.seat is SeatSource.ROSTER:
        roles.add(const.CAPTAIN_ROLE)
    if row and row.subbed_out:
        roles.add(const.SUBBED_OUT_ROLE)
    if devleague and rule.dev_league:
        roles.add(const.DEV_LEAGUE_ROLE)

    if not rule.in_league:
        roles |= set(welcome_roles) - member.roles
        if _tag_is_from_playing(member, seat):
            roles.add(const.FORMER_PLAYER_ROLE)

    tier_roles = _tier_roles(rule, row)
    kept = {name.lower() for name in tier_roles}
    tier_names = {tier.lower() for tier in tiers}
    roles -= {name for name in member.roles if _is_tier_role(rule, name, tier_names) and name.lower() not in kept}
    roles |= tier_roles

    if not isinstance(seat, SeatWithoutRole):
        roles -= {name for name in member.roles if FRANCHISE_ROLE_REGEX.match(name)}
    if isinstance(seat, Seat):
        roles.add(seat.role)

    return Plan(frozenset(roles), _nickname(rule, member, row, seat))


def _seat(rule: Rule, row: Row | None, agm: Seat | SeatWithoutRole | None, gm: Seat | None) -> Seat | SeatWithoutRole | None:
    match rule.seat:
        case SeatSource.ROSTER:
            if row is None or row.team is None:
                raise ValueError("A rostered status needs the row and its team.")
            return row.team
        case SeatSource.GM:
            if gm is None:
                raise ValueError("A GM status needs the GM's franchise.")
            return gm
        case SeatSource.AGM:
            return agm


def _tier_roles(rule: Rule, row: Row | None) -> set[str]:
    if row is None or row.tier is None or rule.tier is TierRoles.NONE:
        return set()
    if rule.tier is TierRoles.TIER_AND_FA:
        return {row.tier, f"{row.tier}FA"}
    return {row.tier}


def _is_tier_role(rule: Rule, name: str, tier_names: set[str]) -> bool:
    if not tier_names:
        return False
    if rule.takes_every_fa_role and name.endswith("FA"):
        return True
    return name.removesuffix("FA").lower() in tier_names


def _nickname(rule: Rule, member: MemberState, row: Row | None, seat: Seat | SeatWithoutRole | None) -> Rename | StripPrefix:
    if row:
        return Rename(row.name, seat.prefix if seat else rule.prefix)
    if seat:
        return Rename(seat.name or rsc_name_from_display_name(member.nick), seat.prefix)
    return StripPrefix()


def _tag_is_from_playing(member: MemberState, seat: Seat | SeatWithoutRole | None) -> bool:
    tag, separator, _name = member.nick.partition(" | ")
    return seat is None and bool(separator and tag.strip())
