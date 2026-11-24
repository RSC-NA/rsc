from dataclasses import replace
from typing import NamedTuple

import pytest
from rscapi.models.franchise_gm import FranchiseGM
from rscapi.models.franchise_list import FranchiseList

from rsc import const
from rsc.enums import Status, SubStatus
from rsc.transactions import roles
from rsc.transactions.planner import MemberState, NoRow, Plan, Rename, Row, Seat, SeatWithoutRole, StripPrefix, plan_member

from .sync_fakes import (
    DESERT_ROLE,
    MEMBER_ID,
    OCEAN_ROLE,
    ROLE_NAMES,
    TIERS,
    agm_franchise,
    discord_requests,
    forget_writes,
    league_player,
    role_names,
    sync_guild,
    sync_member,
)

TIER_NAMES = ["Premier", "Elite"]
UNMANAGED = frozenset({const.GM_ROLE, const.MUTED_ROLE, "Server Booster"})
EVERY_ROLE = MemberState(frozenset(ROLE_NAMES) | UNMANAGED, "OLD | nickm")
NO_ROLE = MemberState(frozenset(), "nickm")

ROSTER = Seat(OCEAN_ROLE, "OCE")
GM = Seat(OCEAN_ROLE, "OCE", "someone")
AGM = Seat(DESERT_ROLE, "DES", "nickm")
ROW = Row(name="nickm", tier="Premier", team=ROSTER)

LEAGUE = const.LEAGUE_ROLE
SUBBED_OUT = const.SUBBED_OUT_ROLE


class Expected(NamedTuple):
    gives: set[str]
    tag: str | None
    untouched: frozenset[str] = frozenset()


ROSTERED = Expected({LEAGUE, "Premier", OCEAN_ROLE}, "OCE")
INACTIVE_RESERVE = Expected({LEAGUE, const.IR_ROLE, "Premier", OCEAN_ROLE}, "OCE")
WAIVERS = Expected({LEAGUE, "Premier", "PremierFA"}, "FA")
NON_PLAYING = Expected(set(), None, untouched=frozenset({const.SPECTATOR_ROLE, const.FORMER_PLAYER_ROLE}))
EXPECTED: dict[Status | NoRow, Expected] = {
    Status.ROSTERED: ROSTERED,
    Status.RENEWED: ROSTERED,
    Status.IR: INACTIVE_RESERVE,
    Status.AGMIR: INACTIVE_RESERVE,
    Status.UNSIGNED_GM: Expected({LEAGUE, "Premier", OCEAN_ROLE}, "OCE", untouched=frozenset({const.AGM_ROLE})),
    NoRow.NON_PLAYING_GM: Expected({LEAGUE, OCEAN_ROLE}, "OCE", untouched=frozenset({SUBBED_OUT})),
    Status.FREE_AGENT: Expected({LEAGUE, const.FREE_AGENT_ROLE, "Premier", "PremierFA"}, "FA"),
    Status.PERM_FA: Expected({LEAGUE, const.PERM_FA_ROLE, "Premier", "PremierFA"}, "PFA"),
    Status.WAIVERS: WAIVERS,
    Status.WAIVER_CLAIM: WAIVERS,
    Status.WAIVER_RELEASE: WAIVERS,
    Status.DRAFT_ELIGIBLE: Expected({LEAGUE, const.DRAFT_ELIGIBLE, "Premier"}, "DE"),
    Status.PERMFA_W: Expected({LEAGUE, const.PERM_FA_WAITING_ROLE}, "PFW"),
    Status.DROPPED: NON_PLAYING,
    Status.FORMER: NON_PLAYING,
    Status.BANNED: NON_PLAYING,
    NoRow.NON_PLAYING: NON_PLAYING,
}
STANDINGS = list(EXPECTED)
OUT_OF_LEAGUE = (Status.DROPPED, Status.FORMER, Status.BANNED, NoRow.NON_PLAYING)
ON_A_FRANCHISE = (Status.ROSTERED, Status.RENEWED, Status.IR, Status.AGMIR, Status.UNSIGNED_GM, NoRow.NON_PLAYING_GM)


def plan(standing: Status | NoRow, member: MemberState, **facts) -> Plan:
    facts.setdefault("tiers", TIER_NAMES)
    if isinstance(standing, Status):
        facts.setdefault("row", ROW)
    return plan_member(standing, member, gm=GM, **facts)


def written(member: MemberState, result: Plan) -> MemberState:
    match result.nickname:
        case Rename(name, prefix):
            nick = f"{prefix} | {name}" if prefix else name
        case StripPrefix():
            nick = member.nick.split(" | ", maxsplit=1)[-1]
    return MemberState(result.final_roles, nick)


class TestEveryStanding:
    @pytest.mark.parametrize("standing", STANDINGS)
    def test_a_member_with_no_role_gets_the_roles_the_standing_gives(self, standing):
        assert plan(standing, NO_ROLE).final_roles == EXPECTED[standing].gives

    @pytest.mark.parametrize("standing", STANDINGS)
    def test_a_member_with_every_role_keeps_what_the_standing_gives_or_leaves_and_every_unmanaged_role(self, standing):
        expected = EXPECTED[standing]

        assert plan(standing, EVERY_ROLE).final_roles == expected.gives | expected.untouched | UNMANAGED

    @pytest.mark.parametrize("standing", STANDINGS)
    def test_the_nickname(self, standing):
        name = "someone" if standing is NoRow.NON_PLAYING_GM else "nickm"
        renamed = Rename(name, EXPECTED[standing].tag)

        assert plan(standing, EVERY_ROLE).nickname == (StripPrefix() if standing in OUT_OF_LEAGUE else renamed)

    @pytest.mark.parametrize("standing", [s for s in STANDINGS if s not in ON_A_FRANCHISE])
    def test_an_agm_off_a_roster_holds_the_agm_role_the_league_role_and_their_franchise_role_and_tag(self, standing):
        result = plan(standing, NO_ROLE, agm=AGM)

        assert result.final_roles == EXPECTED[standing].gives | {const.AGM_ROLE, LEAGUE, DESERT_ROLE}
        assert result.nickname == Rename("nickm", "DES")

    @pytest.mark.parametrize("standing", [s for s in STANDINGS if s not in ON_A_FRANCHISE])
    def test_an_agm_off_a_roster_loses_every_other_franchise_role(self, standing):
        result = plan(standing, EVERY_ROLE, agm=AGM)

        assert DESERT_ROLE in result.final_roles
        assert OCEAN_ROLE not in result.final_roles

    @pytest.mark.parametrize("standing", [Status.ROSTERED, Status.RENEWED, Status.IR, Status.AGMIR])
    def test_a_rostered_agm_holds_the_agm_role_and_the_roster_s_franchise_role_and_tag(self, standing):
        result = plan(standing, EVERY_ROLE, agm=SeatWithoutRole("DES"))

        assert const.AGM_ROLE in result.final_roles
        assert OCEAN_ROLE in result.final_roles
        assert DESERT_ROLE not in result.final_roles
        assert result.nickname == Rename("nickm", "OCE")

    @pytest.mark.parametrize("agm", [None, AGM], ids=["not an AGM", "an AGM"])
    @pytest.mark.parametrize("member", [NO_ROLE, EVERY_ROLE], ids=["no role", "every role"])
    @pytest.mark.parametrize("standing", STANDINGS)
    def test_planning_the_member_a_plan_produced_changes_nothing(self, standing, member, agm):
        first = plan(standing, member, agm=agm)
        after = written(member, first)

        assert written(after, plan(standing, after, agm=agm)) == after


class TestRowFacts:
    @pytest.mark.parametrize("standing", [Status.IR, Status.AGMIR])
    def test_an_ir_member_who_already_holds_ir_keeps_it(self, standing):
        assert const.IR_ROLE in plan(standing, MemberState(frozenset({const.IR_ROLE}), "nickm")).final_roles

    @pytest.mark.parametrize("standing", [s for s in STANDINGS if s not in (Status.IR, Status.AGMIR)])
    def test_a_member_who_is_not_on_ir_loses_it(self, standing):
        assert const.IR_ROLE not in plan(standing, MemberState(frozenset({const.IR_ROLE}), "nickm")).final_roles

    def test_a_rostered_captain_holds_captain(self):
        assert const.CAPTAIN_ROLE in plan(Status.ROSTERED, NO_ROLE, row=Row("nickm", "Premier", captain=True, team=ROSTER)).final_roles

    def test_a_captain_flag_on_a_free_agent_row_gives_no_captain_role(self):
        assert const.CAPTAIN_ROLE not in plan(Status.FREE_AGENT, EVERY_ROLE, row=Row("nickm", "Premier", captain=True)).final_roles

    def test_a_draft_eligible_row_with_no_tier_holds_no_tier_role(self):
        assert plan(Status.DRAFT_ELIGIBLE, EVERY_ROLE, row=Row("nickm")).final_roles & {"Premier", "PremierFA", "Elite", "EliteFA"} == set()

    def test_a_row_in_another_tier_swaps_the_tier_roles(self):
        result = plan(Status.FREE_AGENT, EVERY_ROLE, row=Row("nickm", "Elite"))

        assert result.final_roles & {"Premier", "PremierFA", "Elite", "EliteFA"} == {"Elite", "EliteFA"}

    def test_a_dropped_row_is_read_as_no_row(self):
        assert plan(Status.DROPPED, EVERY_ROLE, row=Row("renamed", "Premier", captain=True, team=ROSTER)) == plan(
            NoRow.NON_PLAYING, EVERY_ROLE
        )

    def test_a_rostered_status_without_its_team_is_refused(self):
        with pytest.raises(ValueError, match="team"):
            plan(Status.ROSTERED, NO_ROLE, row=Row("nickm", "Premier"))


class TestTierRoles:
    @pytest.mark.parametrize("standing", ON_A_FRANCHISE)
    def test_a_roster_or_gm_sync_takes_a_role_ending_in_fa_that_belongs_to_no_tier(self, standing):
        assert "LegacyFA" not in plan(standing, MemberState(frozenset({"LegacyFA"}), "nickm")).final_roles

    @pytest.mark.parametrize("standing", [s for s in STANDINGS if s not in ON_A_FRANCHISE])
    def test_any_other_sync_leaves_it(self, standing):
        assert "LegacyFA" in plan(standing, MemberState(frozenset({"LegacyFA"}), "nickm")).final_roles

    @pytest.mark.parametrize("standing", STANDINGS)
    def test_no_tier_list_means_no_tier_role_is_taken(self, standing):
        held = frozenset({"Elite", "EliteFA", "LegacyFA"})

        assert held <= plan(standing, MemberState(held, "nickm"), tiers=[]).final_roles


class TestOnlyEverAdded:
    @pytest.mark.parametrize("standing", [Status.FREE_AGENT, Status.PERM_FA, Status.WAIVERS, Status.DRAFT_ELIGIBLE])
    def test_dev_league_is_added_when_asked_for(self, standing):
        assert const.DEV_LEAGUE_ROLE in plan(standing, NO_ROLE, devleague=True).final_roles
        assert const.DEV_LEAGUE_ROLE not in plan(standing, NO_ROLE).final_roles

    @pytest.mark.parametrize("standing", [Status.ROSTERED, Status.PERMFA_W, Status.UNSIGNED_GM, NoRow.NON_PLAYING])
    def test_dev_league_is_not_added_for_a_standing_that_does_not_offer_it(self, standing):
        assert const.DEV_LEAGUE_ROLE not in plan(standing, NO_ROLE, devleague=True).final_roles

    @pytest.mark.parametrize("standing", STANDINGS)
    def test_dev_league_is_never_taken(self, standing):
        assert const.DEV_LEAGUE_ROLE in plan(standing, MemberState(frozenset({const.DEV_LEAGUE_ROLE}), "nickm")).final_roles

    @pytest.mark.parametrize("agm", [None, AGM], ids=["not an AGM", "an AGM"])
    def test_a_member_out_of_the_league_gets_the_welcome_roles(self, agm):
        assert "Welcome" in plan(NoRow.NON_PLAYING, NO_ROLE, agm=agm, welcome_roles=["Welcome"]).final_roles

    def test_a_member_in_the_league_does_not(self):
        assert "Welcome" not in plan(Status.FREE_AGENT, NO_ROLE, welcome_roles=["Welcome"]).final_roles

    def test_a_welcome_role_does_not_keep_a_role_the_standing_takes(self):
        assert LEAGUE not in plan(NoRow.NON_PLAYING, MemberState(frozenset({LEAGUE}), "nickm"), welcome_roles=[LEAGUE]).final_roles


class TestOutOfTheLeague:
    def test_a_tagged_member_becomes_a_former_player(self):
        assert const.FORMER_PLAYER_ROLE in plan(NoRow.NON_PLAYING, MemberState(frozenset(), "OCE | nickm")).final_roles

    def test_an_untagged_member_does_not(self):
        assert const.FORMER_PLAYER_ROLE not in plan(NoRow.NON_PLAYING, NO_ROLE).final_roles

    def test_an_agm_s_tag_does_not_make_them_a_former_player(self):
        assert const.FORMER_PLAYER_ROLE not in plan(NoRow.NON_PLAYING, MemberState(frozenset(), "DES | nickm"), agm=AGM).final_roles


class TestAgmSeat:
    def test_a_franchise_with_no_role_in_the_guild_leaves_the_member_s_franchise_roles_alone(self):
        result = plan(Status.FREE_AGENT, EVERY_ROLE, agm=SeatWithoutRole("DES", "nickm"))

        assert {OCEAN_ROLE, DESERT_ROLE, const.AGM_ROLE} <= result.final_roles
        assert result.nickname == Rename("nickm", "DES")

    def test_an_agm_with_no_name_on_the_staff_list_keeps_the_name_in_their_nickname(self):
        result = plan(NoRow.NON_PLAYING, MemberState(frozenset(), "FA | nickm"), agm=Seat(DESERT_ROLE, "DES"))

        assert result.nickname == Rename("nickm", "DES")

    @pytest.mark.parametrize("standing", [s for s in STANDINGS if s not in ON_A_FRANCHISE and s not in OUT_OF_LEAGUE])
    def test_a_member_who_is_not_an_agm_loses_a_stale_agm_role(self, standing):
        assert const.AGM_ROLE not in plan(standing, MemberState(frozenset({const.AGM_ROLE}), "nickm")).final_roles

    def test_an_unsigned_gm_sync_leaves_the_agm_role_as_it_finds_it(self):
        assert const.AGM_ROLE in plan(Status.UNSIGNED_GM, MemberState(frozenset({const.AGM_ROLE}), "nickm")).final_roles
        assert const.AGM_ROLE not in plan(Status.UNSIGNED_GM, NO_ROLE).final_roles

    def test_a_member_who_is_not_an_agm_off_a_roster_loses_every_franchise_role(self):
        assert plan(Status.DRAFT_ELIGIBLE, EVERY_ROLE).final_roles & {OCEAN_ROLE, DESERT_ROLE} == set()


WITH_A_ROW = [s for s in STANDINGS if isinstance(s, Status) and s not in OUT_OF_LEAGUE]


class TestSubbedOut:
    @pytest.mark.parametrize("standing", WITH_A_ROW)
    def test_a_member_whose_row_is_subbing_out_holds_it(self, standing):
        assert SUBBED_OUT in plan(standing, NO_ROLE, row=replace(ROW, subbed_out=True)).final_roles

    @pytest.mark.parametrize("standing", WITH_A_ROW)
    def test_a_member_whose_row_is_not_subbing_out_loses_it(self, standing):
        assert SUBBED_OUT not in plan(standing, EVERY_ROLE).final_roles

    @pytest.mark.parametrize("standing", [Status.DROPPED, Status.FORMER, Status.BANNED])
    def test_a_member_out_of_the_league_loses_it_whatever_the_row_says(self, standing):
        assert SUBBED_OUT not in plan(standing, EVERY_ROLE, row=replace(ROW, subbed_out=True)).final_roles

    def test_a_non_playing_gm_has_no_row_and_keeps_it(self):
        assert SUBBED_OUT in plan(NoRow.NON_PLAYING_GM, EVERY_ROLE).final_roles
        assert SUBBED_OUT not in plan(NoRow.NON_PLAYING_GM, NO_ROLE).final_roles


def gm_franchise() -> FranchiseList:
    return FranchiseList(name="The Ocean", prefix="OCE", gm=FranchiseGM(rsc_name="someone", discord_id=MEMBER_ID), agms=[])


async def sync(member, standing: Status | NoRow, *, agm: bool = False, sub_status: SubStatus = SubStatus.NOT) -> None:
    if standing is NoRow.NON_PLAYING_GM:
        await roles.update_nonplaying_gm_discord(guild=member.guild, player=member, franchise=gm_franchise(), tiers=TIERS)
        return
    await roles.update_league_player_discord(
        guild=member.guild,
        player=member,
        league_player=league_player(standing, sub_status=sub_status) if isinstance(standing, Status) else None,
        tiers=TIERS,
        franchise=agm_franchise(),
        agm_franchise=agm_franchise() if agm else None,
    )


class TestTheSyncFunctions:
    @pytest.mark.parametrize("sub_status", [SubStatus.NOT, SubStatus.OUT], ids=["not subbing", "subbing out"])
    @pytest.mark.parametrize("agm", [False, True], ids=["not an AGM", "an AGM"])
    @pytest.mark.parametrize("held", [(), ROLE_NAMES], ids=["no role", "every role"])
    @pytest.mark.parametrize("standing", STANDINGS)
    async def test_a_second_sync_of_the_member_the_first_sync_produced_sends_no_request(self, standing, held, agm, sub_status):
        member = sync_member(sync_guild(), held=held, nick="FA | nickm")
        await sync(member, standing, agm=agm, sub_status=sub_status)
        forget_writes(member)

        await sync(member, standing, agm=agm, sub_status=sub_status)

        assert discord_requests(member) == 0

    @pytest.mark.parametrize("standing", WITH_A_ROW)
    async def test_subbed_out_follows_the_row_s_sub_status(self, standing):
        member = sync_member(sync_guild(), nick="nickm")

        await sync(member, standing, sub_status=SubStatus.OUT)
        assert SUBBED_OUT in role_names(member)

        await sync(member, standing, sub_status=SubStatus.IN)
        assert SUBBED_OUT not in role_names(member)

    async def test_a_sync_with_no_row_takes_subbed_out(self):
        member = sync_member(sync_guild(), held=[SUBBED_OUT], nick="nickm")

        await sync(member, NoRow.NON_PLAYING)

        assert SUBBED_OUT not in role_names(member)

    async def test_a_guild_without_a_role_the_sync_only_takes_still_syncs(self):
        guild = sync_guild()
        guild.roles = [role for role in guild.roles if role.name != const.CAPTAIN_ROLE]
        member = sync_member(guild, held=[const.SPECTATOR_ROLE])

        await sync(member, Status.FREE_AGENT)

        assert role_names(member) == {LEAGUE, const.FREE_AGENT_ROLE, "Premier", "PremierFA"}

    async def test_a_guild_without_a_role_the_sync_gives_raises_before_it_writes(self):
        guild = sync_guild()
        guild.roles = [role for role in guild.roles if role.name != const.FREE_AGENT_ROLE]
        member = sync_member(guild, held=[const.SPECTATOR_ROLE])

        with pytest.raises(ValueError, match="Free Agent"):
            await sync(member, Status.FREE_AGENT)

        assert role_names(member) == {const.SPECTATOR_ROLE}
        assert discord_requests(member) == 0
