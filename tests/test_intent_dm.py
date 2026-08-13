import asyncio
import logging
from functools import partial
from unittest.mock import AsyncMock, MagicMock, create_autospec

import discord
import pytest

from rsc.admin.admin import MEMBER_FETCH_LIMIT, AdminMixIn
from rsc.admin.intents import AdminIntentsMixIn
from rsc.admin.views import INTENT_DM_TEMPLATE, IntentDMButton, build_intent_dm_view, modmail_reference
from rsc.core import RSC
from rsc.exceptions import RscException

# Called unbound with a stub `self`; the mixin needs a full cog to instantiate.
resolve_missing_members = AdminIntentsMixIn._resolve_missing_members

TEMPLATE = IntentDMButton.__discord_ui_compiled_template__

GUILD_ID = 395806681994493955
SEASON = 24
LEAGUE_ID = 1
MODMAIL_ID = 1489437974008565840


def _mock_season(number=SEASON, season_id=100):
    season = MagicMock()
    season.number = number
    season.id = season_id
    return season


def _rsc_exception(*, exc_type=None, status=None, reason=None):
    exc = RscException(message=reason or "boom")
    exc.type = exc_type
    exc.status = status
    exc.reason = reason
    return exc


def _autospec_cog():
    """A cog stub whose method signatures track the real ones.

    Autospec rather than a bare MagicMock so that renaming a parameter or adding a
    required one on `declare_intent`/`next_signup_season`/`player_intents` fails
    these tests instead of passing while production breaks.
    """
    return create_autospec(RSC, instance=True)


def _mock_cog(*, configured=True, season=None, season_exc=None, declare_exc=None):
    cog = _autospec_cog()
    cog._get_modmail_bot.return_value = MODMAIL_ID
    cog._api_conf = {GUILD_ID: MagicMock()} if configured else {}
    cog._league = {GUILD_ID: LEAGUE_ID} if configured else {}
    cog.next_signup_season.return_value = season
    cog.next_signup_season.side_effect = season_exc
    cog.declare_intent.return_value = MagicMock()
    cog.declare_intent.side_effect = declare_exc
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


class TestIntentDMTemplate:
    """The template is what keeps old season buttons alive.

    Dispatch uses `fullmatch`, so anchoring matters - a pattern that matched
    loosely would hijack unrelated components, and one that matched too
    strictly would leave players with a dead button.
    """

    @pytest.mark.parametrize("returning", ["yes", "no"])
    def test_matches_well_formed_custom_id(self, returning):
        match = TEMPLATE.fullmatch(f"intent_dm:{GUILD_ID}:{SEASON}:{returning}")
        assert match is not None
        assert match["guild"] == str(GUILD_ID)
        assert match["season"] == str(SEASON)
        assert match["returning"] == returning

    @pytest.mark.parametrize(
        "custom_id",
        [
            "intent_dm:395806681994493955:24:maybe",  # bad returning value
            "intent_dm:395806681994493955:24",  # missing returning
            "intent_dm:395806681994493955:yes",  # missing season
            "intent_dm::24:yes",  # empty guild
            "intent_dm:abc:24:yes",  # non numeric guild
            "intent_dm:395806681994493955:24:yes:extra",  # trailing junk
            "xintent_dm:395806681994493955:24:yes",  # leading junk
            "inactive_check_view:green",  # another component entirely
            "confirmed",  # generic button custom_id
        ],
    )
    def test_rejects_malformed_custom_id(self, custom_id):
        assert TEMPLATE.fullmatch(custom_id) is None

    def test_template_constant_matches_compiled_pattern(self):
        assert TEMPLATE.pattern == INTENT_DM_TEMPLATE


class TestIntentDMButton:
    @pytest.mark.parametrize(
        ("returning", "suffix", "style"),
        [
            (True, "yes", discord.ButtonStyle.green),
            (False, "no", discord.ButtonStyle.red),
        ],
    )
    def test_custom_id_and_style(self, returning, suffix, style):
        button = IntentDMButton(guild_id=GUILD_ID, season=SEASON, returning=returning)
        assert button.custom_id == f"intent_dm:{GUILD_ID}:{SEASON}:{suffix}"
        assert button.item.style is style

    def test_generated_custom_id_round_trips_through_template(self):
        """What we send must be what dispatch can parse back out."""
        button = IntentDMButton(guild_id=GUILD_ID, season=SEASON, returning=True)
        match = TEMPLATE.fullmatch(button.custom_id)
        assert match is not None
        assert int(match["guild"]) == GUILD_ID
        assert int(match["season"]) == SEASON
        assert (match["returning"] == "yes") is True

    async def test_from_custom_id_parses_all_fields(self):
        match = TEMPLATE.fullmatch(f"intent_dm:{GUILD_ID}:{SEASON}:no")
        button = await IntentDMButton.from_custom_id(None, None, match)  # type: ignore[arg-type]
        assert button.guild_id == GUILD_ID
        assert button.season == SEASON
        assert button.returning is False

    async def test_from_custom_id_does_not_touch_the_interaction(self):
        """It runs inside the 3 second budget, so it must only parse.

        Passing None for interaction and item would blow up if the
        implementation ever started reaching into them.
        """
        match = TEMPLATE.fullmatch(f"intent_dm:{GUILD_ID}:{SEASON}:yes")
        button = await IntentDMButton.from_custom_id(None, None, match)  # type: ignore[arg-type]
        assert button.returning is True


class TestBuildIntentDMView:
    def test_contains_both_buttons(self):
        view = build_intent_dm_view(GUILD_ID, SEASON)
        custom_ids = {item.custom_id for item in view.children}  # type: ignore[attr-defined]
        assert custom_ids == {
            f"intent_dm:{GUILD_ID}:{SEASON}:yes",
            f"intent_dm:{GUILD_ID}:{SEASON}:no",
        }

    def test_view_never_times_out(self):
        """A DM may sit for months before it is clicked."""
        assert build_intent_dm_view(GUILD_ID, SEASON).timeout is None

    def test_seasons_produce_distinct_custom_ids(self):
        """Season is in the ID so a stale click can be told apart from a live one."""
        current = build_intent_dm_view(GUILD_ID, SEASON)
        previous = build_intent_dm_view(GUILD_ID, SEASON - 1)
        assert {i.custom_id for i in current.children}.isdisjoint(  # type: ignore[attr-defined]
            {i.custom_id for i in previous.children}  # type: ignore[attr-defined]
        )

    def test_guilds_produce_distinct_custom_ids(self):
        """Two RSC leagues must not collide on the same custom_id."""
        a = build_intent_dm_view(GUILD_ID, SEASON)
        b = build_intent_dm_view(GUILD_ID + 1, SEASON)
        assert {i.custom_id for i in a.children}.isdisjoint(  # type: ignore[attr-defined]
            {i.custom_id for i in b.children}  # type: ignore[attr-defined]
        )


class TestModmailReference:
    def test_includes_mention_and_link(self):
        ref = modmail_reference(1489437974008565840)
        assert "<@1489437974008565840>" in ref
        assert "https://discord.com/users/1489437974008565840" in ref


def _mock_intent(discord_id):
    intent = MagicMock()
    intent.player.player.discord_id = discord_id
    return intent


def _mock_resolve_guild(cached=(), chunked=True):
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.name = "RSC 3v3"
    guild.chunked = chunked
    guild.chunk = AsyncMock()
    cache = {pid: MagicMock(spec=discord.Member) for pid in cached}
    guild.get_member = MagicMock(side_effect=cache.get)
    guild.fetch_member = AsyncMock()
    return guild


def _stub_cog(intents):
    cog = _autospec_cog()
    cog.player_intents.return_value = intents
    # Resolution lives on AdminMixIn now and `_resolve_missing_members` only
    # extracts ids and delegates. Bind the real implementation so these tests
    # still exercise the cache/fetch logic rather than an autospec stub.
    cog._resolve_members_by_id = partial(AdminMixIn._resolve_members_by_id, cog)
    # Chunking lives in its own helper now. Bind it too, otherwise the autospec stub
    # swallows the call and the cache/fetch assertions below test nothing.
    cog._ensure_chunked = partial(AdminMixIn._ensure_chunked, cog)
    return cog


class TestResolveMissingMembers:
    """A cache miss must never silently drop a player who should be DMed."""

    async def test_cache_hits_avoid_http(self):
        guild = _mock_resolve_guild(cached=[1, 2, 3])
        cog = _stub_cog([_mock_intent(1), _mock_intent(2), _mock_intent(3)])

        to_dm, left, failed = await resolve_missing_members(cog, guild, 100)

        assert len(to_dm) == 3
        assert (left, failed) == ([], [])
        guild.fetch_member.assert_not_awaited()

    async def test_cache_miss_falls_back_to_fetch(self):
        guild = _mock_resolve_guild(cached=[1])
        fetched = MagicMock(spec=discord.Member)
        guild.fetch_member = AsyncMock(return_value=fetched)
        cog = _stub_cog([_mock_intent(1), _mock_intent(2)])

        to_dm, left, failed = await resolve_missing_members(cog, guild, 100)

        assert len(to_dm) == 2
        assert fetched in to_dm
        guild.fetch_member.assert_awaited_once_with(2)
        assert (left, failed) == ([], [])

    async def test_not_found_means_left_the_guild(self):
        guild = _mock_resolve_guild()
        guild.fetch_member = AsyncMock(side_effect=discord.NotFound(MagicMock(), "gone"))
        cog = _stub_cog([_mock_intent(7)])

        to_dm, left, failed = await resolve_missing_members(cog, guild, 100)

        assert to_dm == []
        assert left == [7]
        assert failed == []

    async def test_http_error_means_lookup_failed(self):
        guild = _mock_resolve_guild()
        guild.fetch_member = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "boom"))
        cog = _stub_cog([_mock_intent(7)])

        to_dm, left, failed = await resolve_missing_members(cog, guild, 100)

        assert to_dm == []
        assert left == []
        assert failed == [7]

    async def test_chunks_a_cold_cache_before_falling_back(self):
        guild = _mock_resolve_guild(chunked=False)
        guild.fetch_member = AsyncMock(side_effect=discord.NotFound(MagicMock(), "gone"))
        cog = _stub_cog([_mock_intent(1)])

        await resolve_missing_members(cog, guild, 100)

        guild.chunk.assert_awaited_once()

    async def test_does_not_chunk_when_already_chunked(self):
        guild = _mock_resolve_guild(cached=[1], chunked=True)
        cog = _stub_cog([_mock_intent(1)])

        await resolve_missing_members(cog, guild, 100)

        guild.chunk.assert_not_awaited()

    async def test_chunk_failure_is_not_fatal(self):
        """Without the members intent, chunk() raises - fall through to fetch."""
        guild = _mock_resolve_guild(chunked=False)
        guild.chunk = AsyncMock(side_effect=discord.ClientException("no members intent"))
        fetched = MagicMock(spec=discord.Member)
        guild.fetch_member = AsyncMock(return_value=fetched)
        cog = _stub_cog([_mock_intent(1)])

        to_dm, _, _ = await resolve_missing_members(cog, guild, 100)

        assert to_dm == [fetched]

    async def test_fetch_fallback_is_capped_and_overflow_is_reported(self):
        """Excess misses become lookup failures rather than hundreds of HTTP calls."""
        overflow = 5
        total = MEMBER_FETCH_LIMIT + overflow
        guild = _mock_resolve_guild()
        guild.fetch_member = AsyncMock(return_value=MagicMock(spec=discord.Member))
        # Ids start at 1; a falsy id is treated as absent (snowflakes are never 0)
        cog = _stub_cog([_mock_intent(i) for i in range(1, total + 1)])

        to_dm, left, failed = await resolve_missing_members(cog, guild, 100)

        assert guild.fetch_member.await_count == MEMBER_FETCH_LIMIT
        assert len(to_dm) == MEMBER_FETCH_LIMIT
        assert len(failed) == overflow  # surfaced, not silently dropped
        assert left == []

    async def test_skips_intents_without_a_player(self):
        no_player = MagicMock()
        no_player.player = None
        guild = _mock_resolve_guild(cached=[1])
        cog = _stub_cog([no_player, _mock_intent(1)])

        to_dm, left, failed = await resolve_missing_members(cog, guild, 100)

        assert len(to_dm) == 1
        assert (left, failed) == ([], [])

    async def test_skips_intents_without_a_discord_id(self):
        guild = _mock_resolve_guild(cached=[1])
        cog = _stub_cog([_mock_intent(None), _mock_intent(1)])

        to_dm, left, failed = await resolve_missing_members(cog, guild, 100)

        assert len(to_dm) == 1
        guild.fetch_member.assert_not_awaited()

    async def test_requests_only_missing_intents(self):
        guild = _mock_resolve_guild(cached=[1])
        cog = _stub_cog([_mock_intent(1)])

        await resolve_missing_members(cog, guild, 100)

        assert cog.player_intents.await_args.kwargs["missing"] is True
        assert cog.player_intents.await_args.kwargs["season_id"] == 100

    async def test_chunk_timeout_falls_through_to_fetch(self, monkeypatch):
        """`guild.chunk()` has no timeout of its own and can hang forever."""
        monkeypatch.setattr("rsc.admin.admin.CHUNK_TIMEOUT", 0.01)

        async def never_returns(*args, **kwargs):
            await asyncio.sleep(30)

        guild = _mock_resolve_guild(chunked=False)
        guild.chunk = AsyncMock(side_effect=never_returns)
        fetched = MagicMock(spec=discord.Member)
        guild.fetch_member = AsyncMock(return_value=fetched)
        cog = _stub_cog([_mock_intent(1)])

        to_dm, _, _ = await asyncio.wait_for(resolve_missing_members(cog, guild, 100), timeout=5)

        assert to_dm == [fetched]

    async def test_no_overflow_warning_when_cap_hit_exactly(self, caplog):
        """Hitting the cap with nothing left over degraded nothing."""
        guild = _mock_resolve_guild()
        guild.fetch_member = AsyncMock(return_value=MagicMock(spec=discord.Member))
        cog = _stub_cog([_mock_intent(i) for i in range(1, MEMBER_FETCH_LIMIT + 1)])

        with caplog.at_level(logging.WARNING, logger="red.rsc.admin.intents"):
            await resolve_missing_members(cog, guild, 100)

        assert "fetch limit" not in caplog.text

    async def test_overflow_warning_when_players_are_dropped(self, caplog):
        guild = _mock_resolve_guild()
        guild.fetch_member = AsyncMock(return_value=MagicMock(spec=discord.Member))
        cog = _stub_cog([_mock_intent(i) for i in range(1, MEMBER_FETCH_LIMIT + 4)])

        with caplog.at_level(logging.WARNING, logger="red.rsc.admin.intents"):
            await resolve_missing_members(cog, guild, 100)

        assert "fetch limit" in caplog.text


class TestCogStubFidelity:
    """Guard the guard: the stub must reject calls the real method would."""

    def test_stub_rejects_a_call_the_real_signature_forbids(self):
        cog = _mock_cog(season=_mock_season())
        with pytest.raises(TypeError):
            cog.declare_intent(guild=object(), not_a_real_parameter=1)

    def test_stub_accepts_the_production_call_shape(self):
        cog = _mock_cog(season=_mock_season())
        cog.declare_intent(guild=object(), member=1, returning=True).close()


class TestCallbackDefersFirst:
    async def test_defer_happens_before_any_api_work(self):
        """The 3 second response deadline is the binding one, not the 15 minute token.

        If the API call were awaited before the deferral, a slow API would blow the
        window and the click would be lost.
        """
        order: list[str] = []

        async def record_api(*args, **kwargs):
            order.append("api")
            return _mock_season()

        async def record_defer(*args, **kwargs):
            order.append("defer")

        cog = _mock_cog(season=_mock_season())
        cog.next_signup_season.side_effect = record_api
        interaction = _mock_interaction(cog)
        interaction.response.defer = AsyncMock(side_effect=record_defer)

        await IntentDMButton(GUILD_ID, SEASON, returning=True).callback(interaction)

        assert order == ["defer", "api"]


class TestCallbackGuards:
    """Regression coverage for the silent-dead-button failure mode.

    discord.py swallows exceptions from a dynamic item callback, and a type 6
    deferral leaves the message untouched, so anything escaping here would look
    to the player like a click that did nothing at all.
    """

    async def test_unconfigured_guild_does_not_call_the_api(self):
        cog = _mock_cog(configured=False)
        interaction = _mock_interaction(cog)

        await IntentDMButton(GUILD_ID, SEASON, returning=True).callback(interaction)

        cog.next_signup_season.assert_not_awaited()
        cog.declare_intent.assert_not_awaited()
        interaction.followup.send.assert_awaited_once()
        assert "Something Went Wrong" in _retry_embed(interaction).title

    async def test_missing_guild_is_handled(self):
        cog = _mock_cog(season=_mock_season())
        interaction = _mock_interaction(cog, guild=False)

        await IntentDMButton(GUILD_ID, SEASON, returning=True).callback(interaction)

        cog.declare_intent.assert_not_awaited()
        interaction.followup.send.assert_awaited_once()

    async def test_missing_cog_is_handled(self):
        interaction = _mock_interaction(None)

        await IntentDMButton(GUILD_ID, SEASON, returning=True).callback(interaction)

        interaction.followup.send.assert_awaited_once()

    async def test_unexpected_exception_is_caught_and_surfaced(self):
        """A KeyError from an unguarded dict index must not vanish."""
        cog = _mock_cog(season=_mock_season())
        cog.next_signup_season = AsyncMock(side_effect=KeyError(GUILD_ID))
        interaction = _mock_interaction(cog)

        await IntentDMButton(GUILD_ID, SEASON, returning=True).callback(interaction)

        interaction.followup.send.assert_awaited_once()
        embed = _retry_embed(interaction)
        assert embed.colour == discord.Colour.red()
        assert str(MODMAIL_ID) in embed.description

    async def test_player_error_falls_back_to_default_modmail(self):
        """The catch-all can fire before the guild's ModMail bot is resolved."""
        cog = _mock_cog(season=_mock_season())
        cog._get_modmail_bot = AsyncMock(side_effect=RuntimeError("config unavailable"))
        interaction = _mock_interaction(cog)

        await IntentDMButton(GUILD_ID, SEASON, returning=True).callback(interaction)

        assert str(MODMAIL_ID) in _retry_embed(interaction).description


class TestCallbackSignupWindow:
    async def test_signups_closed_records_nothing_and_points_at_modmail(self):
        cog = _mock_cog(season_exc=_rsc_exception(exc_type="SignupsClosedException"))
        interaction = _mock_interaction(cog)

        await IntentDMButton(GUILD_ID, SEASON, returning=True).callback(interaction)

        cog.declare_intent.assert_not_awaited()
        embed = _final_embed(interaction)
        assert embed.colour == discord.Colour.orange()
        assert "Signups Are Closed" in embed.title
        assert str(MODMAIL_ID) in embed.description

    async def test_no_signup_season_records_nothing(self):
        cog = _mock_cog(season=None)
        interaction = _mock_interaction(cog)

        await IntentDMButton(GUILD_ID, SEASON, returning=True).callback(interaction)

        cog.declare_intent.assert_not_awaited()
        assert _final_embed(interaction).colour == discord.Colour.orange()

    async def test_stale_season_records_nothing_and_points_at_signup(self):
        """Clicking last season's DM must not silently declare for this season."""
        cog = _mock_cog(season=_mock_season(number=SEASON + 1))
        interaction = _mock_interaction(cog)

        await IntentDMButton(GUILD_ID, SEASON, returning=True).callback(interaction)

        cog.declare_intent.assert_not_awaited()
        embed = _final_embed(interaction)
        assert embed.colour == discord.Colour.yellow()
        assert f"Season {SEASON}" in embed.description
        assert f"Season {SEASON + 1}" in embed.description
        assert "/signup" in embed.description

    async def test_other_api_error_keeps_buttons_for_retry(self):
        cog = _mock_cog(season_exc=_rsc_exception(status=500, reason="boom"))
        interaction = _mock_interaction(cog)

        await IntentDMButton(GUILD_ID, SEASON, returning=True).callback(interaction)

        cog.declare_intent.assert_not_awaited()
        # followup, not edit - the buttons must survive so the player can retry
        interaction.followup.send.assert_awaited_once()
        interaction.edit_original_response.assert_not_awaited()


class TestCallbackDeclare:
    @pytest.mark.parametrize(
        ("returning", "colour", "expected"),
        [
            (True, discord.Colour.green(), "RETURNING"),
            (False, discord.Colour.red(), "NOT RETURNING"),
        ],
    )
    async def test_successful_declaration(self, returning, colour, expected):
        cog = _mock_cog(season=_mock_season())
        interaction = _mock_interaction(cog)

        await IntentDMButton(GUILD_ID, SEASON, returning=returning).callback(interaction)

        cog.declare_intent.assert_awaited_once()
        assert cog.declare_intent.await_args.kwargs["returning"] is returning
        # DMs give a discord.User, so the raw id is what gets passed through
        assert cog.declare_intent.await_args.kwargs["member"] == interaction.user.id

        embed = _final_embed(interaction)
        assert embed.colour == colour
        assert expected in embed.description
        # Terminal outcome strips the buttons from that one message
        assert interaction.edit_original_response.call_args.kwargs["view"] is None

    async def test_already_declared_conflict_is_friendly(self):
        cog = _mock_cog(
            season=_mock_season(),
            declare_exc=_rsc_exception(status=409, reason="Already declared."),
        )
        interaction = _mock_interaction(cog)

        await IntentDMButton(GUILD_ID, SEASON, returning=True).callback(interaction)

        embed = _final_embed(interaction)
        assert embed.colour == discord.Colour.yellow()
        assert "Already declared." in embed.description

    async def test_late_failure_does_not_claim_the_intent_was_lost(self):
        """API succeeded, reply failed. Telling them to retry would earn a 409."""
        cog = _mock_cog(season=_mock_season())
        interaction = _mock_interaction(cog)
        interaction.edit_original_response = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "boom"))

        button = IntentDMButton(GUILD_ID, SEASON, returning=True)
        await button.callback(interaction)

        assert button.declared is True
        description = _retry_embed(interaction).description.lower()
        assert "recorded" in description
        assert "try the buttons again" not in description

    async def test_failure_before_declaring_still_tells_them_to_retry(self):
        cog = _mock_cog(season=_mock_season())
        cog.next_signup_season.side_effect = KeyError(GUILD_ID)
        interaction = _mock_interaction(cog)

        button = IntentDMButton(GUILD_ID, SEASON, returning=True)
        await button.callback(interaction)

        assert button.declared is False
        assert "try the buttons again" in _retry_embed(interaction).description.lower()

    async def test_declare_failure_keeps_buttons_and_hides_internals(self):
        cog = _mock_cog(
            season=_mock_season(),
            declare_exc=_rsc_exception(status=503, reason="upstream exploded"),
        )
        interaction = _mock_interaction(cog)

        await IntentDMButton(GUILD_ID, SEASON, returning=True).callback(interaction)

        interaction.edit_original_response.assert_not_awaited()
        embed = _retry_embed(interaction)
        # Players should not see raw API failure text
        assert "upstream exploded" not in (embed.description or "")
        assert str(MODMAIL_ID) in embed.description
