"""Tests for the activity check DM buttons.

The channel-side `InactiveCheckView` cannot serve DMs: it is registered per
message id and guards on `isinstance(interaction.user, discord.Member)`, which
is False in a DM. `ActivityCheckDMButton` is the dynamic-item port that can.
"""

from unittest.mock import AsyncMock, MagicMock, create_autospec

import discord
import pytest

from rsc.admin.views import (
    ACTIVITY_DM_TEMPLATE,
    ActivityCheckDMButton,
    build_activity_check_dm_view,
)
from rsc.core import RSC
from rsc.exceptions import RscException

TEMPLATE = ActivityCheckDMButton.__discord_ui_compiled_template__

GUILD_ID = 395806681994493955
SEASON = 27
SEASON_ID = 100
LEAGUE_ID = 1
MSG_ID = 987654321
MODMAIL_ID = 1489437974008565840


def _rsc_exception(*, exc_type=None, status=None, reason=None):
    exc = RscException(message=reason or "boom")
    exc.type = exc_type
    exc.status = status
    exc.reason = reason
    return exc


def _mock_season(number=SEASON, season_id=SEASON_ID):
    season = MagicMock()
    season.id = season_id
    season.number = number
    return season


def _mock_check(completed=False):
    check = MagicMock()
    check.completed = completed
    check.missing = True
    return check


def _mock_cog(
    *,
    configured=True,
    msg_id=MSG_ID,
    season=None,
    season_exc=None,
    submit_exc=None,
    still_missing=None,
):
    """A cog stub whose method signatures track the real ones.

    Autospec rather than a bare MagicMock so that renaming a parameter or adding
    a required one on `activity_check`/`current_season`/`season_activity_checks`
    fails these tests instead of passing while production breaks.
    """
    cog = create_autospec(RSC, instance=True)
    cog._get_modmail_bot.return_value = MODMAIL_ID
    cog._api_conf = {GUILD_ID: MagicMock()} if configured else {}
    cog._league = {GUILD_ID: LEAGUE_ID} if configured else {}
    cog._get_activity_check_msg_id.return_value = msg_id
    cog.current_season.return_value = season if season is not None else _mock_season()
    cog.current_season.side_effect = season_exc
    cog.activity_check.return_value = MagicMock()
    cog.activity_check.side_effect = submit_exc
    # Drives the duplicate-submission probe on the error path.
    cog.season_activity_checks.return_value = [_mock_check()] if still_missing else []
    return cog


def _mock_interaction(cog, *, guild=True, user_id=555):
    guild_obj = None
    if guild:
        guild_obj = MagicMock(spec=discord.Guild)
        guild_obj.id = GUILD_ID
        guild_obj.name = "RSC 3v3"

    client = MagicMock()
    client.get_cog.return_value = cog
    client.get_guild.return_value = guild_obj

    interaction = MagicMock(spec=discord.Interaction)
    interaction.client = client
    interaction.user = MagicMock()
    interaction.user.id = user_id
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _final_embed(interaction) -> discord.Embed:
    """The embed from the terminal `edit_original_response` call."""
    return interaction.edit_original_response.call_args.kwargs["embed"]


def _retry_embed(interaction) -> discord.Embed:
    """The embed from the non-terminal `followup.send` call."""
    return interaction.followup.send.call_args.kwargs["embed"]


class TestActivityDMTemplate:
    """Dispatch uses `fullmatch`, so anchoring matters. A loose pattern would
    hijack unrelated components; a strict one leaves players a dead button."""

    @pytest.mark.parametrize("active", ["yes", "no"])
    def test_matches_well_formed_custom_id(self, active):
        match = TEMPLATE.fullmatch(f"activity_dm:{GUILD_ID}:{SEASON}:{active}")
        assert match is not None
        assert match["guild"] == str(GUILD_ID)
        assert match["season"] == str(SEASON)
        assert match["active"] == active

    @pytest.mark.parametrize(
        "custom_id",
        [
            "activity_dm:395806681994493955:27:maybe",  # bad active value
            "activity_dm:395806681994493955:27",  # missing active
            "activity_dm:395806681994493955:yes",  # missing season
            "activity_dm::27:yes",  # empty guild
            "activity_dm:abc:27:yes",  # non numeric guild
            "activity_dm:395806681994493955:27:yes:extra",  # trailing junk
            "xactivity_dm:395806681994493955:27:yes",  # leading junk
            "intent_dm:395806681994493955:27:yes",  # the sibling DM button
            "inactive_check_view:green",  # the channel view
            "confirmed",  # generic button custom_id
        ],
    )
    def test_rejects_malformed_custom_id(self, custom_id):
        assert TEMPLATE.fullmatch(custom_id) is None

    def test_template_constant_matches_compiled_pattern(self):
        assert TEMPLATE.pattern == ACTIVITY_DM_TEMPLATE

    def test_does_not_hijack_intent_buttons(self):
        """Both templates are registered globally; neither may swallow the other."""
        from rsc.admin.views import IntentDMButton

        intent_template = IntentDMButton.__discord_ui_compiled_template__
        assert intent_template.fullmatch(f"activity_dm:{GUILD_ID}:{SEASON}:yes") is None
        assert TEMPLATE.fullmatch(f"intent_dm:{GUILD_ID}:{SEASON}:yes") is None


class TestActivityDMButton:
    @pytest.mark.parametrize(
        ("active", "suffix", "style"),
        [
            (True, "yes", discord.ButtonStyle.green),
            (False, "no", discord.ButtonStyle.red),
        ],
    )
    def test_custom_id_and_style(self, active, suffix, style):
        button = ActivityCheckDMButton(guild_id=GUILD_ID, season=SEASON, active=active)
        assert button.custom_id == f"activity_dm:{GUILD_ID}:{SEASON}:{suffix}"
        assert button.item.style is style

    @pytest.mark.parametrize("active", [True, False])
    async def test_custom_id_round_trip(self, active):
        original = ActivityCheckDMButton(guild_id=GUILD_ID, season=SEASON, active=active)
        match = TEMPLATE.fullmatch(original.custom_id)
        rebuilt = await ActivityCheckDMButton.from_custom_id(MagicMock(), MagicMock(), match)

        assert (rebuilt.guild_id, rebuilt.season, rebuilt.active) == (GUILD_ID, SEASON, active)

    def test_view_has_both_buttons(self):
        view = build_activity_check_dm_view(GUILD_ID, SEASON)
        ids = {item.custom_id for item in view.children}

        assert ids == {
            f"activity_dm:{GUILD_ID}:{SEASON}:yes",
            f"activity_dm:{GUILD_ID}:{SEASON}:no",
        }
        assert view.timeout is None


class TestCallbackDefersFirst:
    async def test_defer_precedes_api_work(self):
        """Every branch hits the API, which can blow the 3 second deadline."""
        cog = _mock_cog()
        interaction = _mock_interaction(cog)

        await ActivityCheckDMButton(GUILD_ID, SEASON, True).callback(interaction)

        interaction.response.defer.assert_awaited_once()

    async def test_unhandled_error_still_replies(self, caplog):
        """discord.py swallows exceptions out of a dynamic item callback, so a
        click that errors would otherwise look like it silently did nothing."""
        cog = _mock_cog()
        cog._get_modmail_bot.side_effect = RuntimeError("boom")
        interaction = _mock_interaction(cog)

        await ActivityCheckDMButton(GUILD_ID, SEASON, True).callback(interaction)

        assert _retry_embed(interaction).title == "Something Went Wrong"


class TestCallbackGuards:
    async def test_unresolvable_guild_is_retryable(self):
        cog = _mock_cog()
        interaction = _mock_interaction(cog, guild=False)

        await ActivityCheckDMButton(GUILD_ID, SEASON, True).callback(interaction)

        assert _retry_embed(interaction).title == "Something Went Wrong"
        cog.activity_check.assert_not_awaited()

    async def test_unconfigured_guild_is_retryable(self):
        """The API wrappers index `_api_conf`/`_league` directly, so an
        unconfigured guild raises KeyError rather than RscException."""
        cog = _mock_cog(configured=False)
        interaction = _mock_interaction(cog)

        await ActivityCheckDMButton(GUILD_ID, SEASON, True).callback(interaction)

        assert _retry_embed(interaction).title == "Something Went Wrong"
        cog.activity_check.assert_not_awaited()

    async def test_ended_check_is_terminal(self):
        """A stopped check clears the stored message id. That, not the season in
        the custom_id, decides whether submissions are still accepted."""
        cog = _mock_cog(msg_id=None)
        interaction = _mock_interaction(cog)

        await ActivityCheckDMButton(GUILD_ID, SEASON, True).callback(interaction)

        assert _final_embed(interaction).title == "Activity Check Has Ended"
        assert interaction.edit_original_response.call_args.kwargs["view"] is None
        cog.activity_check.assert_not_awaited()

    async def test_stale_season_is_terminal(self):
        cog = _mock_cog(season=_mock_season(number=SEASON + 1))
        interaction = _mock_interaction(cog)

        await ActivityCheckDMButton(GUILD_ID, SEASON, True).callback(interaction)

        embed = _final_embed(interaction)
        assert embed.title == "This Message Is Out Of Date"
        assert f"Season {SEASON}" in embed.description
        assert f"Season {SEASON + 1}" in embed.description
        cog.activity_check.assert_not_awaited()

    async def test_season_lookup_failure_is_retryable(self):
        cog = _mock_cog(season_exc=_rsc_exception(status=500, reason="boom"))
        interaction = _mock_interaction(cog)

        await ActivityCheckDMButton(GUILD_ID, SEASON, True).callback(interaction)

        assert _retry_embed(interaction).title == "Something Went Wrong"
        cog.activity_check.assert_not_awaited()


class TestCallbackSubmit:
    @pytest.mark.parametrize(
        ("active", "title", "marker"),
        [
            (True, "Marked Active", "**active**"),
            (False, "Marked In-Active", "**inactive**"),
        ],
    )
    async def test_success_is_terminal(self, active, title, marker):
        cog = _mock_cog()
        interaction = _mock_interaction(cog)

        await ActivityCheckDMButton(GUILD_ID, SEASON, active).callback(interaction)

        embed = _final_embed(interaction)
        assert embed.title == title
        assert marker in embed.description
        assert interaction.edit_original_response.call_args.kwargs["view"] is None

    async def test_submits_raw_user_id_not_member(self):
        """`interaction.user` is a `discord.User` in a DM, so the API call must
        take an id. Passing the object would break on `.id` access downstream."""
        cog = _mock_cog()
        interaction = _mock_interaction(cog, user_id=4242)

        await ActivityCheckDMButton(GUILD_ID, SEASON, True).callback(interaction)

        assert cog.activity_check.call_args.args[1] == 4242
        assert cog.activity_check.call_args.kwargs["returning_status"] is True

    async def test_duplicate_submission_is_terminal(self):
        """This endpoint has no 409, so a duplicate cannot be told from a real
        failure by status code. An empty missing-check probe means already done."""
        cog = _mock_cog(submit_exc=_rsc_exception(status=400, reason="bad"), still_missing=False)
        interaction = _mock_interaction(cog)

        await ActivityCheckDMButton(GUILD_ID, SEASON, True).callback(interaction)

        embed = _final_embed(interaction)
        assert embed.title == "Activity Check"
        assert "already completed" in embed.description
        interaction.followup.send.assert_not_awaited()

    async def test_genuine_failure_is_retryable(self):
        cog = _mock_cog(submit_exc=_rsc_exception(status=400, reason="bad"), still_missing=True)
        interaction = _mock_interaction(cog)

        await ActivityCheckDMButton(GUILD_ID, SEASON, True).callback(interaction)

        assert _retry_embed(interaction).title == "Something Went Wrong"

    async def test_probe_failure_fails_open_to_retry(self):
        """A failed probe must not be reported as 'already completed'."""
        cog = _mock_cog(submit_exc=_rsc_exception(status=400, reason="bad"))
        cog.season_activity_checks.side_effect = _rsc_exception(status=500, reason="down")
        interaction = _mock_interaction(cog)

        await ActivityCheckDMButton(GUILD_ID, SEASON, True).callback(interaction)

        assert _retry_embed(interaction).title == "Something Went Wrong"

    async def test_late_failure_does_not_tell_player_to_retry(self):
        """The submission landed but the reply did not. Telling them to click
        again would just churn the API for an already-recorded check."""
        cog = _mock_cog()
        interaction = _mock_interaction(cog)
        interaction.edit_original_response.side_effect = RuntimeError("edit failed")

        await ActivityCheckDMButton(GUILD_ID, SEASON, True).callback(interaction)

        embed = _retry_embed(interaction)
        assert embed.title == "Activity Check Recorded"
        assert "No further action is needed" in embed.description
