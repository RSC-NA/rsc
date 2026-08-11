"""Tests for `/accolades masstrophy`.

The command runs over a pasted list of Discord IDs, so any single bad entry --
an ID that isn't in the guild, a nickname that would exceed 32 characters, a
member the bot can't edit -- has to be reported rather than abandoning the rest
of the batch.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rsc import const
from rsc.utils.trophy import TrophyMixIn
from rsc.utils.views.mass_trophy import MassTrophyModal


def _create_mixin(**attrs):
    saved = TrophyMixIn.__abstractmethods__
    TrophyMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(TrophyMixIn)
    finally:
        TrophyMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _make_member(discord_id: int, name: str = "player"):
    member = MagicMock(spec=discord.Member)
    member.id = discord_id
    member.display_name = name
    member.mention = f"<@{discord_id}>"
    member.edit = AsyncMock()
    return member


def _http_exception(status: int, text: str = ""):
    response = MagicMock()
    response.status = status
    exc = discord.HTTPException(response, {"message": text, "code": 0})
    exc.text = text
    return exc


class TestGetMembers:
    @pytest.fixture
    def guild(self):
        guild = MagicMock(spec=discord.Guild)
        guild.get_member = MagicMock(return_value=None)
        guild.fetch_member = AsyncMock()
        return guild

    def _modal(self, value: str) -> MassTrophyModal:
        modal = MassTrophyModal()
        modal.member_input._value = value
        return modal

    async def test_unresolvable_ids_do_not_discard_the_batch(self, guild):
        """The original code raised on the first miss, losing every valid ID."""
        good = _make_member(111)
        guild.get_member = MagicMock(side_effect=lambda i: good if i == 111 else None)
        guild.fetch_member = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "unknown member"))

        members, errors = await self._modal("999\n111\nnotanumber").get_members(guild)

        assert members == [good]
        assert len(errors) == 2
        assert any("999" in e for e in errors)
        assert any("notanumber" in e for e in errors)

    async def test_uncached_member_is_fetched_from_the_api(self, guild):
        """`get_member` is cache only, so a cache miss is not proof of absence."""
        member = _make_member(222)
        guild.fetch_member = AsyncMock(return_value=member)

        members, errors = await self._modal("222").get_members(guild)

        assert members == [member]
        assert errors == []
        guild.fetch_member.assert_awaited_once_with(222)

    async def test_fetch_failure_is_reported_not_raised(self, guild):
        guild.fetch_member = AsyncMock(side_effect=_http_exception(500, "server error"))

        members, errors = await self._modal("333").get_members(guild)

        assert members == []
        assert len(errors) == 1

    async def test_blank_lines_are_ignored(self, guild):
        member = _make_member(444)
        guild.get_member = MagicMock(return_value=member)

        members, errors = await self._modal("444\n\n   \n").get_members(guild)

        assert members == [member]
        assert errors == []

    async def test_empty_submission_raises(self, guild):
        with pytest.raises(ValueError, match="No Discord IDs"):
            await self._modal("   \n\n").get_members(guild)


class TestMassTrophyCommand:
    @pytest.fixture
    def guild(self):
        guild = MagicMock(spec=discord.Guild)
        guild.name = "RSC 3v3"
        return guild

    @pytest.fixture
    def interaction(self, guild):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = guild
        interaction.response = MagicMock()
        interaction.response.send_modal = AsyncMock()
        interaction.response.send_message = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()
        return interaction

    @pytest.fixture
    def modal_interaction(self):
        modal_interaction = MagicMock(spec=discord.Interaction)
        modal_interaction.edit_original_response = AsyncMock()
        return modal_interaction

    def _patch_modal(self, members, errors, modal_interaction):
        modal = MagicMock()
        modal.wait = AsyncMock(return_value=False)
        modal.stop = MagicMock()
        modal.get_members = AsyncMock(return_value=(members, errors))
        modal.interaction = modal_interaction
        return patch("rsc.utils.trophy.MassTrophyModal", return_value=modal)

    def _final_embed(self, modal_interaction):
        return modal_interaction.edit_original_response.await_args.kwargs["embed"]

    async def test_one_failure_does_not_stop_the_rest(self, interaction, modal_interaction):
        """A too-long nickname used to return early, skipping every later member."""
        first, second, third = _make_member(1), _make_member(2), _make_member(3)
        mixin = _create_mixin()
        mixin.format_nickname = AsyncMock(
            side_effect=[
                "one \U0001f3c6",
                ValueError("Discord name is too long (2): ..."),
                "three \U0001f3c6",
            ]
        )

        with self._patch_modal([first, second, third], [], modal_interaction):
            await TrophyMixIn._accolades_mass_trophy_cmd.callback(mixin, interaction, const.TROPHY_EMOJI)

        first.edit.assert_awaited_once()
        third.edit.assert_awaited_once()
        second.edit.assert_not_awaited()

        embed = self._final_embed(modal_interaction)
        assert "**2/3**" in embed.description
        assert embed.fields[0].name == "Errors (1)"
        assert "too long" in embed.fields[0].value

    async def test_forbidden_edit_is_reported_and_batch_continues(self, interaction, modal_interaction):
        blocked, ok = _make_member(1), _make_member(2)
        blocked.edit = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "missing perms"))
        mixin = _create_mixin(format_nickname=AsyncMock(return_value="name \U0001f3c6"))

        with self._patch_modal([blocked, ok], [], modal_interaction):
            await TrophyMixIn._accolades_mass_trophy_cmd.callback(mixin, interaction, const.TROPHY_EMOJI)

        ok.edit.assert_awaited_once()
        embed = self._final_embed(modal_interaction)
        assert "**1/2**" in embed.description
        assert "Missing permission" in embed.fields[0].value

    async def test_http_error_is_reported_and_batch_continues(self, interaction, modal_interaction):
        failed, ok = _make_member(1), _make_member(2)
        failed.edit = AsyncMock(side_effect=_http_exception(429, "rate limited"))
        mixin = _create_mixin(format_nickname=AsyncMock(return_value="name \U0001f3c6"))

        with self._patch_modal([failed, ok], [], modal_interaction):
            await TrophyMixIn._accolades_mass_trophy_cmd.callback(mixin, interaction, const.TROPHY_EMOJI)

        ok.edit.assert_awaited_once()
        embed = self._final_embed(modal_interaction)
        assert "**1/2**" in embed.description
        assert "rate limited" in embed.fields[0].value

    async def test_unresolved_ids_carry_into_the_final_report(self, interaction, modal_interaction):
        """Errors from ID resolution must survive into the summary."""
        member = _make_member(1)
        mixin = _create_mixin(format_nickname=AsyncMock(return_value="name \U0001f3c6"))

        with self._patch_modal([member], ["Member not found in guild: `999`"], modal_interaction):
            await TrophyMixIn._accolades_mass_trophy_cmd.callback(mixin, interaction, const.TROPHY_EMOJI)

        embed = self._final_embed(modal_interaction)
        assert "**1/1**" in embed.description
        assert "999" in embed.fields[0].value

    async def test_all_failures_report_an_error_embed(self, interaction, modal_interaction):
        member = _make_member(1)
        member.edit = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "nope"))
        mixin = _create_mixin(format_nickname=AsyncMock(return_value="name \U0001f3c6"))

        with self._patch_modal([member], [], modal_interaction):
            await TrophyMixIn._accolades_mass_trophy_cmd.callback(mixin, interaction, const.TROPHY_EMOJI)

        embed = self._final_embed(modal_interaction)
        assert embed.title == "Mass Trophy Failed"
        assert "**0/1**" in embed.description

    async def test_progress_is_reported_during_a_long_run(self, interaction, modal_interaction):
        """The operator needs to see the command is alive, not a dead spinner."""
        members = [_make_member(i) for i in range(25)]
        mixin = _create_mixin(format_nickname=AsyncMock(return_value="name \U0001f3c6"))

        with self._patch_modal(members, [], modal_interaction):
            await TrophyMixIn._accolades_mass_trophy_cmd.callback(mixin, interaction, const.TROPHY_EMOJI)

        descriptions = [c.kwargs["embed"].description for c in modal_interaction.edit_original_response.await_args_list]
        assert any("10/25 processed" in d for d in descriptions)
        assert any("20/25 processed" in d for d in descriptions)
        assert "**25/25**" in descriptions[-1]

    async def test_invalid_trophy_is_rejected_before_the_modal(self, interaction):
        """Validating inside the loop aborted a batch that was already half applied."""
        mixin = _create_mixin()

        await TrophyMixIn._accolades_mass_trophy_cmd.callback(mixin, interaction, "not-a-trophy")

        interaction.response.send_modal.assert_not_awaited()
        assert interaction.response.send_message.await_args.kwargs["embed"].title == "Error"

    @pytest.mark.parametrize(
        ("trophy", "field"),
        [
            (const.TROPHY_EMOJI, "trophy"),
            (const.STAR_EMOJI, "star"),
            (const.DEV_LEAGUE_EMOJI, "devleague"),
            (const.COMBINE_CUP_EMOJI, "combine_cup"),
        ],
    )
    async def test_each_trophy_type_increments_its_own_counter(self, interaction, modal_interaction, trophy, field):
        member = _make_member(1)
        mixin = _create_mixin(format_nickname=AsyncMock(return_value="name x"))

        with self._patch_modal([member], [], modal_interaction):
            await TrophyMixIn._accolades_mass_trophy_cmd.callback(mixin, interaction, trophy)

        accolades = mixin.format_nickname.await_args.args[1]
        assert getattr(accolades, field) == 1

    async def test_timed_out_modal_does_not_report(self, interaction, modal_interaction):
        mixin = _create_mixin()
        modal = MagicMock()
        modal.wait = AsyncMock(return_value=True)
        modal.get_members = AsyncMock()

        with patch("rsc.utils.trophy.MassTrophyModal", return_value=modal):
            await TrophyMixIn._accolades_mass_trophy_cmd.callback(mixin, interaction, const.TROPHY_EMOJI)

        modal.get_members.assert_not_awaited()
        interaction.followup.send.assert_not_awaited()

    async def test_overflowing_error_list_is_flagged_not_silently_dropped(self, interaction, modal_interaction):
        members = [_make_member(i) for i in range(150)]
        for m in members:
            m.edit = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "nope"))
        mixin = _create_mixin(format_nickname=AsyncMock(return_value="name x"))

        with self._patch_modal(members, [], modal_interaction):
            await TrophyMixIn._accolades_mass_trophy_cmd.callback(mixin, interaction, const.TROPHY_EMOJI)

        embed = self._final_embed(modal_interaction)
        assert embed.fields[0].name == "Errors (150)"
        assert embed.valid_fields()
        assert embed.footer.text and "full list" in embed.footer.text
