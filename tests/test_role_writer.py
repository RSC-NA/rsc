import asyncio
import logging
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import discord
import pytest
from rscapi.models.franchise_gm import FranchiseGM

from rsc import const
from rsc.enums import Status
from rsc.exceptions import DiscordNameTooLong
from rsc.transactions import writer
from rsc.transactions.roles import update_league_player_discord
from rsc.transactions.writer import (
    NicknameRefusedError,
    Request,
    SyncKind,
    api_pages,
    api_read,
    apply_member_changes,
    member_visited,
    sync_run,
    waiting_for_staff,
)

from .sync_fakes import (
    BOT_POSITION,
    OCEAN_ROLE,
    ROLE_NAMES,
    TIERS,
    agm_franchise,
    discord_requests,
    forbidden,
    forget_writes,
    league_player,
    role_names,
    sync_guild,
    sync_member,
    sync_role,
)


class Clock:
    def __init__(self):
        self.now = 100.0

    async def passes(self, seconds: float, result: object = None) -> object:
        self.now += seconds
        return result


@pytest.fixture
def clock(monkeypatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(writer.time, "perf_counter", lambda: clock.now)
    return clock


@pytest.fixture
def guild() -> MagicMock:
    return sync_guild()


@pytest.fixture
def member(guild) -> MagicMock:
    return sync_member(guild, held=[const.LEAGUE_ROLE, const.FREE_AGENT_ROLE])


def role(guild: MagicMock, name: str) -> MagicMock:
    return next(r for r in guild.roles if r.name == name)


def summaries(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if "Sync summary." in r.getMessage()]


class TestOneRequest:
    async def test_removals_additions_and_the_nickname_go_in_one_edit(self, guild, member):
        league, premier, captain = role(guild, const.LEAGUE_ROLE), role(guild, "Premier"), role(guild, const.CAPTAIN_ROLE)

        with sync_run(SyncKind.PLAYERS, guild) as stats:
            await apply_member_changes(member, remove=[role(guild, const.FREE_AGENT_ROLE)], add=[premier, captain], nick="OCE | nickm")

        member.edit.assert_awaited_once_with(roles=[league, premier, captain], nick="OCE | nickm")
        member.add_roles.assert_not_awaited()
        member.remove_roles.assert_not_awaited()
        assert stats.requests == {Request.EDIT: 1}
        assert stats.changed == {member.id}
        assert stats.failed == set()

    async def test_a_role_change_alone_carries_no_nickname(self, guild, member):
        league = role(guild, const.LEAGUE_ROLE)

        with sync_run(SyncKind.PLAYERS, guild) as stats:
            await apply_member_changes(member, remove=[role(guild, const.FREE_AGENT_ROLE)])

        member.edit.assert_awaited_once_with(roles=[league])
        assert stats.requests == {Request.EDIT: 1}

    async def test_a_nickname_change_alone_carries_no_roles(self, guild, member):
        with sync_run(SyncKind.PLAYERS, guild) as stats:
            await apply_member_changes(member, nick="FA | nickm")

        member.edit.assert_awaited_once_with(nick="FA | nickm")
        assert stats.requests == {Request.EDIT: 1}
        assert stats.changed == {member.id}

    async def test_nothing_to_write_sends_nothing(self, guild, member):
        with sync_run(SyncKind.PLAYERS, guild) as stats:
            await apply_member_changes(member, remove=[], add=[])

        assert discord_requests(member) == 0
        assert stats.requests == {}
        assert stats.changed == set()

    async def test_removing_a_role_not_held_and_adding_one_already_held_sends_nothing(self, guild, member):
        with sync_run(SyncKind.PLAYERS, guild) as stats:
            await apply_member_changes(member, remove=[role(guild, const.CAPTAIN_ROLE)], add=[role(guild, const.LEAGUE_ROLE)])

        assert discord_requests(member) == 0
        assert stats.changed == set()

    async def test_a_role_removed_and_added_back_sends_nothing(self, guild, member):
        league = role(guild, const.LEAGUE_ROLE)

        await apply_member_changes(member, remove=[league], add=[league])

        assert discord_requests(member) == 0

    async def test_a_member_written_twice_is_one_changed_member(self, guild, member):
        with sync_run(SyncKind.PLAYERS, guild) as stats:
            await apply_member_changes(member, add=[role(guild, "Premier")])
            await apply_member_changes(member, nick="FA | nickm")

        assert stats.changed == {member.id}
        assert stats.requests == {Request.EDIT: 2}

    async def test_a_reason_reaches_the_audit_log(self, guild, member):
        free_agent = role(guild, const.FREE_AGENT_ROLE)

        with sync_run(SyncKind.NONPLAYING, guild) as stats:
            await apply_member_changes(member, remove=[role(guild, const.LEAGUE_ROLE)], reason="API has no AGM record for this member")

        member.edit.assert_awaited_once_with(roles=[free_agent], reason="API has no AGM record for this member")
        assert stats.requests == {Request.EDIT: 1}

    async def test_a_write_outside_a_run_is_still_sent(self, guild, member):
        await apply_member_changes(member, add=[role(guild, "Premier")], nick="FA | nickm")

        assert "Premier" in role_names(member)
        assert member.display_name == "FA | nickm"


class TestFullRoleList:
    async def test_a_role_the_bot_cannot_manage_stays_in_the_list(self, guild, member):
        booster = sync_role("Server Booster", 3)
        booster.managed = True
        admin = sync_role("Admin", BOT_POSITION + 1)
        member.roles = [*member.roles, booster, admin]

        with pytest.raises(NicknameRefusedError):
            await apply_member_changes(
                member, remove=[role(guild, const.FREE_AGENT_ROLE)], add=[role(guild, "Premier")], nick="OCE | nickm"
            )

        member.edit.assert_awaited_once_with(roles=[role(guild, const.LEAGUE_ROLE), booster, admin, role(guild, "Premier")])
        assert {"Server Booster", "Admin"} <= role_names(member)

    async def test_the_everyone_role_is_left_out_of_the_list(self, guild, member):
        member.roles = [guild.default_role, *member.roles]

        await apply_member_changes(member, add=[role(guild, "Premier")])

        (sent,) = member.edit.await_args_list
        assert guild.default_role not in sent.kwargs["roles"]

    async def test_a_role_the_cache_gained_after_the_caller_read_the_member_is_kept(self, guild, member):
        cached = sync_member(guild, held=[const.LEAGUE_ROLE, const.FREE_AGENT_ROLE, const.SUBBED_OUT_ROLE])
        guild.get_member.return_value = cached

        await apply_member_changes(member, remove=[role(guild, const.FREE_AGENT_ROLE)], add=[role(guild, "Premier")])

        member.edit.assert_awaited_once_with(
            roles=[role(guild, const.LEAGUE_ROLE), role(guild, const.SUBBED_OUT_ROLE), role(guild, "Premier")]
        )

    async def test_a_role_the_cache_lost_after_the_caller_read_the_member_is_not_put_back(self, guild, member):
        guild.get_member.return_value = sync_member(guild, held=[const.FREE_AGENT_ROLE])

        await apply_member_changes(member, remove=[role(guild, const.FREE_AGENT_ROLE)], add=[role(guild, "Premier")])

        member.edit.assert_awaited_once_with(roles=[role(guild, "Premier")])

    async def test_a_member_the_cache_does_not_hold_is_written_from_their_own_roles(self, guild, member):
        await apply_member_changes(member, add=[role(guild, "Premier")])

        assert role_names(member) == {const.LEAGUE_ROLE, const.FREE_AGENT_ROLE, "Premier"}


class TestNicknameTheBotMayNotWrite:
    async def test_the_owner_gets_the_roles_and_no_nickname_in_the_request(self, guild, member):
        guild.owner_id = member.id

        with sync_run(SyncKind.PLAYERS, guild) as stats, pytest.raises(NicknameRefusedError):
            await apply_member_changes(member, add=[role(guild, "Premier")], nick="OCE | nickm")

        (sent,) = member.edit.await_args_list
        assert "nick" not in sent.kwargs
        assert "Premier" in role_names(member)
        assert stats.requests == {Request.EDIT: 1}
        assert stats.failed == {member.id}

    async def test_the_owner_with_only_a_nickname_to_change_costs_no_request(self, guild, member):
        guild.owner_id = member.id

        with sync_run(SyncKind.PLAYERS, guild) as stats, pytest.raises(NicknameRefusedError):
            await apply_member_changes(member, nick="OCE | nickm")

        assert discord_requests(member) == 0
        assert stats.requests == {}
        assert stats.changed == set()
        assert stats.failed == {member.id}

    @pytest.mark.parametrize("position", [BOT_POSITION, BOT_POSITION + 1], ids=["the bot's own top role", "a role above the bot"])
    async def test_a_member_the_bot_does_not_outrank_gets_no_nickname_in_the_request(self, guild, member, position):
        member.roles = [*member.roles, sync_role("Admin", position)]

        with sync_run(SyncKind.PLAYERS, guild) as stats, pytest.raises(NicknameRefusedError):
            await apply_member_changes(member, add=[role(guild, "Premier")], nick="OCE | nickm")

        (sent,) = member.edit.await_args_list
        assert "nick" not in sent.kwargs
        assert "Premier" in role_names(member)
        assert stats.failed == {member.id}

    async def test_a_member_just_below_the_bot_gets_the_nickname(self, guild, member):
        member.roles = [*member.roles, sync_role("Moderator", BOT_POSITION - 1)]

        await apply_member_changes(member, nick="OCE | nickm")

        assert member.display_name == "OCE | nickm"

    async def test_without_the_bot_in_the_cache_the_nickname_is_sent(self, guild, member):
        guild.me = None

        await apply_member_changes(member, add=[role(guild, "Premier")], nick="OCE | nickm")

        assert member.display_name == "OCE | nickm"
        assert discord_requests(member) == 1

    async def test_a_refused_nickname_is_retried_once_with_the_roles_only(self, guild):
        member = sync_member(guild, held=[const.LEAGUE_ROLE], nickname_refused=True)
        league, premier = role(guild, const.LEAGUE_ROLE), role(guild, "Premier")

        with sync_run(SyncKind.PLAYERS, guild) as stats, pytest.raises(NicknameRefusedError, match="Missing Permissions"):
            await apply_member_changes(member, add=[premier], nick="OCE | nickm")

        assert [sent.kwargs for sent in member.edit.await_args_list] == [
            {"roles": [league, premier], "nick": "OCE | nickm"},
            {"roles": [league, premier]},
        ]
        assert role_names(member) == {const.LEAGUE_ROLE, "Premier"}
        assert member.display_name == "nickm"
        assert stats.requests == {Request.EDIT: 2}
        assert stats.changed == {member.id}
        assert stats.failed == {member.id}

    async def test_a_refused_nickname_with_no_role_change_is_not_retried(self, guild):
        member = sync_member(guild, held=[const.LEAGUE_ROLE], nickname_refused=True)

        with sync_run(SyncKind.PLAYERS, guild) as stats, pytest.raises(NicknameRefusedError):
            await apply_member_changes(member, nick="OCE | nickm")

        assert discord_requests(member) == 1
        assert stats.requests == {Request.EDIT: 1}
        assert stats.failed == {member.id}

    async def test_the_retry_keeps_the_audit_log_reason(self, guild):
        member = sync_member(guild, nickname_refused=True)

        with pytest.raises(NicknameRefusedError):
            await apply_member_changes(member, add=[role(guild, "Premier")], nick="OCE | nickm", reason="Signed")

        assert [sent.kwargs.get("reason") for sent in member.edit.await_args_list] == ["Signed", "Signed"]


class TestFailures:
    async def test_a_refused_role_change_is_counted_and_still_raises(self, guild, member):
        member.edit.side_effect = forbidden()

        with sync_run(SyncKind.PLAYERS, guild) as stats, pytest.raises(discord.Forbidden):
            await apply_member_changes(member, add=[role(guild, "Premier")])

        assert "Premier" not in role_names(member)
        assert stats.requests == {Request.EDIT: 1}
        assert stats.failed == {member.id}
        assert stats.changed == {member.id}

    async def test_roles_refused_with_and_without_the_nickname_raise_what_discord_said(self, guild, member):
        member.edit.side_effect = forbidden()

        with sync_run(SyncKind.PLAYERS, guild) as stats, pytest.raises(discord.Forbidden):
            await apply_member_changes(member, add=[role(guild, "Premier")], nick="OCE | nickm")

        assert stats.requests == {Request.EDIT: 2}
        assert stats.failed == {member.id}

    async def test_an_error_that_is_not_a_refusal_is_not_retried(self, guild, member):
        member.edit.side_effect = discord.NotFound(MagicMock(status=404, reason="Not Found"), "Unknown Member")

        with sync_run(SyncKind.PLAYERS, guild) as stats, pytest.raises(discord.NotFound):
            await apply_member_changes(member, add=[role(guild, "Premier")], nick="OCE | nickm")

        assert stats.requests == {Request.EDIT: 1}
        assert stats.failed == {member.id}


class TestSummaryLine:
    async def test_one_line_reports_the_whole_run(self, guild, member, clock, caplog):
        async def quarter_second(**_fields: object) -> None:
            await clock.passes(0.25)

        with caplog.at_level(logging.INFO, logger="red.rsc.transactions.writer"), sync_run(SyncKind.PLAYERS, guild):
            await api_read(clock.passes(1.5))
            member_visited()
            member.edit.side_effect = quarter_second
            await apply_member_changes(
                member,
                remove=[role(guild, const.FREE_AGENT_ROLE)],
                add=[role(guild, "Premier"), role(guild, const.CAPTAIN_ROLE)],
                nick="OCE | nickm",
            )
            member_visited()
            await clock.passes(0.75)

        assert summaries(caplog) == [
            (
                "[RSC 3v3] Sync summary. kind=players visited=2 changed=1 "
                "requests={'edit': 1} failed=0 "
                "api_s=1.500 discord_s=0.250 elapsed_s=2.500"
            )
        ]

    async def test_a_run_with_no_writes_reports_an_empty_request_dict(self, guild, caplog):
        with caplog.at_level(logging.INFO, logger="red.rsc.transactions.writer"), sync_run(SyncKind.NIGHTLY, guild):
            member_visited()

        (line,) = summaries(caplog)
        assert "kind=nightly visited=1 changed=0 requests={} failed=0" in line

    async def test_the_line_is_logged_when_the_run_raises(self, guild, member, caplog):
        member.edit.side_effect = forbidden()

        with (
            caplog.at_level(logging.INFO, logger="red.rsc.transactions.writer"),
            pytest.raises(discord.Forbidden),
            sync_run(SyncKind.FREE_AGENT, guild),
        ):
            member_visited()
            await apply_member_changes(member, add=[role(guild, "Premier")])

        (line,) = summaries(caplog)
        assert "kind=freeagent visited=1 changed=1 requests={'edit': 1} failed=1" in line

    async def test_nothing_is_logged_without_a_run(self, guild, member, caplog):
        with caplog.at_level(logging.INFO, logger="red.rsc.transactions.writer"):
            member_visited()
            await apply_member_changes(member, add=[role(guild, "Premier")])

        assert summaries(caplog) == []


class TestTimers:
    async def test_api_reads_are_timed_and_return_their_result(self, guild, clock):
        with sync_run(SyncKind.MEMBER, guild) as stats:
            tiers = await api_read(clock.passes(2.0, result=TIERS))

        assert tiers is TIERS
        assert stats.api_s == 2.0
        assert stats.discord_s == 0.0

    async def test_paged_rows_are_timed_while_waiting_for_the_next_row(self, guild, clock):
        async def rows() -> AsyncIterator[int]:
            await clock.passes(1.0)
            yield 1
            await clock.passes(0.5)
            yield 2

        seen = []
        with sync_run(SyncKind.PLAYERS, guild) as stats:
            async for row in api_pages(rows()):
                seen.append(row)
                await clock.passes(10.0)

        assert seen == [1, 2]
        assert stats.api_s == 1.5

    async def test_a_failed_read_is_timed_and_still_raises(self, guild, clock):
        async def read() -> None:
            await clock.passes(3.0)
            raise RuntimeError("API is down")

        with sync_run(SyncKind.MEMBER, guild) as stats, pytest.raises(RuntimeError):
            await api_read(read())

        assert stats.api_s == 3.0

    async def test_the_wait_for_staff_is_left_out_of_the_elapsed_time(self, guild, clock):
        with sync_run(SyncKind.PLAYERS, guild) as stats:
            await clock.passes(1.0)
            with waiting_for_staff():
                await clock.passes(30.0)
            await clock.passes(2.0)

        assert stats.elapsed_s == 3.0

    async def test_reads_outside_a_run_still_return(self, clock):
        assert await api_read(clock.passes(1.0, result="tiers")) == "tiers"
        with waiting_for_staff():
            await clock.passes(1.0)


class TestRunsStaySeparate:
    async def test_two_runs_at_once_each_count_their_own_member(self, guild):
        async def run(kind: SyncKind, member: MagicMock) -> writer.SyncStats:
            with sync_run(kind, guild) as stats:
                await asyncio.sleep(0)
                await apply_member_changes(member, add=[role(guild, "Premier")])
                await asyncio.sleep(0)
                member_visited()
            return stats

        first, second = sync_member(guild), sync_member(guild)
        second.id = first.id + 1

        nightly, players = await asyncio.gather(run(SyncKind.NIGHTLY, first), run(SyncKind.PLAYERS, second))

        assert (nightly.changed, nightly.visited) == ({first.id}, 1)
        assert (players.changed, players.visited) == ({second.id}, 1)


IR_ROLE_FLIPS = "A rostered sync takes the IR role from an IR player who already holds it, so every second sync writes."
STATUSES = [
    pytest.param(status, marks=pytest.mark.xfail(strict=True, reason=IR_ROLE_FLIPS)) if status in (Status.IR, Status.AGMIR) else status
    for status in Status
]


async def sync(member: MagicMock, status: Status | None, *, agm: bool = False, name: str = "nickm") -> None:
    await update_league_player_discord(
        guild=member.guild,
        player=member,
        league_player=league_player(status, name=name) if status else None,
        tiers=TIERS,
        franchise=agm_franchise(),
        agm_franchise=agm_franchise() if agm else None,
    )


class TestRoleFunctionsSendOneRequest:
    @pytest.mark.parametrize("agm", [False, True], ids=["not an AGM", "an AGM"])
    @pytest.mark.parametrize("held", [(), ROLE_NAMES], ids=["no role", "every role"])
    @pytest.mark.parametrize("status", [*STATUSES, None])
    async def test_a_sync_sends_one_request_and_a_second_sync_sends_none(self, guild, status, held, agm):
        member = sync_member(guild, held=held, nick="FA | nickm")

        with sync_run(SyncKind.MEMBER, guild) as first:
            await sync(member, status, agm=agm)

        assert discord_requests(member) == 1
        assert first.requests == {Request.EDIT: 1}
        assert first.changed == {member.id}

        forget_writes(member)
        with sync_run(SyncKind.MEMBER, guild) as second:
            await sync(member, status, agm=agm)

        assert discord_requests(member) == 0
        assert second.requests == {}
        assert second.changed == set()

    async def test_a_role_the_cache_gained_since_the_command_was_sent_survives_the_sync(self, guild):
        from_the_command = sync_member(guild, held=[const.SPECTATOR_ROLE])
        cached = sync_member(guild, held=[const.SPECTATOR_ROLE, const.SUBBED_OUT_ROLE])
        guild.get_member.return_value = cached

        await sync(from_the_command, Status.DRAFT_ELIGIBLE)

        (sent,) = from_the_command.edit.await_args_list
        assert {r.name for r in sent.kwargs["roles"]} == {const.SUBBED_OUT_ROLE, const.LEAGUE_ROLE, const.DRAFT_ELIGIBLE, "Premier"}

    async def test_a_refused_nickname_is_logged_and_the_roles_still_apply(self, guild, caplog):
        member = sync_member(guild, nick="nickm", nickname_refused=True)

        with caplog.at_level(logging.WARNING, logger="red.rsc.transactions.roles"), sync_run(SyncKind.MEMBER, guild) as stats:
            await sync(member, Status.DRAFT_ELIGIBLE)

        assert role_names(member) == {const.LEAGUE_ROLE, const.DRAFT_ELIGIBLE, "Premier"}
        assert member.display_name == "nickm"
        assert stats.failed == {member.id}
        assert stats.requests == {Request.EDIT: 2}
        assert [r.getMessage() for r in caplog.records] == [
            f"Unable to update nickname nickm ({member.id}): 403 Forbidden (error code: 0): Missing Permissions"
        ]

    async def test_the_owner_is_synced_in_one_request_and_the_skipped_nickname_is_logged(self, guild, caplog):
        member = sync_member(guild, nick="nickm")
        guild.owner_id = member.id

        with caplog.at_level(logging.WARNING, logger="red.rsc.transactions.roles"), sync_run(SyncKind.MEMBER, guild) as stats:
            await sync(member, Status.DRAFT_ELIGIBLE)

        assert role_names(member) == {const.LEAGUE_ROLE, const.DRAFT_ELIGIBLE, "Premier"}
        assert member.display_name == "nickm"
        assert stats.failed == {member.id}
        assert stats.requests == {Request.EDIT: 1}
        (warning,) = caplog.records
        assert warning.getMessage().startswith(f"Unable to update nickname nickm ({member.id}): ")

    async def test_the_owner_already_in_sync_costs_no_request(self, guild):
        member = sync_member(guild, held=[const.LEAGUE_ROLE, const.DRAFT_ELIGIBLE, "Premier"], nick="nickm")
        guild.owner_id = member.id

        with sync_run(SyncKind.MEMBER, guild) as stats:
            await sync(member, Status.DRAFT_ELIGIBLE)

        assert discord_requests(member) == 0
        assert stats.changed == set()
        assert stats.failed == {member.id}

    @pytest.mark.parametrize("status", [Status.DRAFT_ELIGIBLE, Status.FREE_AGENT, Status.ROSTERED, Status.PERMFA_W, Status.UNSIGNED_GM])
    async def test_a_name_too_long_for_discord_gets_the_roles_in_one_request_then_raises(self, guild, status):
        member = sync_member(guild, held=[const.SPECTATOR_ROLE], nick="nickm")

        with sync_run(SyncKind.MEMBER, guild) as stats, pytest.raises(DiscordNameTooLong):
            await sync(member, status, name="a name far too long for discord to take")

        (sent,) = member.edit.await_args_list
        assert "nick" not in sent.kwargs
        assert const.LEAGUE_ROLE in role_names(member)
        assert const.SPECTATOR_ROLE not in role_names(member)
        assert member.display_name == "nickm"
        assert stats.requests == {Request.EDIT: 1}

    async def test_a_non_playing_agm_whose_tag_does_not_fit_keeps_the_roles_and_the_sync_does_not_raise(self, guild):
        member = sync_member(guild, nick="nickm")
        franchise = agm_franchise()
        franchise.agms = [FranchiseGM(rsc_name="a name far too long for discord to take", discord_id=member.id)]

        await update_league_player_discord(guild=guild, player=member, league_player=None, tiers=TIERS, agm_franchise=franchise)

        assert role_names(member) == {const.LEAGUE_ROLE, const.AGM_ROLE, OCEAN_ROLE}
        assert member.display_name == "nickm"
        assert discord_requests(member) == 1
