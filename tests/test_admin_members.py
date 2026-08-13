from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from rscapi.exceptions import ApiException

from rsc.admin.members import AdminMembersMixIn
from rsc.enums import ACTIVE_STATUSES, INACTIVE_STATUSES, StaffPositions, Status
from rsc.exceptions import RscException


def _create_mixin(**attrs):
    saved = AdminMembersMixIn.__abstractmethods__
    AdminMembersMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(AdminMembersMixIn)
    finally:
        AdminMembersMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _mock_interaction(guild):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _role(position, *, id=1, arbiter=False, project_role=""):
    r = MagicMock()
    r.id = id
    r.position = position
    r.arbiter = arbiter
    r.project_role = project_role
    r.league = MagicMock()
    r.league.name = "RSC 3v3"
    return r


def _sent_embed(interaction):
    return interaction.followup.send.await_args.kwargs["embed"]


# The decorator turns the method into an app command, so reach through to the callback
CMD = AdminMembersMixIn._member_elevated_roles_cmd.callback


class TestAdminElevatedRolesCommand:
    async def test_registered_under_admin_members(self):
        cmds = {c.name: c for c in AdminMembersMixIn._members.commands}
        assert "elevatedroles" in cmds
        assert [p.name for p in cmds["elevatedroles"].parameters] == ["member"]

    async def test_displays_each_role_as_a_field(self, mock_guild, mock_member):
        roles = [
            _role("NUMS", id=7, project_role="Numbers Cruncher"),
            _role("ADM", id=9, arbiter=True),
        ]
        mixin = _create_mixin(member_elevated_roles=AsyncMock(return_value=roles))
        interaction = _mock_interaction(mock_guild)

        await CMD(mixin, interaction, mock_member)

        embed = _sent_embed(interaction)
        assert embed.title == "Elevated Roles"
        assert "RSC 3v3" in embed.description
        assert [f.name for f in embed.fields] == ["Numbers", "Admin"]

        numbers, admin = embed.fields
        assert "**Role ID:** 7" in numbers.value
        assert "**Project Role:** Numbers Cruncher" in numbers.value
        assert "**Arbiter:** No" in numbers.value
        assert "**Arbiter:** Yes" in admin.value
        # GM/AGM are FranchiseStaff now and must not be reported here
        assert "GM" not in numbers.value

    async def test_no_roles_reports_empty(self, mock_guild, mock_member):
        mixin = _create_mixin(member_elevated_roles=AsyncMock(return_value=[]))
        interaction = _mock_interaction(mock_guild)

        await CMD(mixin, interaction, mock_member)

        embed = _sent_embed(interaction)
        assert "no elevated roles" in embed.description
        assert embed.fields == []

    async def test_unknown_position_falls_back_to_raw_value(self, mock_guild, mock_member):
        """A position the local enum has not caught up with must not crash the command."""
        mixin = _create_mixin(member_elevated_roles=AsyncMock(return_value=[_role("BOGUS")]))
        interaction = _mock_interaction(mock_guild)

        await CMD(mixin, interaction, mock_member)

        embed = _sent_embed(interaction)
        assert embed.fields[0].name == "BOGUS (unrecognized)"

    async def test_null_position_is_handled(self, mock_guild, mock_member):
        mixin = _create_mixin(member_elevated_roles=AsyncMock(return_value=[_role(None)]))
        interaction = _mock_interaction(mock_guild)

        await CMD(mixin, interaction, mock_member)

        assert _sent_embed(interaction).fields[0].name == "Unknown"

    async def test_api_error_returns_error_embed(self, mock_guild, mock_member):
        exc = RscException(response=ApiException(status=500, reason="Error"))
        mixin = _create_mixin(member_elevated_roles=AsyncMock(side_effect=exc))
        interaction = _mock_interaction(mock_guild)

        await CMD(mixin, interaction, mock_member)

        assert _sent_embed(interaction).title == "API Error"

    async def test_bypasses_permission_cache(self, mock_guild, mock_member):
        """Must hit the API directly so admins always see current truth."""
        mixin = _create_mixin(member_elevated_roles=AsyncMock(return_value=[]))
        mixin.elevated_positions = AsyncMock()
        interaction = _mock_interaction(mock_guild)

        await CMD(mixin, interaction, mock_member)

        mixin.member_elevated_roles.assert_awaited_once_with(mock_guild, mock_member.id)
        mixin.elevated_positions.assert_not_awaited()

    async def test_no_guild_is_noop(self, mock_member):
        mixin = _create_mixin(member_elevated_roles=AsyncMock())
        interaction = _mock_interaction(None)

        assert await CMD(mixin, interaction, mock_member) is None
        mixin.member_elevated_roles.assert_not_awaited()


NOTINSERVER_CMD = AdminMembersMixIn._admin_member_notinserver_cmd.callback


def _league_player(name, discord_id, status, *, lp_id=1, tier="Elite", franchise="Some Franchise"):
    lp = MagicMock()
    lp.id = lp_id
    lp.status = status.value if isinstance(status, Status) else status
    lp.tier = MagicMock()
    # `name` cannot go through the MagicMock constructor -- it configures the mock
    # rather than setting the attribute.
    lp.tier.name = tier
    lp.team = MagicMock()
    lp.team.franchise = MagicMock()
    lp.team.franchise.name = franchise
    lp.player = MagicMock()
    lp.player.name = name
    lp.player.discord_id = discord_id
    return lp


def _paged_players(players):
    """Stub for `paged_players`, which is an async generator rather than a coroutine."""

    def _stub(*args, **kwargs):
        async def _gen():
            for p in players:
                yield p

        return _gen()

    return _stub


def _notinserver_mixin(players, **attrs):
    season = MagicMock()
    season.id = 42
    season.number = 21
    defaults = {
        "current_season": AsyncMock(return_value=season),
        "_ensure_chunked": AsyncMock(return_value=True),
        "total_players": AsyncMock(return_value=len(players)),
        "paged_players": _paged_players(players),
    }
    return _create_mixin(**{**defaults, **attrs})


def _notinserver_interaction(guild):
    interaction = _mock_interaction(guild)
    interaction.edit_original_response = AsyncMock()
    return interaction


def _report_embed(interaction):
    """The summary embed. Unlike `_sent_embed`, the last send here is a code block."""
    for call in interaction.followup.send.await_args_list:
        if "embed" in call.kwargs:
            return call.kwargs["embed"]
    raise AssertionError("no embed was sent")


def _reported_ids(interaction):
    """Discord IDs in the bulkretire code block, or [] if no report was sent."""
    for call in interaction.followup.send.await_args_list:
        content = call.kwargs.get("content") or ""
        if "bulkretire" in content:
            return [line for line in content.splitlines() if line.isdigit()]
    return []


@pytest.fixture(autouse=True)
def _safe_defer():
    # The command bails when `safe_defer` is falsy, and a bare MagicMock cannot be awaited.
    with patch("rsc.admin.members.utils.safe_defer", AsyncMock(return_value=True)) as m:
        yield m


class TestActiveStatuses:
    def test_excludes_only_former_banned_dropped(self):
        assert INACTIVE_STATUSES == {Status.FORMER, Status.BANNED, Status.DROPPED}

    def test_active_is_every_other_status(self):
        assert ACTIVE_STATUSES == frozenset(Status) - INACTIVE_STATUSES
        assert Status.DRAFT_ELIGIBLE in ACTIVE_STATUSES
        assert Status.PERM_FA in ACTIVE_STATUSES
        assert Status.FORMER not in ACTIVE_STATUSES


class TestAdminNotInServerCommand:
    async def test_registered_under_admin_members(self):
        cmds = {c.name: c for c in AdminMembersMixIn._members.commands}
        assert "notinserver" in cmds
        assert [p.name for p in cmds["notinserver"].parameters] == ["status"]

    async def test_inactive_statuses_are_skipped(self, mock_guild):
        """Former/Banned/Dropped players are noise even though they are not in the server."""
        players = [_league_player(s.name, 100 + i, s) for i, s in enumerate(sorted(INACTIVE_STATUSES))]
        mixin = _notinserver_mixin(players)
        interaction = _notinserver_interaction(mock_guild)
        mock_guild.fetch_member = AsyncMock()

        await NOTINSERVER_CMD(mixin, interaction)

        mock_guild.fetch_member.assert_not_awaited()
        assert _report_embed(interaction).fields[0].value == "0"

    async def test_player_in_server_is_not_reported(self, mock_guild, mock_member):
        mixin = _notinserver_mixin([_league_player("Present", 111, Status.ROSTERED)])
        interaction = _notinserver_interaction(mock_guild)
        mock_guild.get_member = MagicMock(return_value=mock_member)
        mock_guild.fetch_member = AsyncMock()

        await NOTINSERVER_CMD(mixin, interaction)

        mock_guild.fetch_member.assert_not_awaited()
        assert _reported_ids(interaction) == []

    async def test_player_absent_from_discord_is_reported(self, mock_guild):
        mixin = _notinserver_mixin([_league_player("Gone", 222, Status.ROSTERED)])
        interaction = _notinserver_interaction(mock_guild)
        mock_guild.fetch_member = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "Unknown Member"))

        await NOTINSERVER_CMD(mixin, interaction)

        embed = _report_embed(interaction)
        assert embed.title == "League Players Not In Server"
        assert embed.fields[0].name == "Not In Server"
        assert embed.fields[0].value == "1"
        assert "No players were retired" in embed.footer.text
        assert _reported_ids(interaction) == ["222"]

    async def test_cache_miss_confirmed_by_fetch_is_not_reported(self, mock_guild, mock_member):
        """The false positive guard: a cold cache entry must not retire a present player."""
        mixin = _notinserver_mixin([_league_player("Uncached", 333, Status.FREE_AGENT)])
        interaction = _notinserver_interaction(mock_guild)
        mock_guild.fetch_member = AsyncMock(return_value=mock_member)

        await NOTINSERVER_CMD(mixin, interaction)

        mock_guild.fetch_member.assert_awaited_once_with(333)
        assert _report_embed(interaction).fields[0].value == "0"
        assert _reported_ids(interaction) == []

    async def test_missing_discord_id_is_bucketed_not_spammed(self, mock_guild):
        mixin = _notinserver_mixin([_league_player("NoId", None, Status.ROSTERED, lp_id=77)])
        interaction = _notinserver_interaction(mock_guild)
        mock_guild.fetch_member = AsyncMock()

        await NOTINSERVER_CMD(mixin, interaction)

        # One embed, no per-player error followup.
        assert interaction.followup.send.await_count == 1
        embed = _report_embed(interaction)
        assert embed.fields[1].name == "No Discord ID"
        assert embed.fields[1].value == "1"
        assert "NoId (league player 77)" in [f.value for f in embed.fields if f.name == "Missing Discord ID"][0]

    async def test_explicit_status_override_reports_that_status(self, mock_guild):
        players = [
            _league_player("Former", 444, Status.FORMER),
            _league_player("Rostered", 555, Status.ROSTERED),
        ]
        mixin = _notinserver_mixin(players)
        interaction = _notinserver_interaction(mock_guild)
        mock_guild.fetch_member = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "Unknown Member"))

        await NOTINSERVER_CMD(mixin, interaction, Status.FORMER)

        assert _reported_ids(interaction) == ["444"]
        assert "**Former Player** status" in _report_embed(interaction).description

    async def test_no_current_season_aborts(self, mock_guild):
        mixin = _notinserver_mixin([], current_season=AsyncMock(return_value=None))
        interaction = _notinserver_interaction(mock_guild)

        await NOTINSERVER_CMD(mixin, interaction)

        assert _report_embed(interaction).title == "Error"
        mixin.total_players.assert_not_awaited()

    async def test_unchunked_guild_aborts(self, mock_guild):
        mixin = _notinserver_mixin([], _ensure_chunked=AsyncMock(return_value=False))
        interaction = _notinserver_interaction(mock_guild)

        await NOTINSERVER_CMD(mixin, interaction)

        embed = _report_embed(interaction)
        assert embed.title == "Error"
        assert "not be trustworthy" in embed.description
        mixin.total_players.assert_not_awaited()

    async def test_api_error_returns_error_embed(self, mock_guild):
        exc = RscException(response=ApiException(status=500, reason="Error"))
        mixin = _notinserver_mixin([], total_players=AsyncMock(side_effect=exc))
        interaction = _notinserver_interaction(mock_guild)

        await NOTINSERVER_CMD(mixin, interaction)

        assert _report_embed(interaction).title == "API Error"

    async def test_scopes_query_to_current_season_id(self, mock_guild):
        """`season` takes an id. Passing a season *number* silently returns nothing."""
        mixin = _notinserver_mixin([])
        mixin.paged_players = MagicMock(side_effect=_paged_players([]))
        interaction = _notinserver_interaction(mock_guild)

        await NOTINSERVER_CMD(mixin, interaction)

        assert mixin.paged_players.call_args.kwargs["season"] == 42
        assert "season_number" not in mixin.paged_players.call_args.kwargs
        mixin.total_players.assert_awaited_once_with(mock_guild, season=42)

    async def test_no_guild_is_noop(self):
        mixin = _notinserver_mixin([])
        interaction = _notinserver_interaction(None)

        assert await NOTINSERVER_CMD(mixin, interaction) is None
        mixin.current_season.assert_not_awaited()


class TestStaffPositionsFullName:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("TM", "Transactions"),
            ("TMH", "Transactions Head"),
            ("FRAN", "Franchise Manager"),
            ("NH", "Numbers Head"),
            ("NUMS", "Numbers"),
            ("MMR", "MMR Puller"),
            ("ADM", "Admin"),
        ],
    )
    def test_full_name_matches_api_description(self, value, expected):
        assert StaffPositions(value).full_name == expected

    def test_every_position_has_a_readable_name(self):
        """No position may render as a bare enum member name (e.g. 'NUMBERS_HEAD')."""
        for p in StaffPositions:
            assert p.full_name, f"{p.name} has no full_name"
            assert "_" not in p.full_name, f"{p.name} renders unformatted: {p.full_name}"
