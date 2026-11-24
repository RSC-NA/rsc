import asyncio
import logging
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from rsc import const
from rsc.enums import Status
from rsc.transactions import writer
from rsc.transactions.roles import update_league_player_discord
from rsc.transactions.writer import (
    Request,
    SyncKind,
    api_pages,
    api_read,
    apply_member_changes,
    member_visited,
    sync_run,
    waiting_for_staff,
)

from .sync_fakes import TIERS, discord_requests, forget_writes, league_player, role_names, sync_guild, sync_member


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


def forbidden() -> discord.Forbidden:
    return discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "Missing Permissions")


def summaries(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if "Sync summary." in r.getMessage()]


class TestRequestCounts:
    async def test_an_add_counts_one_request_per_role(self, guild, member):
        premier, captain = role(guild, "Premier"), role(guild, const.CAPTAIN_ROLE)

        with sync_run(SyncKind.PLAYERS, guild) as stats:
            await apply_member_changes(member, add=[premier, captain])

        member.add_roles.assert_awaited_once_with(premier, captain)
        member.remove_roles.assert_not_awaited()
        member.edit.assert_not_awaited()
        assert stats.requests == {Request.ADD_ROLE: 2}
        assert stats.changed == {member.id}
        assert stats.failed == set()

    async def test_a_remove_counts_one_request_per_role(self, guild, member):
        league, free_agent = role(guild, const.LEAGUE_ROLE), role(guild, const.FREE_AGENT_ROLE)

        with sync_run(SyncKind.PLAYERS, guild) as stats:
            await apply_member_changes(member, remove=[league, free_agent])

        member.remove_roles.assert_awaited_once_with(league, free_agent)
        member.add_roles.assert_not_awaited()
        assert stats.requests == {Request.REMOVE_ROLE: 2}
        assert stats.changed == {member.id}

    async def test_a_nickname_change_counts_one_edit(self, guild, member):
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

    async def test_removals_go_first_then_additions_then_the_nickname(self, guild, member):
        writes = MagicMock()
        for name in ("remove_roles", "add_roles", "edit"):
            writes.attach_mock(getattr(member, name), name)

        with sync_run(SyncKind.PLAYERS, guild) as stats:
            await apply_member_changes(
                member, remove=[role(guild, const.FREE_AGENT_ROLE)], add=[role(guild, "Premier")], nick="OCE | nickm"
            )

        assert [name for name, _args, _kwargs in writes.mock_calls] == ["remove_roles", "add_roles", "edit"]
        assert stats.requests == {Request.REMOVE_ROLE: 1, Request.ADD_ROLE: 1, Request.EDIT: 1}

    async def test_a_member_written_twice_is_one_changed_member(self, guild, member):
        with sync_run(SyncKind.PLAYERS, guild) as stats:
            await apply_member_changes(member, add=[role(guild, "Premier")])
            await apply_member_changes(member, nick="FA | nickm")

        assert stats.changed == {member.id}
        assert stats.requests == {Request.ADD_ROLE: 1, Request.EDIT: 1}

    async def test_a_reason_reaches_the_audit_log(self, guild, member):
        member.remove_roles = AsyncMock()
        league = role(guild, const.LEAGUE_ROLE)

        with sync_run(SyncKind.NONPLAYING, guild) as stats:
            await apply_member_changes(member, remove=[league], reason="API has no AGM record for this member")

        member.remove_roles.assert_awaited_once_with(league, reason="API has no AGM record for this member")
        assert stats.requests == {Request.REMOVE_ROLE: 1}

    async def test_a_write_outside_a_run_is_still_sent(self, guild, member):
        await apply_member_changes(member, add=[role(guild, "Premier")], nick="FA | nickm")

        assert "Premier" in role_names(member)
        assert member.display_name == "FA | nickm"


class TestFailures:
    async def test_a_refused_write_is_counted_and_still_raises(self, guild, member):
        member.edit.side_effect = forbidden()

        with sync_run(SyncKind.PLAYERS, guild) as stats, pytest.raises(discord.Forbidden):
            await apply_member_changes(member, add=[role(guild, "Premier")], nick="FA | nickm")

        assert "Premier" in role_names(member)
        assert stats.requests == {Request.ADD_ROLE: 1, Request.EDIT: 1}
        assert stats.failed == {member.id}
        assert stats.changed == {member.id}

    async def test_a_refused_removal_stops_before_the_additions(self, guild, member):
        member.remove_roles.side_effect = forbidden()

        with sync_run(SyncKind.PLAYERS, guild) as stats, pytest.raises(discord.Forbidden):
            await apply_member_changes(member, remove=[role(guild, const.FREE_AGENT_ROLE)], add=[role(guild, "Premier")])

        member.add_roles.assert_not_awaited()
        assert stats.requests == {Request.REMOVE_ROLE: 1}
        assert stats.failed == {member.id}


class TestSummaryLine:
    async def test_one_line_reports_the_whole_run(self, guild, member, clock, caplog):
        async def quarter_second(*_roles: discord.Role, **_fields: str) -> None:
            await clock.passes(0.25)

        with caplog.at_level(logging.INFO, logger="red.rsc.transactions.writer"), sync_run(SyncKind.PLAYERS, guild):
            await api_read(clock.passes(1.5))
            member_visited()
            for write in (member.remove_roles, member.add_roles, member.edit):
                write.side_effect = quarter_second
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
                "requests={'remove_role': 1, 'add_role': 2, 'edit': 1} failed=0 "
                "api_s=1.500 discord_s=0.750 elapsed_s=3.000"
            )
        ]

    async def test_a_run_with_no_writes_reports_an_empty_request_dict(self, guild, caplog):
        with caplog.at_level(logging.INFO, logger="red.rsc.transactions.writer"), sync_run(SyncKind.NIGHTLY, guild):
            member_visited()

        (line,) = summaries(caplog)
        assert "kind=nightly visited=1 changed=0 requests={} failed=0" in line

    async def test_the_line_is_logged_when_the_run_raises(self, guild, member, caplog):
        member.add_roles.side_effect = forbidden()

        with (
            caplog.at_level(logging.INFO, logger="red.rsc.transactions.writer"),
            pytest.raises(discord.Forbidden),
            sync_run(SyncKind.FREE_AGENT, guild),
        ):
            member_visited()
            await apply_member_changes(member, add=[role(guild, "Premier")])

        (line,) = summaries(caplog)
        assert "kind=freeagent visited=1 changed=1 requests={'add_role': 1} failed=1" in line

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


class TestRoleFunctionsReportThroughTheRun:
    @pytest.mark.parametrize("status", [Status.DRAFT_ELIGIBLE, Status.FREE_AGENT, Status.ROSTERED, Status.PERMFA_W, None])
    async def test_a_sync_counts_every_request_and_a_second_sync_sends_none(self, guild, status):
        member = sync_member(guild, held=[const.SPECTATOR_ROLE, const.FREE_AGENT_ROLE, "EliteFA"], nick="FA | nickm")
        row = league_player(status) if status else None

        with sync_run(SyncKind.MEMBER, guild) as first:
            await update_league_player_discord(guild=guild, player=member, league_player=row, tiers=TIERS, agm_franchise=None)

        assert discord_requests(member) > 0
        assert sum(first.requests.values()) == discord_requests(member)
        assert first.changed == {member.id}

        forget_writes(member)
        with sync_run(SyncKind.MEMBER, guild) as second:
            await update_league_player_discord(guild=guild, player=member, league_player=row, tiers=TIERS, agm_franchise=None)

        assert discord_requests(member) == 0
        assert second.requests == {}
        assert second.changed == set()

    async def test_a_refused_nickname_is_one_failure_and_the_roles_still_apply(self, guild):
        member = sync_member(guild, nick="nickm")
        member.edit.side_effect = forbidden()

        with sync_run(SyncKind.MEMBER, guild) as stats:
            await update_league_player_discord(
                guild=guild, player=member, league_player=league_player(Status.DRAFT_ELIGIBLE), tiers=TIERS, agm_franchise=None
            )

        assert {const.LEAGUE_ROLE, const.DRAFT_ELIGIBLE, "Premier"} <= role_names(member)
        assert stats.failed == {member.id}
        assert stats.requests[Request.EDIT] == 1
