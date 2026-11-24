import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from rsc import const
from rsc.enums import Status

from .sync_fakes import DESERT_ROLE, MEMBER_ID, OCEAN_ROLE, discord_requests, forget_writes, role_names, sync_guild, sync_member

SCRIPT = Path(__file__).parent.parent / "scripts" / "sync_lab.py"
LAB_ENV = {"RSC_LAB_BOT_TOKEN": "token", "RSC_LAB_GUILD_ID": "1234", "RSC_LAB_MEMBER_ID": "5678"}


def _load_lab():
    spec = importlib.util.spec_from_file_location("sync_lab", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


lab = _load_lab()


class TestRefusal:
    def test_a_test_server_with_no_bot_running_may_run(self):
        assert lab.refusal(LAB_ENV, bot_running=False) is None

    @pytest.mark.parametrize("missing", list(LAB_ENV))
    def test_a_missing_variable_is_named(self, missing):
        env = {name: value for name, value in LAB_ENV.items() if name != missing}

        assert missing in lab.refusal(env, bot_running=False)

    def test_the_production_server_is_refused(self):
        env = LAB_ENV | {"RSC_LAB_GUILD_ID": "395806681994493964"}

        assert "production" in lab.refusal(env, bot_running=False)

    def test_a_running_bot_is_refused(self):
        assert "redbot" in lab.refusal(LAB_ENV, bot_running=True)

    def test_an_id_that_is_not_a_number_is_refused(self):
        assert lab.refusal(LAB_ENV | {"RSC_LAB_MEMBER_ID": "nickm"}, bot_running=False) is not None


class TestRedbotRunning:
    @staticmethod
    def _proc(tmp_path, *command_lines):
        for pid, argv in enumerate(command_lines, start=100):
            (tmp_path / str(pid)).mkdir()
            (tmp_path / str(pid) / "cmdline").write_bytes(b"\0".join(argv) + b"\0")
        return tmp_path

    @pytest.mark.parametrize(
        "argv",
        [
            [b"/repo/.venv/bin/python", b"/repo/.venv/bin/redbot", b"rsc", b"--dev"],
            [b"python", b"-m", b"redbot", b"rsc"],
        ],
    )
    def test_a_bot_started_either_way_is_seen(self, tmp_path, argv):
        assert lab.redbot_running(self._proc(tmp_path, [b"zsh"], argv)) is True

    def test_a_command_that_only_mentions_the_bot_is_not_the_bot(self, tmp_path):
        assert lab.redbot_running(self._proc(tmp_path, [b"zsh", b"-c", b"pgrep -f redbot"])) is False

    def test_an_unreadable_process_list_stops_the_lab(self, tmp_path):
        with pytest.raises(lab.LabError, match="cannot be read"):
            lab.redbot_running(tmp_path / "missing")


class TestScenarios:
    @pytest.fixture
    def guild(self):
        guild = sync_guild()
        guild.owner_id = 1
        return guild

    @staticmethod
    async def _play(guild, member, scenario):
        fetch = AsyncMock(return_value=member)
        chosen = await lab.prepare(guild, fetch, scenario)
        forget_writes(member)
        return await lab.sync(guild, fetch, scenario, chosen)

    @pytest.mark.parametrize(
        ("name", "roles", "nick"),
        [
            ("fresh-to-de", {const.LEAGUE_ROLE, const.DRAFT_ELIGIBLE, "Elite"}, "DE | nickm"),
            ("de-to-rostered", {const.LEAGUE_ROLE, "Elite", DESERT_ROLE}, "LAB | nickm"),
            ("rostered-to-fa", {const.LEAGUE_ROLE, "Elite", const.FREE_AGENT_ROLE, "EliteFA"}, "FA | nickm"),
            ("no-change", {const.LEAGUE_ROLE, const.DRAFT_ELIGIBLE, "Elite"}, "DE | nickm"),
        ],
    )
    async def test_a_scenario_ends_in_its_expected_state(self, guild, name, roles, nick):
        member = sync_member(guild, held=[const.SPECTATOR_ROLE, "PremierFA"], nick="OLD | nickm")

        outcome = await self._play(guild, member, lab.SCENARIOS[name])

        assert outcome.matches
        assert (role_names(member), member.display_name) == (roles, nick)
        assert sum(outcome.summary_requests.values()) == discord_requests(member)

    @pytest.mark.parametrize(
        ("state", "status"),
        [(lab.draft_eligible, Status.DRAFT_ELIGIBLE), (lab.rostered, Status.ROSTERED), (lab.free_agent, Status.FREE_AGENT)],
    )
    async def test_a_starting_state_is_one_a_sync_leaves_alone(self, guild, state, status):
        member = sync_member(guild)

        outcome = await self._play(guild, member, lab.Scenario(state, status, state))

        assert outcome.matches
        assert outcome.summary_requests == {}
        assert discord_requests(member) == 0

    async def test_reset_strips_the_member_and_runs_no_sync(self, guild):
        member = sync_member(guild, held=[const.LEAGUE_ROLE, const.CAPTAIN_ROLE, "Premier", OCEAN_ROLE], nick="OCE | nickm")

        outcome = await self._play(guild, member, lab.SCENARIOS["reset"])

        assert outcome.matches
        assert (role_names(member), member.display_name) == (set(), "nickm")
        assert outcome.summary is None

    async def test_the_owner_keeps_their_nickname_and_gets_the_roles(self, guild):
        guild.owner_id = MEMBER_ID
        member = sync_member(guild, nick="nickm")
        member.edit.side_effect = discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "Missing Permissions")

        outcome = await self._play(guild, member, lab.SCENARIOS["nick-forbidden"])

        assert outcome.matches
        assert outcome.error is None
        assert member.display_name == "nickm"
        assert role_names(member) == {const.LEAGUE_ROLE, const.DRAFT_ELIGIBLE, "Elite"}
        assert "failed=1" in outcome.summary

    async def test_nick_forbidden_is_refused_for_anyone_but_the_owner(self, guild):
        member = sync_member(guild)

        with pytest.raises(lab.LabError, match="server owner"):
            await lab.prepare(guild, AsyncMock(return_value=member), lab.SCENARIOS["nick-forbidden"])

        assert discord_requests(member) == 0

    async def test_a_server_without_a_tier_is_refused(self, guild):
        guild.roles = [role for role in guild.roles if not role.name.endswith("FA")]

        with pytest.raises(lab.LabError, match="tier"):
            await lab.prepare(guild, AsyncMock(return_value=sync_member(guild)), lab.SCENARIOS["fresh-to-de"])


class TestRequestList:
    @pytest.mark.parametrize(
        ("method", "path", "kind"),
        [
            ("PUT", "/api/v10/guilds/1/members/2/roles/3", "add_role"),
            ("DELETE", "/api/v10/guilds/1/members/2/roles/3", "remove_role"),
            ("PATCH", "/api/v10/guilds/1/members/2", "edit"),
            ("GET", "/api/v10/guilds/1/members/2", "other"),
        ],
    )
    def test_a_request_is_named_the_way_the_summary_names_it(self, method, path, kind):
        assert lab.request_kind(method, path) == kind

    def test_ids_are_replaced_so_two_runs_can_be_compared(self):
        guild = MagicMock(spec=discord.Guild)
        guild.id = 1
        guild.roles = []
        for role_id, name in ((1, "@everyone"), (3, "League")):
            role = MagicMock(spec=discord.Role)
            role.id = role_id
            role.name = name
            guild.roles.append(role)

        assert lab.readable("PUT", "/api/v10/guilds/1/members/2/roles/3", guild, 2) == "PUT /guilds/{guild}/members/{member}/roles/League"
