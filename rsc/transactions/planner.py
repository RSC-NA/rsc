"""The roles and nickname a member should have for their league status.

`RULES` maps every status to the roles it gives and the tag it writes.
`plan_member` applies one rule to one member and adds the rules that hold for
every status. It reads plain data and returns plain data, so it can be run
without Discord.
"""

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
    """Where a member with no league player row stands."""

    NON_PLAYING = auto()
    NON_PLAYING_GM = auto()


class SeatSource(Enum):
    """Whose franchise role and tag a status carries."""

    ROSTER = auto()
    GM = auto()
    AGM = auto()


class TierRoles(Enum):
    NONE = auto()
    TIER = auto()
    TIER_AND_FA = auto()


@dataclass(frozen=True)
class Rule:
    """What one status decides.

    A status gives the roles in `holds`, leaves the roles in `leaves` as it
    finds them, and takes every other role in `STATUS_ROLES`. `prefix` is the
    tag for a member with no franchise. A member out of the league has no tag.
    """

    holds: frozenset[str] = frozenset()
    leaves: frozenset[str] = frozenset()
    prefix: str | None = None
    seat: SeatSource = SeatSource.AGM
    tier: TierRoles = TierRoles.NONE
    dev_league: bool = False
    in_league: bool = True


ROSTERED = Rule(
    holds=frozenset({const.LEAGUE_ROLE}),
    leaves=frozenset({const.SUBBED_OUT_ROLE}),
    seat=SeatSource.ROSTER,
    tier=TierRoles.TIER,
)
INACTIVE_RESERVE = replace(ROSTERED, holds=frozenset({const.LEAGUE_ROLE, const.IR_ROLE}))
UNSIGNED_GM = Rule(
    holds=frozenset({const.LEAGUE_ROLE}),
    leaves=frozenset({const.AGM_ROLE, const.PERM_FA_WAITING_ROLE, const.SUBBED_OUT_ROLE}),
    seat=SeatSource.GM,
    tier=TierRoles.TIER,
)
NON_PLAYING_GM = Rule(
    holds=frozenset({const.LEAGUE_ROLE}),
    leaves=frozenset({const.IR_ROLE, const.PERM_FA_WAITING_ROLE, const.SUBBED_OUT_ROLE}),
    seat=SeatSource.GM,
)
FREE_AGENT = Rule(
    holds=frozenset({const.LEAGUE_ROLE, const.FREE_AGENT_ROLE}),
    leaves=frozenset({const.SUBBED_OUT_ROLE, const.AGM_ROLE}),
    prefix="FA",
    tier=TierRoles.TIER_AND_FA,
    dev_league=True,
)
PERM_FA = Rule(
    holds=frozenset({const.LEAGUE_ROLE, const.PERM_FA_ROLE}),
    leaves=frozenset({const.SUBBED_OUT_ROLE, const.AGM_ROLE}),
    prefix="PFA",
    tier=TierRoles.TIER_AND_FA,
    dev_league=True,
)
WAIVERS = Rule(
    holds=frozenset({const.LEAGUE_ROLE}),
    leaves=frozenset({const.SUBBED_OUT_ROLE, const.AGM_ROLE}),
    prefix="FA",
    tier=TierRoles.TIER_AND_FA,
    dev_league=True,
)
DRAFT_ELIGIBLE = Rule(
    holds=frozenset({const.LEAGUE_ROLE, const.DRAFT_ELIGIBLE}),
    leaves=frozenset({const.SUBBED_OUT_ROLE, const.AGM_ROLE}),
    prefix="DE",
    tier=TierRoles.TIER,
    dev_league=True,
)
PERMFA_WAITING = Rule(
    holds=frozenset({const.LEAGUE_ROLE, const.PERM_FA_WAITING_ROLE}),
    leaves=frozenset({const.SUBBED_OUT_ROLE, const.AGM_ROLE}),
    prefix="PFW",
)
NON_PLAYING = Rule(leaves=frozenset({const.SPECTATOR_ROLE, const.FORMER_PLAYER_ROLE}), in_league=False)

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
    """A member's place on a franchise, as a player, its GM or an AGM.

    `role` is `None` when the guild has no role for the franchise. `name` is
    the RSC name the franchise's staff list has for the member.
    """

    role: str | None
    prefix: str | None
    name: str | None = None


@dataclass(frozen=True)
class Row:
    """What a sync reads from a league player row."""

    name: str
    tier: str | None = None
    captain: bool = False
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
    """Every role the member should hold, and what to do with the nickname.

    A role the status rules do not cover is in `roles` when the member holds it.
    """

    roles: frozenset[str]
    nickname: Rename | StripPrefix


def plan_member(
    standing: Status | NoRow,
    member: MemberState,
    *,
    row: Row | None = None,
    agm: Seat | None = None,
    gm: Seat | None = None,
    tiers: Collection[str] = (),
    welcome: Collection[str] = (),
    devleague: bool = False,
) -> Plan:
    """Decide a member's roles and nickname.

    `agm` is the member's seat as an AGM and `gm` their seat as a GM. `tiers`
    names every tier, `welcome` the roles a member out of the league is given,
    and `devleague` asks for the Dev League role.
    """
    rule = RULES[standing]
    if not rule.in_league:
        row = None
    seat = _seat(rule, row, agm, gm)

    roles = (set(member.roles) - (STATUS_ROLES - rule.leaves)) | rule.holds

    # Issue 50. The rostered sync has always taken the IR role from a member who already held it.
    if rule is INACTIVE_RESERVE and const.IR_ROLE in member.roles:
        roles.discard(const.IR_ROLE)

    if agm:
        roles |= {const.AGM_ROLE, const.LEAGUE_ROLE}
    if row and row.captain and rule.seat is SeatSource.ROSTER:
        roles.add(const.CAPTAIN_ROLE)
    if devleague and rule.dev_league:
        roles.add(const.DEV_LEAGUE_ROLE)

    if not rule.in_league:
        roles |= set(welcome) - member.roles
        # An AGM's tag says staff. Anyone else's says they used to play.
        if seat is None and _has_prefix(member.nick):
            roles.add(const.FORMER_PLAYER_ROLE)

    tier_roles = _tier_roles(rule, row)
    kept = {name.lower() for name in tier_roles}
    tier_names = {tier.lower() for tier in tiers}
    roles -= {name for name in member.roles if _is_tier_role(rule, name, tier_names) and name.lower() not in kept}
    roles |= tier_roles

    # A seat with no role in the guild leaves the member's franchise roles as they are.
    if seat is None or seat.role:
        roles -= {name for name in member.roles if FRANCHISE_ROLE_REGEX.match(name)}
    if seat and seat.role:
        roles.add(seat.role)

    return Plan(frozenset(roles), _nickname(rule, member, row, seat))


def _seat(rule: Rule, row: Row | None, agm: Seat | None, gm: Seat | None) -> Seat | None:
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
    # The roster and GM syncs have always taken every role ending in FA, which also clears the FA role of a tier that is gone.
    if rule.seat is not SeatSource.AGM and name.endswith("FA"):
        return True
    return name.removesuffix("FA").lower() in tier_names


def _nickname(rule: Rule, member: MemberState, row: Row | None, seat: Seat | None) -> Rename | StripPrefix:
    if row:
        return Rename(row.name, seat.prefix if seat else rule.prefix)
    if seat:
        return Rename(seat.name or rsc_name_from_display_name(member.nick), seat.prefix)
    return StripPrefix()


def _has_prefix(nick: str) -> bool:
    prefix, separator, _name = nick.partition(" | ")
    return bool(separator and prefix.strip())
