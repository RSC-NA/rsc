"""Departed player reconciliation.

The guardrail tests are the point of this file. `find_departed_players` feeds a
bulk retire, so a false "they left the server" is a player wrongly removed from
the league. Every case below exists to prove a specific way that cannot happen.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rsc.admin.models import DepartedReport
from rsc.admin.retire import (
    AUDIT_ABORT_FLOOR,
    AUDIT_MEMBER_FETCH_LIMIT,
    AdminRetireMixIn,
)
from rsc.enums import Status

GUILD_ID = 395806681994493964


def _create_mixin(**attrs):
    """Create an AdminRetireMixIn instance bypassing ABC restrictions."""
    saved = AdminRetireMixIn.__abstractmethods__
    AdminRetireMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(AdminRetireMixIn)
    finally:
        AdminRetireMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _make_league_player(discord_id: int, status: Status = Status.ROSTERED, team: str | None = "Team", franchise: str = "Franchise"):
    lp = MagicMock()
    lp.status = status
    lp.player = MagicMock()
    lp.player.discord_id = discord_id
    if team:
        lp.team = MagicMock()
        lp.team.name = team
        lp.team.franchise = MagicMock()
        lp.team.franchise.name = franchise
    else:
        lp.team = None
    return lp


def _paged(players):
    async def _iter(*args, **kwargs):
        for p in players:
            yield p

    return _iter


@pytest.fixture
def guild():
    g = MagicMock(spec=discord.Guild)
    g.id = GUILD_ID
    g.name = "RSC 3v3"
    g.unavailable = False
    g.member_count = 1000
    g.members = [MagicMock()] * 1000
    g.chunked = True
    return g


@pytest.fixture
def mixin(guild):
    bot = MagicMock()
    bot.is_closed.return_value = False
    bot.guilds = [guild]

    m = _create_mixin(bot=bot)
    m._api_conf = {guild.id: MagicMock()}
    m._league = {guild.id: 1}
    m._ensure_chunked = AsyncMock(return_value=True)
    m._resolve_members_by_id = AsyncMock(return_value=([], [], []))
    m.paged_players = _paged([])
    m._get_event_channel = AsyncMock(return_value=MagicMock(spec=discord.TextChannel))
    m._try_post_embeds = AsyncMock()
    m._get_retire_audit_enabled = AsyncMock(return_value=True)
    m.bulk_retire_players = AsyncMock()
    m._format_truncated_list = AdminRetireMixIn._format_truncated_list
    return m


class TestFindDepartedPlayers:
    async def test_reports_players_discord_confirmed_as_gone(self, mixin, guild):
        players = [_make_league_player(i) for i in range(100, 200)]
        mixin.paged_players = _paged(players)
        mixin._resolve_members_by_id.return_value = ([], [100, 101], [])

        report = await mixin.find_departed_players(guild)

        assert report.aborted is None
        assert report.departed == [100, 101]
        assert report.total_active == 100
        mixin._resolve_members_by_id.assert_awaited_once()
        assert mixin._resolve_members_by_id.await_args.kwargs["fetch_limit"] == AUDIT_MEMBER_FETCH_LIMIT

    async def test_lookup_failures_are_never_actionable(self, mixin, guild):
        """'Could not tell' is not 'they left'."""
        mixin.paged_players = _paged([_make_league_player(i) for i in range(100, 200)])
        mixin._resolve_members_by_id.return_value = ([], [], [100, 101, 102])

        report = await mixin.find_departed_players(guild)

        assert report.departed == []
        assert report.lookup_failed == [100, 101, 102]

    async def test_cache_miss_that_resolves_is_not_departed(self, mixin, guild):
        """A `get_member` miss whose `fetch_member` succeeds lands in `found`, not `left_guild`."""
        resolved = MagicMock(spec=discord.Member)
        mixin.paged_players = _paged([_make_league_player(100)])
        mixin._resolve_members_by_id.return_value = ([resolved], [], [])

        report = await mixin.find_departed_players(guild)

        assert report.departed == []

    async def test_only_active_statuses_are_checked(self, mixin, guild):
        mixin.paged_players = _paged(
            [
                _make_league_player(100, status=Status.ROSTERED),
                _make_league_player(101, status=Status.FORMER),
                _make_league_player(102, status=Status.DROPPED),
                _make_league_player(103, status=Status.BANNED),
                _make_league_player(104, status=Status.FREE_AGENT),
            ]
        )

        report = await mixin.find_departed_players(guild)

        assert report.total_active == 2
        assert sorted(mixin._resolve_members_by_id.await_args.args[1]) == [100, 104]

    async def test_players_without_a_discord_id_are_skipped(self, mixin, guild):
        mixin.paged_players = _paged([_make_league_player(100), _make_league_player(None)])

        report = await mixin.find_departed_players(guild)

        assert report.total_active == 1


class TestGuardrails:
    async def test_aborts_when_bot_is_disconnected(self, mixin, guild):
        mixin.bot.is_closed.return_value = True
        mixin.paged_players = MagicMock(side_effect=AssertionError("must not page the API"))

        report = await mixin.find_departed_players(guild)

        assert report.aborted
        assert report.departed == []
        mixin._resolve_members_by_id.assert_not_awaited()

    async def test_aborts_when_guild_is_unavailable(self, mixin, guild):
        guild.unavailable = True
        mixin.paged_players = MagicMock(side_effect=AssertionError("must not page the API"))

        report = await mixin.find_departed_players(guild)

        assert report.aborted
        assert report.departed == []

    async def test_aborts_when_chunking_fails(self, mixin, guild):
        """A cold cache makes every player look like they left."""
        mixin._ensure_chunked.return_value = False
        mixin.paged_players = MagicMock(side_effect=AssertionError("must not page the API"))

        report = await mixin.find_departed_players(guild)

        assert report.aborted
        assert report.departed == []
        mixin._resolve_members_by_id.assert_not_awaited()

    async def test_aborts_on_a_thin_member_cache(self, mixin, guild):
        guild.members = [MagicMock()] * 500  # 50% of member_count
        mixin.paged_players = MagicMock(side_effect=AssertionError("must not page the API"))

        report = await mixin.find_departed_players(guild)

        assert report.aborted
        assert "member cache" in report.aborted
        assert report.departed == []

    async def test_aborts_when_too_much_of_the_league_looks_gone(self, mixin, guild):
        mixin.paged_players = _paged([_make_league_player(i) for i in range(100, 200)])
        mixin._resolve_members_by_id.return_value = ([], list(range(100, 140)), [])

        report = await mixin.find_departed_players(guild)

        assert report.aborted
        assert "sanity limit" in report.aborted
        assert report.departed == []

    async def test_small_absolute_counts_are_not_blocked_by_the_ratio(self, mixin, guild):
        """A tiny league with two leavers crosses the ratio without being suspicious."""
        departed = list(range(100, 100 + AUDIT_ABORT_FLOOR - 1))
        mixin.paged_players = _paged([_make_league_player(i) for i in range(100, 120)])
        mixin._resolve_members_by_id.return_value = ([], departed, [])

        report = await mixin.find_departed_players(guild)

        assert report.aborted is None
        assert report.departed == departed


class TestAuditLoop:
    async def test_posts_a_report_and_retires_nobody(self, mixin, guild):
        mixin.paged_players = _paged([_make_league_player(i) for i in range(100, 200)])
        mixin._resolve_members_by_id.return_value = ([], [100], [])

        report = await mixin.run_retire_audit(guild)

        assert report is not None
        assert report.departed == [100]
        mixin._try_post_embeds.assert_awaited_once()
        mixin.bulk_retire_players.assert_not_awaited()

    async def test_skips_when_disabled(self, mixin, guild):
        mixin._get_retire_audit_enabled.return_value = False

        assert await mixin.run_retire_audit(guild) is None
        mixin._try_post_embeds.assert_not_awaited()

    async def test_skips_an_unprepared_guild(self, mixin, guild):
        mixin._league = {}

        assert await mixin.run_retire_audit(guild) is None
        mixin._try_post_embeds.assert_not_awaited()

    async def test_skips_without_an_event_channel(self, mixin, guild):
        mixin._get_event_channel.return_value = None

        assert await mixin.run_retire_audit(guild) is None
        mixin._try_post_embeds.assert_not_awaited()

    async def test_one_bad_guild_does_not_kill_the_loop(self, mixin, guild):
        second = MagicMock(spec=discord.Guild)
        second.id = 999
        second.name = "Other"
        mixin.bot.guilds = [guild, second]
        mixin.run_retire_audit = AsyncMock(side_effect=[RuntimeError("boom"), None])

        await AdminRetireMixIn.retire_audit_loop.coro(mixin)

        assert mixin.run_retire_audit.await_count == 2


def _interaction(guild):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 222222222
    interaction.user.display_name = "Admin"
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


class TestRetireDepartedCommand:
    @pytest.fixture(autouse=True)
    def _defer(self):
        with patch("rsc.admin.retire.utils.safe_defer", new_callable=AsyncMock):
            yield

    async def test_dry_run_is_the_default(self, mixin, guild):
        mixin.find_departed_players = AsyncMock(return_value=DepartedReport(departed=[100, 101], total_active=50))
        interaction = _interaction(guild)

        await AdminRetireMixIn._admin_retire_departed_cmd.callback(mixin, interaction)

        mixin.bulk_retire_players.assert_not_awaited()
        embed = interaction.followup.send.await_args.kwargs["embed"]
        assert "Dry run" in embed.footer.text

    async def test_declining_the_confirmation_retires_nobody(self, mixin, guild):
        mixin.find_departed_players = AsyncMock(return_value=DepartedReport(departed=[100, 101], total_active=50))
        interaction = _interaction(guild)

        view = MagicMock()
        view.prompt = AsyncMock()
        view.wait = AsyncMock()
        view.result = False

        with patch("rsc.admin.retire.ConfirmRetireView", return_value=view):
            await AdminRetireMixIn._admin_retire_departed_cmd.callback(mixin, interaction, apply=True)

        mixin.bulk_retire_players.assert_not_awaited()

    async def test_confirming_retires_the_departed_players(self, mixin, guild):
        mixin.find_departed_players = AsyncMock(return_value=DepartedReport(departed=[100, 101], total_active=50))
        mixin.build_bulk_retire_embed = MagicMock(return_value=discord.Embed())
        interaction = _interaction(guild)

        view = MagicMock()
        view.prompt = AsyncMock()
        view.wait = AsyncMock()
        view.result = True

        with patch("rsc.admin.retire.ConfirmRetireView", return_value=view):
            await AdminRetireMixIn._admin_retire_departed_cmd.callback(mixin, interaction, apply=True)

        mixin.bulk_retire_players.assert_awaited_once()
        assert mixin.bulk_retire_players.await_args.kwargs["discord_ids"] == [100, 101]
        # Durable audit trail of who ran it and what changed.
        mixin._try_post_embeds.assert_awaited_once()

    async def test_an_aborted_audit_never_reaches_the_confirmation(self, mixin, guild):
        mixin.find_departed_players = AsyncMock(return_value=DepartedReport(aborted="cache is cold", departed=[]))
        interaction = _interaction(guild)

        with patch("rsc.admin.retire.ConfirmRetireView", side_effect=AssertionError("must not prompt")):
            await AdminRetireMixIn._admin_retire_departed_cmd.callback(mixin, interaction, apply=True)

        mixin.bulk_retire_players.assert_not_awaited()
