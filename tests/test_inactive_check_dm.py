"""Regression tests for `/admin inactivecheck dm`.

The command once queued 426 DMs when only 149 players were missing a check,
because it filtered on `missing=True` alone. The API auto-creates an
ActivityCheck for every active league player and that record keeps
`missing=True` after completion, so `completed=False` is the filter that
actually narrows the set. These tests pin that down, plus the confirmation
gate that would have caught the blast before it went out.
"""

from functools import partial
from unittest.mock import AsyncMock, MagicMock, create_autospec

import discord
import pytest

from rsc.admin.admin import AdminMixIn
from rsc.admin.inactivity import AdminInactivityMixIn
from rsc.core import RSC

# Called unbound with a stub `self`; the mixin needs a full cog to instantiate.
fetch_missing = AdminInactivityMixIn._fetch_missing_activity_checks
dm_cmd = AdminInactivityMixIn._admin_inactive_check_dm_cmd.callback
still_missing = AdminInactivityMixIn._still_missing_activity_check
build_embed = AdminInactivityMixIn._build_activity_check_dm_embed

GUILD_ID = 395806681994493955
SEASON_ID = 100
SEASON_NUMBER = 27
MSG_ID = 123456789
MODMAIL_ID = 1489437974008565840


def _mock_check(discord_id, *, completed=False, missing=True):
    check = MagicMock()
    check.discord_id = discord_id
    check.completed = completed
    check.missing = missing
    return check


def _mock_season():
    season = MagicMock()
    season.id = SEASON_ID
    season.number = SEASON_NUMBER
    return season


def _mock_guild(member_ids=()):
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.name = "RSC 3v3"
    guild.chunked = True
    guild.chunk = AsyncMock()
    cache = {}
    for pid in member_ids:
        member = MagicMock(spec=discord.Member)
        member.id = pid
        member.mention = f"<@{pid}>"
        cache[pid] = member
    guild.get_member = MagicMock(side_effect=cache.get)
    guild.fetch_member = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "nope"))
    return guild


def _mock_cog(checks, *, season=None, last_run=(None, None, None)):
    """A cog stub whose method signatures track the real ones.

    Autospec rather than a bare MagicMock so that renaming a parameter or
    adding a required one on `season_activity_checks` fails these tests
    instead of passing while production breaks.
    """
    cog = create_autospec(RSC, instance=True)
    cog.season_activity_checks.return_value = checks
    cog.current_season.return_value = season if season is not None else _mock_season()
    cog._get_activity_check_msg_id.return_value = MSG_ID
    cog._get_activity_check_dm_last_run.return_value = last_run
    cog._get_modmail_bot.return_value = MODMAIL_ID
    cog._dm_helper = MagicMock()
    cog._dm_helper.enqueue = AsyncMock()
    # Bind the real implementations under test.
    cog._fetch_missing_activity_checks = partial(fetch_missing, cog)
    cog._resolve_members_by_id = partial(AdminMixIn._resolve_members_by_id, cog)
    cog._still_missing_activity_check = partial(still_missing, cog)
    cog._format_truncated_list = AdminMixIn._format_truncated_list
    cog._build_activity_check_dm_embed = AsyncMock(return_value=MagicMock(spec=discord.Embed))
    return cog


def _mock_interaction(guild):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 555
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.fixture
def confirm_view(monkeypatch):
    """Patch the confirm gate. `.result` drives accept vs decline."""
    view = MagicMock()
    view.result = True
    view.prompt = AsyncMock()
    view.wait = AsyncMock()
    factory = MagicMock(return_value=view)
    monkeypatch.setattr("rsc.admin.inactivity.DMConfirmView", factory)
    view.factory = factory
    return view


class TestFetchMissingActivityChecks:
    """The filter bug itself. `missing=True` alone matches the whole roster."""

    async def test_requests_completed_false(self):
        cog = _mock_cog([])

        await fetch_missing(cog, _mock_guild(), SEASON_ID)

        kwargs = cog.season_activity_checks.call_args.kwargs
        assert kwargs["completed"] is False, "dropping completed=False re-opens the 426-DM bug"
        assert kwargs["missing"] is True
        assert kwargs["season_id"] == SEASON_ID

    async def test_completed_records_are_dropped_client_side(self):
        """Belt and braces: a server side regression must not re-widen the set."""
        cog = _mock_cog([_mock_check(1), _mock_check(2, completed=True), _mock_check(3)])

        result = await fetch_missing(cog, _mock_guild(), SEASON_ID)

        assert [c.discord_id for c in result] == [1, 3]

    async def test_populate_and_dm_agree(self, confirm_view):
        """The drift guard. Both commands must derive from the same helper."""
        checks = [_mock_check(i) for i in range(1, 6)] + [_mock_check(99, completed=True)]
        guild = _mock_guild(member_ids=range(1, 6))
        cog = _mock_cog(checks)

        populate_set = {c.discord_id for c in await fetch_missing(cog, guild, SEASON_ID)}

        await dm_cmd(cog, _mock_interaction(guild))
        dm_set = {call.args[0].id for call in cog._dm_helper.enqueue.call_args_list}

        assert populate_set == dm_set == {1, 2, 3, 4, 5}


class TestConfirmationGate:
    """426 DMs went out from a single command with no preview. Never again."""

    async def test_nothing_queued_before_confirm(self, confirm_view):
        guild = _mock_guild(member_ids=[1, 2, 3])
        cog = _mock_cog([_mock_check(i) for i in (1, 2, 3)])

        await dm_cmd(cog, _mock_interaction(guild))

        # prompt() must have been awaited before the first enqueue.
        confirm_view.prompt.assert_awaited_once()
        confirm_view.wait.assert_awaited_once()
        assert cog._dm_helper.enqueue.await_count == 3

    async def test_decline_queues_nothing(self, confirm_view):
        confirm_view.result = False
        guild = _mock_guild(member_ids=[1, 2, 3])
        cog = _mock_cog([_mock_check(i) for i in (1, 2, 3)])

        await dm_cmd(cog, _mock_interaction(guild))

        cog._dm_helper.enqueue.assert_not_awaited()
        cog._set_activity_check_dm_last_run.assert_not_awaited()

    async def test_quoted_count_matches_dms_sent(self, confirm_view):
        """No gap between what the admin is shown and what actually goes out."""
        # 5 resolvable, 2 who left the guild.
        checks = [_mock_check(i) for i in range(1, 8)]
        guild = _mock_guild(member_ids=range(1, 6))
        cog = _mock_cog(checks)

        await dm_cmd(cog, _mock_interaction(guild))

        prompt_embed = confirm_view.factory.call_args.args[1]
        assert "**5** player(s)" in prompt_embed.description
        assert cog._dm_helper.enqueue.await_count == 5

    async def test_duplicate_run_warning(self, confirm_view):
        guild = _mock_guild(member_ids=[1])
        cog = _mock_cog([_mock_check(1)], last_run=(SEASON_NUMBER, 1700000000, 999))

        await dm_cmd(cog, _mock_interaction(guild))

        prompt_embed = confirm_view.factory.call_args.args[1]
        assert "already sent" in prompt_embed.description
        assert "<t:1700000000:F>" in prompt_embed.description

    async def test_run_claimed_before_queueing(self, confirm_view):
        guild = _mock_guild(member_ids=[1])
        cog = _mock_cog([_mock_check(1)])

        await dm_cmd(cog, _mock_interaction(guild))

        cog._set_activity_check_dm_last_run.assert_awaited_once()
        assert cog._set_activity_check_dm_last_run.call_args.args[1] == SEASON_NUMBER


class TestUnreachableReporting:
    """A cold cache must not silently under-DM."""

    async def test_left_guild_reported_and_skipped(self, confirm_view):
        checks = [_mock_check(i) for i in range(1, 6)]
        guild = _mock_guild(member_ids=[1, 2, 3])
        cog = _mock_cog(checks)
        interaction = _mock_interaction(guild)

        await dm_cmd(cog, interaction)

        assert cog._dm_helper.enqueue.await_count == 3
        final = interaction.edit_original_response.call_args.kwargs["embed"]
        assert "**3** DMs queued" in final.description
        assert "Skipped **2** player(s) who left the server." in final.description

    async def test_all_unreachable_short_circuits(self, confirm_view):
        cog = _mock_cog([_mock_check(1), _mock_check(2)])
        interaction = _mock_interaction(_mock_guild(member_ids=[]))

        await dm_cmd(cog, interaction)

        cog._dm_helper.enqueue.assert_not_awaited()
        confirm_view.prompt.assert_not_awaited()
        assert interaction.followup.send.call_args.kwargs["embed"].title == "Nobody To DM"

    async def test_nobody_missing_short_circuits(self, confirm_view):
        cog = _mock_cog([])
        interaction = _mock_interaction(_mock_guild())

        await dm_cmd(cog, interaction)

        cog._dm_helper.enqueue.assert_not_awaited()
        confirm_view.prompt.assert_not_awaited()
        assert "All players have completed" in interaction.followup.send.call_args.kwargs["embed"].description


class TestDMEmbedCopy:
    """The buttons are the way to respond. The channel link is a fallback."""

    @staticmethod
    async def _build(channel=True):
        guild = _mock_guild()
        guild.icon = None
        chan = MagicMock(spec=discord.TextChannel)
        chan.id = 777
        chan.name = "inactivity-check"
        guild.channels = [chan] if channel else []
        cog = _mock_cog([])
        return await build_embed(cog, guild, MSG_ID)

    async def test_points_at_the_buttons(self):
        desc = (await self._build()).description

        assert "**Use the buttons below**" in desc
        assert "**I'm active**" in desc
        assert "**Withdraw**" in desc

    async def test_link_is_demoted_to_subtext(self):
        """It reads as a backup, not the call to action."""
        desc = (await self._build()).description

        assert "-# Buttons not working?" in desc
        assert "Click here to complete" not in desc
        # The fallback comes last, after the button guidance.
        assert desc.index("Use the buttons below") < desc.index("Buttons not working?")

    async def test_offers_modmail_support(self):
        desc = (await self._build()).description

        assert desc.endswith(f"-# Need help? Message <@{MODMAIL_ID}> to open a ticket.")
        # Bare mention only. The profile-link fallback reads as clutter here.
        assert "discord.com/users" not in desc
        # Support line sits below the fallback link.
        assert desc.index("Buttons not working?") < desc.index("Need help?")

    async def test_states_the_stakes(self):
        assert "**unable to play**" in (await self._build()).description

    async def test_no_channel_omits_the_fallback_but_keeps_support(self):
        desc = (await self._build(channel=False)).description

        assert "Buttons not working?" not in desc
        assert "**Use the buttons below**" in desc
        assert "Need help?" in desc

    async def test_fits_embed_limit(self):
        assert len((await self._build()).description) <= 4096


class TestPrecheck:
    """A batch drains for minutes. Players who respond mid-drain get skipped."""

    async def test_precheck_passed_to_enqueue(self, confirm_view):
        guild = _mock_guild(member_ids=[1])
        cog = _mock_cog([_mock_check(1)])

        await dm_cmd(cog, _mock_interaction(guild))

        assert cog._dm_helper.enqueue.call_args.kwargs["precheck"] is not None

    async def test_precheck_true_while_still_missing(self):
        cog = _mock_cog([_mock_check(1)])
        member = MagicMock(spec=discord.Member)
        member.id = 1

        assert await still_missing(cog, _mock_guild(), SEASON_ID, member)() is True
        assert cog.season_activity_checks.call_args.kwargs["completed"] is False

    async def test_precheck_false_once_completed(self):
        cog = _mock_cog([])
        member = MagicMock(spec=discord.Member)
        member.id = 1

        assert await still_missing(cog, _mock_guild(), SEASON_ID, member)() is False
