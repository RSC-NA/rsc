import asyncio
import copy
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rsc.admin.permfa_poll import (
    CURRENT_ANSWER_FIELD,
    POLL_DURATION,
    PREVIEW_POLL_ID,
    AdminPermFAPollMixIn,
    PermFAPoll,
    PollClickResult,
    PollDelivery,
    PollRecipient,
    PollResponse,
    defaults_poll,
)
from rsc.admin.views import PERMFA_POLL_DM_TEMPLATE, PermFAPollButton, build_permfa_poll_view
from rsc.embeds import EmbedLimits
from rsc.exceptions import RscException
from rsc.utils.dm import DMOutcome

TEMPLATE = PermFAPollButton.__discord_ui_compiled_template__

GUILD_ID = 395806681994493955
TIER_ID = 7
POLL_ID = 1289451234567890123
ADMIN_ID = 999
NOW = 1_800_000_000
EXPIRES = NOW + int(POLL_DURATION.total_seconds())


class FakeGroup:
    """Mimics Red's custom group reads: a full path merges registered defaults,
    a partial path returns the raw nested dict."""

    def __init__(self, store: dict, ids: tuple[str, ...]):
        self.store = store
        self.ids = ids

    async def all(self):
        if len(self.ids) == 2:
            data = self.store.get(self.ids[0], {}).get(self.ids[1])
            return {**copy.deepcopy(defaults_poll), **copy.deepcopy(data or {})}
        if len(self.ids) == 1:
            return copy.deepcopy(self.store.get(self.ids[0], {}))
        return copy.deepcopy(self.store)

    async def set(self, value):
        guild, tier = self.ids
        self.store.setdefault(guild, {})[tier] = copy.deepcopy(value)


class FakeConfig:
    def __init__(self):
        self.store: dict = {}

    def custom(self, group, *ids):
        assert group == "PermFAPoll"
        return FakeGroup(self.store, ids)


@pytest.fixture
def clock():
    """Controllable wall clock for the poll module."""
    state = {"now": NOW}
    with patch("rsc.admin.permfa_poll._now", side_effect=lambda: state["now"]):
        yield state


@pytest.fixture(autouse=True)
def no_sweep_delay():
    with patch("rsc.admin.permfa_poll.SWEEP_EDIT_DELAY", 0):
        yield


def _guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.name = "RSC 3v3"
    guild.icon = None
    return guild


def _mixin(guild=None):
    saved = AdminPermFAPollMixIn.__abstractmethods__
    AdminPermFAPollMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(AdminPermFAPollMixIn)
    finally:
        AdminPermFAPollMixIn.__abstractmethods__ = saved
    m.config = FakeConfig()
    m._permfa_poll_locks = {}
    m._permfa_poll_timers = {}
    m.bot = MagicMock()
    m.bot.wait_until_ready = AsyncMock()
    m.bot.get_guild.return_value = guild
    m._dm_helper = MagicMock()
    m._dm_helper.enqueue = AsyncMock()
    m._get_permfa_announce_channel = AsyncMock(return_value=None)
    return m


def _poll(**overrides) -> PermFAPoll:
    fields = {
        "poll_id": POLL_ID,
        "tier_id": TIER_ID,
        "tier_name": "Elite",
        "season": 24,
        "created_at": NOW,
        "expires_at": EXPIRES,
        "created_by": ADMIN_ID,
        "recipients": {
            1: PollRecipient(name="Alpha", mmr=1500, delivery=PollDelivery.SENT),
            2: PollRecipient(name="Bravo", mmr=1400, delivery=PollDelivery.SENT),
        },
    }
    fields.update(overrides)
    return PermFAPoll(**fields)


async def _store(mixin, poll: PermFAPoll):
    await mixin._save_permfa_poll(GUILD_ID, poll)


async def _load(mixin) -> PermFAPoll:
    poll = await mixin._get_permfa_poll(GUILD_ID, TIER_ID)
    assert poll is not None
    return poll


def _message(channel_id=500, message_id=600):
    message = MagicMock(spec=discord.Message)
    message.id = message_id
    message.channel = MagicMock()
    message.channel.id = channel_id
    message.edit = AsyncMock()
    return message


# --- Template and view ---


class TestTemplate:
    def test_template_constant_matches_compiled_pattern(self):
        assert TEMPLATE.pattern == PERMFA_POLL_DM_TEMPLATE

    @pytest.mark.parametrize("yes", [True, False])
    def test_generated_custom_id_round_trips(self, yes):
        button = PermFAPollButton(guild_id=GUILD_ID, tier_id=TIER_ID, poll_id=POLL_ID, yes=yes)
        match = TEMPLATE.fullmatch(button.item.custom_id)
        assert match
        assert int(match["guild"]) == GUILD_ID
        assert int(match["tier"]) == TIER_ID
        assert int(match["poll"]) == POLL_ID
        assert match["choice"] == ("yes" if yes else "no")

    @pytest.mark.parametrize(
        "custom_id",
        [
            "pfa_poll:1:2:3:maybe",
            "pfa_poll:1:2:yes",
            "pfa_poll:a:2:3:yes",
            "intent_dm:1:2:yes",
            "pfa_poll:1:2:3:yes:extra",
        ],
    )
    def test_rejects_malformed_custom_id(self, custom_id):
        assert TEMPLATE.fullmatch(custom_id) is None

    def test_custom_id_fits_discord_limit(self):
        button = PermFAPollButton(guild_id=2**64 - 1, tier_id=2**64 - 1, poll_id=2**64 - 1, yes=True)
        assert len(button.item.custom_id) <= 100

    async def test_from_custom_id_parses_all_fields(self):
        match = TEMPLATE.fullmatch(f"pfa_poll:{GUILD_ID}:{TIER_ID}:{POLL_ID}:no")
        assert match
        button = await PermFAPollButton.from_custom_id(MagicMock(), MagicMock(), match)
        assert (button.guild_id, button.tier_id, button.poll_id, button.yes) == (GUILD_ID, TIER_ID, POLL_ID, False)

    def test_view_has_yes_and_no_and_never_times_out(self):
        view = build_permfa_poll_view(GUILD_ID, TIER_ID, POLL_ID)
        assert view.timeout is None
        ids = [child.item.custom_id for child in view.children]
        assert ids == [f"pfa_poll:{GUILD_ID}:{TIER_ID}:{POLL_ID}:yes", f"pfa_poll:{GUILD_ID}:{TIER_ID}:{POLL_ID}:no"]


# --- Model ---


class TestPollModel:
    def test_open_until_the_deadline(self):
        poll = _poll()
        assert poll.is_open(EXPIRES - 1)
        assert not poll.is_open(EXPIRES)

    def test_closed_early_is_not_open(self):
        assert not _poll(closed_at=NOW + 10).is_open(NOW + 20)

    def test_closed_time_falls_back_to_deadline(self):
        assert _poll().closed_time() == EXPIRES
        assert _poll(closed_at=NOW + 5).closed_time() == NOW + 5

    def test_round_trips_through_dict(self):
        poll = _poll(closed_at=NOW + 1, closed_by=ADMIN_ID, last_remind_at=NOW + 2)
        poll.recipients[1].messages = [[10, 20]]
        poll.recipients[1].response = PollResponse.YES
        poll.recipients[1].responded_at = NOW + 3
        assert PermFAPoll.from_dict(poll.to_dict()) == poll

    def test_defaults_only_record_is_no_poll(self):
        assert PermFAPoll.from_dict(dict(defaults_poll)) is None

    def test_tolerates_missing_keys(self):
        poll = PermFAPoll.from_dict({"PollId": POLL_ID, "TierId": TIER_ID})
        assert poll
        assert poll.recipients == {}
        assert poll.dms_cleaned is False


# --- Recording answers ---


class TestClick:
    async def test_no_poll_is_inactive(self, clock):
        mixin = _mixin()
        result = await mixin.permfa_poll_click(_guild(), TIER_ID, POLL_ID, 1, PollResponse.YES)
        assert result.keep_buttons is False
        assert "no longer active" in result.embed.description

    async def test_replaced_poll_is_inactive(self, clock):
        mixin = _mixin()
        await _store(mixin, _poll(poll_id=POLL_ID + 1))
        result = await mixin.permfa_poll_click(_guild(), TIER_ID, POLL_ID, 1, PollResponse.YES)
        assert result.keep_buttons is False
        assert (await _load(mixin)).recipients[1].response is None

    async def test_non_recipient_is_turned_away(self, clock):
        mixin = _mixin()
        await _store(mixin, _poll())
        result = await mixin.permfa_poll_click(_guild(), TIER_ID, POLL_ID, 12345, PollResponse.YES)
        assert result.keep_buttons is False
        assert 12345 not in (await _load(mixin)).recipients

    @pytest.mark.parametrize("closed_at", [None, NOW + 5])
    async def test_closed_or_expired_records_nothing(self, clock, closed_at):
        mixin = _mixin()
        await _store(mixin, _poll(closed_at=closed_at))
        clock["now"] = EXPIRES + 1

        result = await mixin.permfa_poll_click(_guild(), TIER_ID, POLL_ID, 1, PollResponse.YES)

        assert result.keep_buttons is False
        assert "(Closed)" in result.embed.title
        assert (await _load(mixin)).recipients[1].response is None

    async def test_answer_can_be_changed(self, clock):
        mixin = _mixin()
        await _store(mixin, _poll())

        result = await mixin.permfa_poll_click(_guild(), TIER_ID, POLL_ID, 1, PollResponse.YES)
        assert result.keep_buttons is True
        assert (await _load(mixin)).recipients[1].response == PollResponse.YES

        clock["now"] = NOW + 60
        result = await mixin.permfa_poll_click(_guild(), TIER_ID, POLL_ID, 1, PollResponse.NO)
        recipient = (await _load(mixin)).recipients[1]
        assert result.keep_buttons is True
        assert recipient.response == PollResponse.NO
        assert recipient.responded_at == NOW + 60

    async def test_repeating_an_answer_keeps_its_first_come_time(self, clock):
        mixin = _mixin()
        await _store(mixin, _poll())
        await mixin.permfa_poll_click(_guild(), TIER_ID, POLL_ID, 1, PollResponse.YES)
        clock["now"] = NOW + 60
        await mixin.permfa_poll_click(_guild(), TIER_ID, POLL_ID, 1, PollResponse.YES)
        assert (await _load(mixin)).recipients[1].responded_at == NOW

    async def test_updated_dm_shows_current_answer(self, clock):
        mixin = _mixin()
        await _store(mixin, _poll())
        result = await mixin.permfa_poll_click(_guild(), TIER_ID, POLL_ID, 1, PollResponse.NO)
        field = next(f for f in result.embed.fields if f.name == "Your current answer")
        assert "**No**" in field.value


# --- Button adapter ---


def _button_interaction(cog, guild):
    client = MagicMock()
    client.get_cog.return_value = cog
    client.get_guild.return_value = guild

    interaction = MagicMock(spec=discord.Interaction)
    interaction.client = client
    interaction.user = MagicMock()
    interaction.user.id = 1
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


class TestButton:
    def _button(self, yes=True):
        return PermFAPollButton(guild_id=GUILD_ID, tier_id=TIER_ID, poll_id=POLL_ID, yes=yes)

    async def test_defers_before_any_work(self):
        order = []
        cog = MagicMock()

        async def click(*args, **kwargs):
            order.append("click")
            return PollClickResult(embed=discord.Embed(), keep_buttons=True)

        cog.permfa_poll_click = click
        interaction = _button_interaction(cog, _guild())
        interaction.response.defer.side_effect = lambda *a, **k: order.append("defer")

        await self._button().callback(interaction)

        assert order == ["defer", "click"]

    async def test_missing_cog_asks_to_retry(self):
        interaction = _button_interaction(None, _guild())
        await self._button().callback(interaction)
        interaction.followup.send.assert_awaited_once()
        interaction.edit_original_response.assert_not_awaited()

    async def test_keeps_buttons_so_the_answer_can_change(self):
        cog = MagicMock()
        embed = discord.Embed(title="updated")
        cog.permfa_poll_click = AsyncMock(return_value=PollClickResult(embed=embed, keep_buttons=True))
        interaction = _button_interaction(cog, _guild())

        await self._button(yes=False).callback(interaction)

        assert cog.permfa_poll_click.call_args.kwargs["response"] == PollResponse.NO
        interaction.edit_original_response.assert_awaited_once_with(embed=embed)

    async def test_final_outcome_strips_buttons(self):
        cog = MagicMock()
        embed = discord.Embed(title="closed")
        cog.permfa_poll_click = AsyncMock(return_value=PollClickResult(embed=embed, keep_buttons=False))
        interaction = _button_interaction(cog, _guild())

        await self._button().callback(interaction)

        interaction.edit_original_response.assert_awaited_once_with(embed=embed, view=None)

    async def test_unexpected_exception_is_caught_and_surfaced(self):
        cog = MagicMock()
        cog.permfa_poll_click = AsyncMock(side_effect=RuntimeError("boom"))
        interaction = _button_interaction(cog, _guild())

        await self._button().callback(interaction)

        interaction.followup.send.assert_awaited_once()
        assert interaction.followup.send.call_args.kwargs["ephemeral"] is True

    async def test_end_to_end_click_through_the_real_mixin(self, clock):
        guild = _guild()
        mixin = _mixin(guild)
        await _store(mixin, _poll())
        interaction = _button_interaction(mixin, guild)

        await self._button().callback(interaction)

        assert (await _load(mixin)).recipients[1].response == PollResponse.YES
        assert "view" not in interaction.edit_original_response.call_args.kwargs


# --- Delivery callback ---


class TestRecordDelivery:
    async def test_sent_while_open_stores_the_message(self, clock):
        mixin = _mixin()
        await _store(mixin, _poll(recipients={1: PollRecipient(name="Alpha")}))
        message = _message()

        await mixin._permfa_poll_on_result(_guild(), TIER_ID, POLL_ID, 1)(DMOutcome.SENT, message)

        recipient = (await _load(mixin)).recipients[1]
        assert recipient.delivery == PollDelivery.SENT
        assert recipient.messages == [[500, 600]]
        message.edit.assert_not_awaited()

    async def test_failed_reminder_does_not_hide_a_delivered_dm(self, clock):
        mixin = _mixin()
        await _store(mixin, _poll())
        await mixin._record_permfa_poll_delivery(_guild(), TIER_ID, POLL_ID, 1, DMOutcome.FAILED, None)
        assert (await _load(mixin)).recipients[1].delivery == PollDelivery.SENT

    async def test_failed_first_dm_is_recorded(self, clock):
        mixin = _mixin()
        await _store(mixin, _poll(recipients={1: PollRecipient(name="Alpha")}))
        await mixin._record_permfa_poll_delivery(_guild(), TIER_ID, POLL_ID, 1, DMOutcome.FAILED, None)
        assert (await _load(mixin)).recipients[1].delivery == PollDelivery.FAILED

    async def test_skip_only_marks_undelivered_recipients(self, clock):
        mixin = _mixin()
        await _store(mixin, _poll(recipients={1: PollRecipient(name="Alpha"), 2: PollRecipient(name="Bravo", delivery=PollDelivery.SENT)}))
        await mixin._record_permfa_poll_delivery(_guild(), TIER_ID, POLL_ID, 1, DMOutcome.SKIPPED, None)
        await mixin._record_permfa_poll_delivery(_guild(), TIER_ID, POLL_ID, 2, DMOutcome.SKIPPED, None)
        poll = await _load(mixin)
        assert poll.recipients[1].delivery == PollDelivery.SKIPPED
        assert poll.recipients[2].delivery == PollDelivery.SENT

    async def test_sent_after_close_is_closed_immediately(self, clock):
        """The sweep may already have copied its refs, so this one would keep live buttons."""
        mixin = _mixin()
        await _store(mixin, _poll(closed_at=NOW + 1))
        clock["now"] = NOW + 2
        message = _message()

        await mixin._record_permfa_poll_delivery(_guild(), TIER_ID, POLL_ID, 1, DMOutcome.SENT, message)

        assert (await _load(mixin)).recipients[1].messages == []
        message.edit.assert_awaited_once()
        assert message.edit.call_args.kwargs["view"] is None

    async def test_sent_for_a_replaced_poll_is_closed_immediately(self, clock):
        mixin = _mixin()
        await _store(mixin, _poll(poll_id=POLL_ID + 1))
        message = _message()

        await mixin._record_permfa_poll_delivery(_guild(), TIER_ID, POLL_ID, 1, DMOutcome.SENT, message)

        message.edit.assert_awaited_once()
        assert "no longer active" in message.edit.call_args.kwargs["embed"].description


# --- Send-time precheck ---


class TestPrecheck:
    async def test_open_poll_sends(self, clock):
        mixin = _mixin()
        await _store(mixin, _poll())
        assert await mixin._permfa_poll_precheck(GUILD_ID, TIER_ID, POLL_ID)()

    async def test_closed_poll_does_not_send(self, clock):
        mixin = _mixin()
        await _store(mixin, _poll(closed_at=NOW))
        assert not await mixin._permfa_poll_precheck(GUILD_ID, TIER_ID, POLL_ID)()

    async def test_replaced_poll_does_not_send(self, clock):
        mixin = _mixin()
        await _store(mixin, _poll(poll_id=POLL_ID + 1))
        assert not await mixin._permfa_poll_precheck(GUILD_ID, TIER_ID, POLL_ID)()

    async def test_reminder_dropped_once_the_player_answers(self, clock):
        mixin = _mixin()
        poll = _poll()
        poll.recipients[1].response = PollResponse.NO
        await _store(mixin, poll)
        assert not await mixin._permfa_poll_precheck(GUILD_ID, TIER_ID, POLL_ID, unanswered_by=1)()
        assert await mixin._permfa_poll_precheck(GUILD_ID, TIER_ID, POLL_ID, unanswered_by=2)()


# --- Close sweep ---


class TestSweep:
    async def test_still_open_returns_remaining_time_and_edits_nothing(self, clock):
        mixin = _mixin(_guild())
        await _store(mixin, _poll())
        clock["now"] = EXPIRES - 30

        assert await mixin._sweep_permfa_poll(GUILD_ID, TIER_ID) == 30
        mixin.bot.get_partial_messageable.assert_not_called()

    async def test_expiry_edits_every_dm_and_marks_cleaned(self, clock):
        mixin = _mixin(_guild())
        poll = _poll()
        poll.recipients[1].messages = [[11, 101], [11, 102]]
        poll.recipients[2].messages = [[22, 201]]
        await _store(mixin, poll)
        partial_message = MagicMock()
        partial_message.edit = AsyncMock()
        mixin.bot.get_partial_messageable.return_value.get_partial_message.return_value = partial_message
        clock["now"] = EXPIRES + 100

        assert await mixin._sweep_permfa_poll(GUILD_ID, TIER_ID) is None

        assert partial_message.edit.await_count == 3
        assert all(c.kwargs["view"] is None for c in partial_message.edit.call_args_list)
        stored = await _load(mixin)
        # Natural expiry closes at the deadline, not when the sweep noticed
        assert stored.closed_at == EXPIRES
        assert stored.dms_cleaned is True
        assert all(r.messages == [] for r in stored.recipients.values())

    async def test_edit_failure_does_not_block_cleanup(self, clock):
        mixin = _mixin(_guild())
        poll = _poll(closed_at=NOW + 1)
        poll.recipients[1].messages = [[11, 101]]
        await _store(mixin, poll)
        partial_message = MagicMock()
        partial_message.edit = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "server error"))
        mixin.bot.get_partial_messageable.return_value.get_partial_message.return_value = partial_message
        clock["now"] = NOW + 2

        await mixin._sweep_permfa_poll(GUILD_ID, TIER_ID)

        stored = await _load(mixin)
        assert stored.dms_cleaned is True
        assert stored.recipients[1].messages == []

    async def test_results_posted_once(self, clock):
        mixin = _mixin(_guild())
        channel = MagicMock()
        channel.send = AsyncMock()
        mixin._get_permfa_announce_channel = AsyncMock(return_value=channel)
        await _store(mixin, _poll(closed_at=NOW + 1))
        clock["now"] = NOW + 2

        await mixin._sweep_permfa_poll(GUILD_ID, TIER_ID)
        sent = channel.send.await_count
        await mixin._sweep_permfa_poll(GUILD_ID, TIER_ID)

        assert sent >= 1
        assert channel.send.await_count == sent
        assert (await _load(mixin)).results_posted is True


# --- Timers ---


class TestTimers:
    async def test_arming_skips_a_live_timer(self):
        mixin = _mixin()
        mixin._sweep_permfa_poll = AsyncMock(return_value=None)
        mixin._arm_permfa_poll_timer(GUILD_ID, TIER_ID, 1000)
        first = mixin._permfa_poll_timers[(GUILD_ID, TIER_ID)]

        mixin._arm_permfa_poll_timer(GUILD_ID, TIER_ID, 0)

        assert mixin._permfa_poll_timers[(GUILD_ID, TIER_ID)] is first
        mixin.cancel_permfa_poll_timers()

    async def test_replace_cancels_and_sweeps_now(self):
        mixin = _mixin()
        mixin._sweep_permfa_poll = AsyncMock(return_value=None)
        mixin._arm_permfa_poll_timer(GUILD_ID, TIER_ID, 1000)
        first = mixin._permfa_poll_timers[(GUILD_ID, TIER_ID)]

        mixin._arm_permfa_poll_timer(GUILD_ID, TIER_ID, 0, replace=True)
        second = mixin._permfa_poll_timers[(GUILD_ID, TIER_ID)]
        await asyncio.wait_for(second, timeout=1)
        await asyncio.sleep(0)

        assert first.cancelled()
        mixin._sweep_permfa_poll.assert_awaited_once_with(GUILD_ID, TIER_ID)
        # The done callback cleaned up its own entry
        assert (GUILD_ID, TIER_ID) not in mixin._permfa_poll_timers

    async def test_stale_done_callback_leaves_the_new_timer(self):
        mixin = _mixin()
        mixin._sweep_permfa_poll = AsyncMock(return_value=None)
        mixin._arm_permfa_poll_timer(GUILD_ID, TIER_ID, 1000)
        mixin._arm_permfa_poll_timer(GUILD_ID, TIER_ID, 1000, replace=True)
        second = mixin._permfa_poll_timers[(GUILD_ID, TIER_ID)]
        # Let the cancelled first timer's done callback run
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert mixin._permfa_poll_timers[(GUILD_ID, TIER_ID)] is second
        mixin.cancel_permfa_poll_timers()

    async def test_early_wake_sleeps_the_remainder(self):
        mixin = _mixin()
        mixin._sweep_permfa_poll = AsyncMock(side_effect=[0.0, None])
        await mixin._permfa_poll_timer(GUILD_ID, TIER_ID, 0)
        assert mixin._sweep_permfa_poll.await_count == 2

    async def test_cancel_stops_every_timer(self):
        mixin = _mixin()
        mixin._sweep_permfa_poll = AsyncMock(return_value=None)
        mixin._arm_permfa_poll_timer(GUILD_ID, 1, 1000)
        mixin._arm_permfa_poll_timer(GUILD_ID, 2, 1000)
        tasks = list(mixin._permfa_poll_timers.values())

        mixin.cancel_permfa_poll_timers()
        await asyncio.sleep(0)

        assert all(t.cancelled() for t in tasks)
        assert mixin._permfa_poll_timers == {}

    async def test_setup_rearms_only_polls_that_need_cleaning(self, clock):
        mixin = _mixin()
        await mixin._save_permfa_poll(GUILD_ID, _poll(tier_id=1))
        await mixin._save_permfa_poll(GUILD_ID, _poll(tier_id=2, closed_at=NOW - 10))
        await mixin._save_permfa_poll(GUILD_ID, _poll(tier_id=3, closed_at=NOW - 10, dms_cleaned=True))
        mixin._arm_permfa_poll_timer = MagicMock()
        clock["now"] = NOW + 100

        await mixin.setup_permfa_poll_timers(_guild())

        calls = {c.args[1]: c.args[2] for c in mixin._arm_permfa_poll_timer.call_args_list}
        assert calls == {1: EXPIRES - (NOW + 100), 2: 0}


# --- Results ---


class TestResults:
    def test_groups_and_first_come_order(self, clock):
        poll = _poll(
            recipients={
                1: PollRecipient(name="Late", mmr=1500, delivery=PollDelivery.SENT, response="yes", responded_at=NOW + 50),
                2: PollRecipient(name="Early", mmr=1400, delivery=PollDelivery.SENT, response="yes", responded_at=NOW + 10),
                3: PollRecipient(name="Nope", delivery=PollDelivery.SENT, response="no", responded_at=NOW + 5),
                4: PollRecipient(name="Quiet", delivery=PollDelivery.SENT),
                5: PollRecipient(name="Closed", delivery=PollDelivery.FAILED),
                6: PollRecipient(name="Queued"),
            }
        )
        embeds = _mixin()._permfa_poll_results_embeds(poll)
        fields = {f.name: f.value for e in embeds for f in e.fields}

        yes = next(v for k, v in fields.items() if k.startswith("\N{WHITE HEAVY CHECK MARK}"))
        assert yes.index("Early") < yes.index("Late")
        assert yes.startswith("1. <@2>")
        assert "1400 MMR" in yes
        assert any("No (1)" in k for k in fields)
        assert any("No Response (1)" in k for k in fields)
        undelivered = next(v for k, v in fields.items() if "Not Delivered (2)" in k)
        assert "DM failed" in undelivered
        assert "not sent" in undelivered
        assert "**Open**" in embeds[0].description

    def test_large_tier_splits_across_embeds_within_limits(self, clock):
        recipients = {
            uid: PollRecipient(name=f"Player With A Long Name {uid}", mmr=1000 + uid, delivery=PollDelivery.SENT) for uid in range(1, 301)
        }
        embeds = _mixin()._permfa_poll_results_embeds(_poll(recipients=recipients))

        assert len(embeds) > 1
        for embed in embeds:
            assert len(embed) <= EmbedLimits.Total
            assert len(embed.fields) <= EmbedLimits.Fields
            assert all(len(f.value or "") <= EmbedLimits.Field.Value for f in embed.fields)
        text = "\n".join(f.value or "" for e in embeds for f in e.fields)
        assert all(f"Player With A Long Name {uid} ·" in text for uid in recipients)

    def test_pack_lines_never_splits_a_line(self):
        lines = [f"line {i} " + "x" * 90 for i in range(40)]
        chunks = AdminPermFAPollMixIn._pack_lines(lines)
        assert all(len(c) <= EmbedLimits.Field.Value for c in chunks)
        assert "\n".join(chunks).split("\n") == lines


# --- Commands ---


def _command_interaction(guild):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.id = POLL_ID
    interaction.user = MagicMock()
    interaction.user.id = ADMIN_ID
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    return interaction


def _league_player(discord_id, name, mmr=1500, lp_id=1):
    lp = MagicMock()
    lp.id = lp_id
    lp.player.discord_id = discord_id
    lp.player.name = name
    lp.current_mmr = mmr
    return lp


def _member(member_id):
    member = MagicMock(spec=discord.Member)
    member.id = member_id
    member.mention = f"<@{member_id}>"
    member.display_name = f"member{member_id}"
    return member


class FakeConfirm:
    """Stands in for DMConfirmView. `before_result` runs while the prompt is open."""

    result = True
    before_result = None

    def __init__(self, *args, **kwargs):
        pass

    async def prompt(self):
        pass

    async def wait(self):
        if FakeConfirm.before_result:
            await FakeConfirm.before_result()


@pytest.fixture
def confirm():
    FakeConfirm.result = True
    FakeConfirm.before_result = None
    with patch("rsc.admin.permfa_poll.DMConfirmView", FakeConfirm):
        yield FakeConfirm


def _poll_mixin(guild, players, found, left=(), failed=()):
    mixin = _mixin(guild)
    mixin.is_valid_tier = AsyncMock(return_value=True)
    mixin.tier_id_by_name = AsyncMock(return_value=TIER_ID)
    season = MagicMock()
    season.number = 24
    mixin.current_season = AsyncMock(return_value=season)

    async def paged_players(guild, **kwargs):
        for p in players:
            yield p

    mixin.paged_players = MagicMock(side_effect=paged_players)
    mixin._resolve_members_by_id = AsyncMock(return_value=(list(found), list(left), list(failed)))
    mixin._arm_permfa_poll_timer = MagicMock()
    return mixin


class TestPollCommand:
    async def test_invalid_tier(self, clock, confirm):
        guild = _guild()
        mixin = _poll_mixin(guild, [], [])
        mixin.is_valid_tier.return_value = False
        interaction = _command_interaction(guild)

        await AdminPermFAPollMixIn._permfa_poll_cmd.callback(mixin, interaction, tier="nope")

        assert "not a valid tier" in interaction.followup.send.call_args.kwargs["embed"].description
        mixin._dm_helper.enqueue.assert_not_awaited()

    async def test_refuses_while_a_poll_is_open(self, clock, confirm):
        guild = _guild()
        mixin = _poll_mixin(guild, [_league_player(1, "Alpha")], [_member(1)])
        await _store(mixin, _poll(poll_id=POLL_ID - 1))
        interaction = _command_interaction(guild)

        await AdminPermFAPollMixIn._permfa_poll_cmd.callback(mixin, interaction, tier="elite")

        assert "already open" in interaction.followup.send.call_args.kwargs["embed"].description
        mixin._dm_helper.enqueue.assert_not_awaited()

    async def test_queues_one_dm_per_reachable_permfa(self, clock, confirm):
        guild = _guild()
        players = [_league_player(1, "Alpha", 1500), _league_player(2, "Bravo", 1400), _league_player(None, "NoDiscord", lp_id=9)]
        mixin = _poll_mixin(guild, players, found=[_member(1)], left=[2])
        interaction = _command_interaction(guild)

        await AdminPermFAPollMixIn._permfa_poll_cmd.callback(mixin, interaction, tier="elite")

        # Only PermFAs are polled, from the requested tier
        assert mixin.paged_players.call_args.kwargs == {"status": "PF", "tier_name": "Elite"}
        poll = await _load(mixin)
        assert poll.poll_id == POLL_ID
        assert poll.expires_at == EXPIRES
        assert list(poll.recipients) == [1]
        assert poll.recipients[1].mmr == 1500
        assert poll.recipients[1].delivery == PollDelivery.QUEUED

        mixin._dm_helper.enqueue.assert_awaited_once()
        kwargs = mixin._dm_helper.enqueue.call_args.kwargs
        assert callable(kwargs["precheck"])
        assert callable(kwargs["on_result"])
        assert all(str(POLL_ID) in child.item.custom_id for child in kwargs["view"].children)
        mixin._arm_permfa_poll_timer.assert_called_once_with(GUILD_ID, TIER_ID, EXPIRES - NOW, replace=True)

    async def test_declined_confirm_stores_nothing(self, clock, confirm):
        confirm.result = False
        guild = _guild()
        mixin = _poll_mixin(guild, [_league_player(1, "Alpha")], [_member(1)])

        await AdminPermFAPollMixIn._permfa_poll_cmd.callback(mixin, _command_interaction(guild), tier="elite")

        assert await mixin._get_permfa_poll(GUILD_ID, TIER_ID) is None
        mixin._dm_helper.enqueue.assert_not_awaited()

    async def test_second_admin_confirming_concurrently_is_blocked(self, clock, confirm):
        guild = _guild()
        mixin = _poll_mixin(guild, [_league_player(1, "Alpha")], [_member(1)])

        async def other_admin_starts_a_poll():
            await _store(mixin, _poll(poll_id=POLL_ID - 1))

        confirm.before_result = other_admin_starts_a_poll
        interaction = _command_interaction(guild)

        await AdminPermFAPollMixIn._permfa_poll_cmd.callback(mixin, interaction, tier="elite")

        assert (await _load(mixin)).poll_id == POLL_ID - 1
        mixin._dm_helper.enqueue.assert_not_awaited()
        assert interaction.edit_original_response.call_args.kwargs["view"] is None


class TestRemindCommand:
    async def test_only_unanswered_players_are_reminded(self, clock, confirm):
        guild = _guild()
        mixin = _mixin(guild)
        poll = _poll()
        poll.recipients[1].response = PollResponse.YES
        await _store(mixin, poll)
        mixin._resolve_members_by_id = AsyncMock(return_value=([_member(2)], [], []))

        await AdminPermFAPollMixIn._permfa_remind_cmd.callback(mixin, _command_interaction(guild), tier="elite")

        mixin._resolve_members_by_id.assert_awaited_once_with(guild, [2])
        mixin._dm_helper.enqueue.assert_awaited_once()
        assert mixin._dm_helper.enqueue.call_args.kwargs["embed"].title.startswith("Reminder:")
        assert (await _load(mixin)).last_remind_at == NOW

    async def test_closed_poll_cannot_be_reminded(self, clock, confirm):
        guild = _guild()
        mixin = _mixin(guild)
        await _store(mixin, _poll(closed_at=NOW))
        interaction = _command_interaction(guild)

        await AdminPermFAPollMixIn._permfa_remind_cmd.callback(mixin, interaction, tier="elite")

        assert "no open" in interaction.followup.send.call_args.kwargs["embed"].description
        mixin._dm_helper.enqueue.assert_not_awaited()


class TestCloseCommand:
    async def test_closes_and_sweeps_immediately(self, clock):
        guild = _guild()
        mixin = _mixin(guild)
        mixin._arm_permfa_poll_timer = MagicMock()
        await _store(mixin, _poll())
        clock["now"] = NOW + 30

        await AdminPermFAPollMixIn._permfa_close_cmd.callback(mixin, _command_interaction(guild), tier="Elite")

        stored = await _load(mixin)
        assert stored.closed_at == NOW + 30
        assert stored.closed_by == ADMIN_ID
        mixin._arm_permfa_poll_timer.assert_called_once_with(GUILD_ID, TIER_ID, 0, replace=True)

    async def test_already_closed_poll_is_an_error(self, clock):
        guild = _guild()
        mixin = _mixin(guild)
        mixin._arm_permfa_poll_timer = MagicMock()
        await _store(mixin, _poll(closed_at=NOW))
        interaction = _command_interaction(guild)

        await AdminPermFAPollMixIn._permfa_close_cmd.callback(mixin, interaction, tier="elite")

        assert "no open" in interaction.followup.send.call_args.kwargs["embed"].description
        mixin._arm_permfa_poll_timer.assert_not_called()


class TestResponsesCommand:
    async def test_no_poll(self, clock):
        guild = _guild()
        interaction = _command_interaction(guild)
        await AdminPermFAPollMixIn._permfa_responses_cmd.callback(_mixin(guild), interaction, tier="elite")
        assert "no PermFA conversion poll" in interaction.followup.send.call_args.kwargs["embed"].description

    async def test_sends_each_embed_as_its_own_followup(self, clock):
        guild = _guild()
        mixin = _mixin(guild)
        await _store(mixin, _poll())
        interaction = _command_interaction(guild)

        await AdminPermFAPollMixIn._permfa_responses_cmd.callback(mixin, interaction, tier="elite")

        for call in interaction.followup.send.call_args_list:
            assert "embeds" not in call.kwargs
            assert call.kwargs["ephemeral"] is True


# --- dmtest preview ---


def _preview_message(mixin):
    """A DM as `dmtest` sends it, for the preview click to update."""
    preview = _poll(poll_id=PREVIEW_POLL_ID, tier_id=PREVIEW_POLL_ID, recipients={})
    message = MagicMock(spec=discord.Message)
    message.embeds = [mixin._permfa_poll_dm_embed(_guild(), preview, PollRecipient(name="Admin"))]
    return message


class TestPreviewClick:
    def test_adds_current_answer_and_keeps_buttons(self, clock):
        mixin = _mixin()
        result = mixin.permfa_poll_preview_click(_preview_message(mixin), PollResponse.YES)

        assert result.keep_buttons is True
        answers = [f for f in result.embed.fields if f.name == CURRENT_ANSWER_FIELD]
        assert len(answers) == 1
        assert "**Yes**" in answers[0].value
        # Nothing is ever stored for a preview
        assert mixin.config.store == {}

    def test_changing_the_answer_replaces_the_field(self, clock):
        mixin = _mixin()
        message = _preview_message(mixin)
        message.embeds = [mixin.permfa_poll_preview_click(message, PollResponse.YES).embed]

        result = mixin.permfa_poll_preview_click(message, PollResponse.NO)

        answers = [f for f in result.embed.fields if f.name == CURRENT_ANSWER_FIELD]
        assert len(answers) == 1
        assert "**No**" in answers[0].value

    def test_missing_message_still_answers(self, clock):
        result = _mixin().permfa_poll_preview_click(None, PollResponse.NO)
        assert result.keep_buttons is True

    async def test_button_routes_preview_without_a_guild_or_poll(self, clock):
        mixin = _mixin()
        mixin.permfa_poll_click = AsyncMock()
        interaction = _button_interaction(mixin, None)
        interaction.message = _preview_message(mixin)
        button = PermFAPollButton(guild_id=GUILD_ID, tier_id=PREVIEW_POLL_ID, poll_id=PREVIEW_POLL_ID, yes=False)

        await button.callback(interaction)

        mixin.permfa_poll_click.assert_not_awaited()
        interaction.followup.send.assert_not_awaited()
        kwargs = interaction.edit_original_response.call_args.kwargs
        assert "view" not in kwargs
        assert any(f.name == CURRENT_ANSWER_FIELD and "**No**" in f.value for f in kwargs["embed"].fields)


class TestDmTestCommand:
    def _mixin(self, guild):
        mixin = _mixin(guild)
        mixin.is_valid_tier = AsyncMock(return_value=True)
        season = MagicMock()
        season.number = 24
        mixin.current_season = AsyncMock(return_value=season)
        return mixin

    def _interaction(self, guild):
        interaction = _command_interaction(guild)
        interaction.user.display_name = "Admin"
        interaction.user.send = AsyncMock()
        return interaction

    @pytest.mark.parametrize("reminder", [False, True])
    async def test_sends_preview_dm_with_preview_buttons(self, clock, reminder):
        guild = _guild()
        mixin = self._mixin(guild)
        interaction = self._interaction(guild)

        await AdminPermFAPollMixIn._permfa_dm_test_cmd.callback(mixin, interaction, tier="elite", reminder=reminder)

        kwargs = interaction.user.send.call_args.kwargs
        embed = kwargs["embed"]
        assert "Elite" in embed.title
        assert embed.title.startswith("Reminder:") is reminder
        assert "Season 24" in embed.description
        assert "not recorded" in embed.footer.text
        ids = [child.item.custom_id for child in kwargs["view"].children]
        assert ids == [f"pfa_poll:{GUILD_ID}:0:0:yes", f"pfa_poll:{GUILD_ID}:0:0:no"]
        assert mixin.config.store == {}

    async def test_season_lookup_failure_is_not_fatal(self, clock):
        guild = _guild()
        mixin = self._mixin(guild)
        mixin.current_season.side_effect = RscException(message="down")
        interaction = self._interaction(guild)

        await AdminPermFAPollMixIn._permfa_dm_test_cmd.callback(mixin, interaction, tier="elite")

        assert "the current season" in interaction.user.send.call_args.kwargs["embed"].description

    async def test_invalid_tier(self, clock):
        guild = _guild()
        mixin = self._mixin(guild)
        mixin.is_valid_tier.return_value = False
        interaction = self._interaction(guild)

        await AdminPermFAPollMixIn._permfa_dm_test_cmd.callback(mixin, interaction, tier="nope")

        interaction.user.send.assert_not_awaited()

    async def test_closed_dms_are_reported(self, clock):
        guild = _guild()
        mixin = self._mixin(guild)
        interaction = self._interaction(guild)
        interaction.user.send.side_effect = discord.Forbidden(MagicMock(), "Cannot DM")

        await AdminPermFAPollMixIn._permfa_dm_test_cmd.callback(mixin, interaction, tier="elite")

        assert "Unable to DM you" in interaction.followup.send.call_args.kwargs["embed"].description
