"""Startup path: cache preparation, guild isolation, and client lifetime."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from aiohttp.test_utils import TestClient, TestServer
from rscapi.rest import ALLOW_RETRY_METHODS
from aiohttp import (
    ClientConnectorError,
    ClientOSError,
    ServerDisconnectedError,
    ServerTimeoutError,
)

from rsc.admin.views import ActivityCheckDMButton, IntentDMButton, PermFAPollButton
from rsc.combines.guide import ReplayLocationButton
from rsc.combines.runner import CombinesLeague
from rsc.core import RSC
from rsc.devleague.runner import DevLeague
from rsc.lobbies.runner import LobbyRunner
from rsc.members.views import PlayerInfoButton, PlayerTrackersButton
from rsc.tiers.tiers import TierMixIn


def _create_cog(**attrs):
    """Create an RSC instance bypassing ABC restrictions and __init__."""
    saved = RSC.__abstractmethods__
    RSC.__abstractmethods__ = frozenset()
    try:
        cog = object.__new__(RSC)
    finally:
        RSC.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(cog, k, v)
    return cog


def _create_tier_mixin(**attrs):
    saved = TierMixIn.__abstractmethods__
    TierMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(TierMixIn)
    finally:
        TierMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _make_guild(guild_id: int, name: str = "Guild"):
    guild = MagicMock()
    guild.id = guild_id
    guild.name = name
    return guild


# --- api_client lifetime ---


class TestApiClientReuse:
    async def test_reuses_same_client_across_calls(self, mock_guild):
        mixin = _create_tier_mixin(_api_conf={mock_guild.id: MagicMock()}, _api_clients={})

        with patch("rsc.abc.ApiClient") as mock_cls:
            async with mixin.api_client(mock_guild) as first:
                pass
            async with mixin.api_client(mock_guild) as second:
                pass

        assert first is second
        # The whole point: one construction, therefore one aiohttp session.
        assert mock_cls.call_count == 1

    async def test_does_not_close_client_on_exit(self, mock_guild):
        mixin = _create_tier_mixin(_api_conf={mock_guild.id: MagicMock()}, _api_clients={})

        with patch("rsc.abc.ApiClient") as mock_cls:
            mock_cls.return_value = AsyncMock()
            async with mixin.api_client(mock_guild) as client:
                pass

        client.close.assert_not_awaited()

    async def test_separate_client_per_guild(self):
        g1, g2 = _make_guild(1), _make_guild(2)
        mixin = _create_tier_mixin(
            _api_conf={g1.id: MagicMock(), g2.id: MagicMock()},
            _api_clients={},
        )

        with patch("rsc.abc.ApiClient", side_effect=lambda conf: MagicMock()):
            async with mixin.api_client(g1) as c1:
                pass
            async with mixin.api_client(g2) as c2:
                pass

        assert c1 is not c2

    async def test_lazily_creates_cache_when_init_did_not_run(self, mock_guild):
        """A mixin used standalone never ran RSC.__init__."""
        mixin = _create_tier_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient"):
            async with mixin.api_client(mock_guild):
                pass

        assert mock_guild.id in mixin._api_clients

    async def test_close_api_clients_closes_and_empties(self, mock_guild):
        client = AsyncMock()
        mixin = _create_tier_mixin(_api_clients={mock_guild.id: client})

        await mixin.close_api_clients()

        client.close.assert_awaited_once()
        assert mixin._api_clients == {}


class TestPrepareApiInvalidation:
    async def test_closes_stale_client_when_config_changes(self, mock_guild):
        stale = AsyncMock()
        cog = _create_cog(
            _api_conf={},
            _api_clients={mock_guild.id: stale},
            _get_api_url=AsyncMock(return_value="https://api.example.com"),
            _get_api_key=AsyncMock(return_value="key"),
        )

        await cog.prepare_api(mock_guild)

        # The cached client is bound to the previous Configuration.
        stale.close.assert_awaited_once()
        assert mock_guild.id not in cog._api_clients
        assert mock_guild.id in cog._api_conf

    async def test_unchanged_config_keeps_the_cached_client(self, mock_guild):
        """setup() re-runs on every on_ready(); that must not drop live sessions."""
        cog = _create_cog(
            _api_conf={},
            _api_clients={},
            _get_api_url=AsyncMock(return_value="https://api.example.com"),
            _get_api_key=AsyncMock(return_value="key"),
        )
        await cog.prepare_api(mock_guild)
        conf = cog._api_conf[mock_guild.id]
        client = AsyncMock()
        cog._api_clients[mock_guild.id] = client

        await cog.prepare_api(mock_guild)

        client.close.assert_not_awaited()
        assert cog._api_clients[mock_guild.id] is client
        assert cog._api_conf[mock_guild.id] is conf

    @pytest.mark.parametrize(
        ("url", "key"),
        [("https://api.example.com", "rotated"), ("https://other.example.com", "key")],
    )
    async def test_changed_key_or_url_replaces_the_client(self, mock_guild, url, key):
        cog = _create_cog(
            _api_conf={},
            _api_clients={},
            _get_api_url=AsyncMock(return_value="https://api.example.com"),
            _get_api_key=AsyncMock(return_value="key"),
        )
        await cog.prepare_api(mock_guild)
        conf = cog._api_conf[mock_guild.id]
        client = AsyncMock()
        cog._api_clients[mock_guild.id] = client
        cog._get_api_url = AsyncMock(return_value=url)
        cog._get_api_key = AsyncMock(return_value=key)

        await cog.prepare_api(mock_guild)

        client.close.assert_awaited_once()
        assert mock_guild.id not in cog._api_clients
        assert cog._api_conf[mock_guild.id] is not conf

    async def test_retries_cover_stale_pooled_sockets(self, mock_guild):
        """Long lived clients can hand out a socket the server already closed.

        aiohttp_retry re-raises any exception not named in `exceptions`, so a
        bare int for `retries` would retry 5xx responses but not this.
        """
        cog = _create_cog(
            _api_conf={},
            _api_clients={},
            _get_api_url=AsyncMock(return_value="https://api.example.com"),
            _get_api_key=AsyncMock(return_value="key"),
        )

        await cog.prepare_api(mock_guild)
        retries = cog._api_conf[mock_guild.id].retries

        assert retries.attempts == 3
        assert ServerDisconnectedError in retries.exceptions
        assert ClientOSError in retries.exceptions
        # A refused connection arrives as a ClientOSError subclass.
        assert any(issubclass(ClientConnectorError, exc) for exc in retries.exceptions)
        # Retrying a timeout would multiply API_TIMEOUT by the attempt count.
        assert not any(issubclass(ServerTimeoutError, exc) for exc in retries.exceptions)
        # 5xx responses stay covered by the built in flag.
        assert retries.retry_all_server_errors is True

    async def test_post_is_never_retried(self):
        """Transactions must not be replayed, whatever the retry config says."""
        assert "POST" not in ALLOW_RETRY_METHODS

    async def test_no_config_written_when_unconfigured(self, mock_guild):
        cog = _create_cog(
            _api_conf={},
            _api_clients={},
            _get_api_url=AsyncMock(return_value=None),
            _get_api_key=AsyncMock(return_value=None),
        )

        await cog.prepare_api(mock_guild)

        assert cog._api_conf == {}


# --- Per guild setup ---


class TestSetupGuild:
    async def test_skips_api_caches_without_api_config(self, mock_guild):
        cog = _create_cog(
            _api_conf={},
            _league={},
            prepare_api=AsyncMock(),
            prepare_league=AsyncMock(),
            tiers=AsyncMock(),
            franchises=AsyncMock(),
            teams=AsyncMock(),
            _populate_free_agent_cache=AsyncMock(),
            setup_permfa_poll_timers=AsyncMock(),
            prepare_ballchasing=AsyncMock(),
            setup_persistent_activity_check=AsyncMock(),
        )

        await cog._setup_guild(mock_guild)

        cog.prepare_league.assert_not_awaited()
        cog.tiers.assert_not_awaited()
        cog.prepare_ballchasing.assert_not_awaited()

    async def test_populates_fa_cache_without_api_config(self, mock_guild):
        """Config only, and the FA loop's before_loop used to do this for every guild."""
        cog = _create_cog(
            _api_conf={},
            _league={},
            prepare_api=AsyncMock(),
            prepare_league=AsyncMock(),
            _populate_free_agent_cache=AsyncMock(),
            setup_permfa_poll_timers=AsyncMock(),
        )

        await cog._setup_guild(mock_guild)

        cog._populate_free_agent_cache.assert_awaited_once_with(mock_guild)

    async def test_rearms_permfa_poll_timers_without_api_config(self, mock_guild):
        """Config only. A poll that expired while the bot was down must still close."""
        cog = _create_cog(
            _api_conf={},
            _league={},
            prepare_api=AsyncMock(),
            prepare_league=AsyncMock(),
            _populate_free_agent_cache=AsyncMock(),
            setup_permfa_poll_timers=AsyncMock(),
        )

        await cog._setup_guild(mock_guild)

        cog.setup_permfa_poll_timers.assert_awaited_once_with(mock_guild)

    async def test_skips_league_caches_without_league(self, mock_guild):
        """tiers/franchises/teams bare-index _league, so they must not run."""
        cog = _create_cog(
            _api_conf={mock_guild.id: MagicMock()},
            _league={},
            prepare_api=AsyncMock(),
            prepare_league=AsyncMock(),
            tiers=AsyncMock(),
            franchises=AsyncMock(),
            teams=AsyncMock(),
            _populate_free_agent_cache=AsyncMock(),
            setup_permfa_poll_timers=AsyncMock(),
            prepare_ballchasing=AsyncMock(),
            setup_persistent_activity_check=AsyncMock(),
        )

        await cog._setup_guild(mock_guild)

        cog.prepare_league.assert_awaited_once()
        cog.tiers.assert_not_awaited()
        cog.franchises.assert_not_awaited()
        cog.teams.assert_not_awaited()
        cog.setup_persistent_activity_check.assert_not_awaited()
        # These two are league independent and must still run.
        cog._populate_free_agent_cache.assert_awaited_once_with(mock_guild)
        cog.prepare_ballchasing.assert_awaited_once_with(mock_guild)

    async def test_populates_caches_when_configured(self, mock_guild):
        cog = _create_cog(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            prepare_api=AsyncMock(),
            prepare_league=AsyncMock(),
            tiers=AsyncMock(),
            franchises=AsyncMock(),
            teams=AsyncMock(),
            _populate_free_agent_cache=AsyncMock(),
            setup_permfa_poll_timers=AsyncMock(),
            prepare_ballchasing=AsyncMock(),
            setup_persistent_activity_check=AsyncMock(),
        )

        await cog._setup_guild(mock_guild)

        cog.tiers.assert_awaited_once_with(mock_guild)
        cog.franchises.assert_awaited_once_with(mock_guild)
        cog.teams.assert_awaited_once_with(mock_guild)
        cog.prepare_ballchasing.assert_awaited_once_with(mock_guild)

    @pytest.mark.parametrize(
        "exc",
        [
            RuntimeError("boom"),
            KeyError("league"),
            AttributeError("API returned a team with no name."),
        ],
    )
    async def test_swallows_cache_errors(self, mock_guild, exc):
        """RscException in particular used to escape every except* handler."""
        cog = _create_cog(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            prepare_api=AsyncMock(),
            prepare_league=AsyncMock(),
            tiers=AsyncMock(side_effect=exc),
            franchises=AsyncMock(),
            teams=AsyncMock(),
            _populate_free_agent_cache=AsyncMock(),
            setup_permfa_poll_timers=AsyncMock(),
            prepare_ballchasing=AsyncMock(),
            setup_persistent_activity_check=AsyncMock(),
        )

        await cog._setup_guild(mock_guild)


class TestSetupIsolation:
    async def test_one_failing_guild_does_not_block_others(self):
        """Previously an unhandled error unwound the whole `for guild` loop."""
        g1, g2, g3 = _make_guild(1, "First"), _make_guild(2, "Second"), _make_guild(3, "Third")
        prepared = []

        async def fake_setup_guild(guild):
            if guild.id == 2:
                raise RuntimeError("API is down for this guild")
            prepared.append(guild.id)

        bot = MagicMock()
        bot.guilds = [g1, g2, g3]
        cog = _create_cog(
            bot=bot,
            _setup_lock=asyncio.Lock(),
            start_webapp=AsyncMock(),
            prepare_application_emojis=AsyncMock(),
            _setup_guild=fake_setup_guild,
        )

        await cog.setup()

        assert prepared == [1, 3]
        # Every DM button template must register, or clicks on those DMs die
        # silently after a restart.
        bot.add_dynamic_items.assert_called_once_with(
            IntentDMButton, ActivityCheckDMButton, PermFAPollButton, PlayerInfoButton, PlayerTrackersButton, ReplayLocationButton
        )

    async def test_prepares_guilds_concurrently(self):
        """Startup latency should be the slowest guild, not the sum."""
        g1, g2, g3 = _make_guild(1), _make_guild(2), _make_guild(3)
        in_flight = 0
        peak = 0

        async def fake_setup_guild(guild):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0)
            in_flight -= 1

        bot = MagicMock()
        bot.guilds = [g1, g2, g3]
        cog = _create_cog(
            bot=bot,
            _setup_lock=asyncio.Lock(),
            start_webapp=AsyncMock(),
            prepare_application_emojis=AsyncMock(),
            _setup_guild=fake_setup_guild,
        )

        await cog.setup()

        assert peak == 3


class TestCogUnload:
    async def test_removes_dm_button_templates(self):
        """Templates live on the bot, so a reload would otherwise keep the old classes."""
        bot = MagicMock()
        cog = _create_cog(
            bot=bot,
            expire_sub_contract_loop=MagicMock(),
            expire_free_agent_checkins_loop=MagicMock(),
            sync_discord_roles=MagicMock(),
            rsc_events_loop=MagicMock(),
            retire_audit_loop=MagicMock(),
            cancel_permfa_poll_timers=MagicMock(),
            _dm_helper=AsyncMock(),
            close_ballchasing_sessions=AsyncMock(),
            close_api_clients=AsyncMock(),
            _web_runner=None,
        )

        await cog.cog_unload()

        bot.remove_dynamic_items.assert_called_once_with(
            IntentDMButton, ActivityCheckDMButton, PermFAPollButton, PlayerInfoButton, PlayerTrackersButton, ReplayLocationButton
        )


class TestStartWebapp:
    async def test_is_idempotent(self):
        """on_ready re-runs setup() on every reconnect; rebinding orphans the runner."""
        existing = MagicMock()
        cog = _create_cog(_web_runner=existing, _web_site=MagicMock())

        with patch("rsc.core.web") as mock_web:
            await cog.start_webapp()

        mock_web.AppRunner.assert_not_called()
        assert cog._web_runner is existing

    async def test_bind_failure_is_not_fatal(self):
        """A dead webhook listener must not stop the guild caches from loading."""
        cog = _create_cog(_web_runner=None, _web_site=None, _combines_runner=MagicMock(), _devleague_runner=MagicMock())

        runner = AsyncMock()
        site = AsyncMock()
        site.start.side_effect = OSError("address already in use")

        with patch("rsc.core.web") as mock_web:
            mock_web.AppRunner.return_value = runner
            mock_web.TCPSite.return_value = site
            await cog.start_webapp()

        runner.cleanup.assert_awaited_once()
        assert cog._web_runner is None

    async def test_registers_lobby_routes_on_each_systems_runner(self):
        combines, devleague = MagicMock(), MagicMock()
        cog = _create_cog(_web_runner=None, _web_site=None, _combines_runner=combines, _devleague_runner=devleague)

        with patch("rsc.core.web") as mock_web:
            mock_web.AppRunner.return_value = AsyncMock()
            mock_web.TCPSite.return_value = AsyncMock()
            await cog.start_webapp()

        routes = {c.args[0]: c.args[1] for c in mock_web.Application.return_value.router.add_post.call_args_list}
        assert routes["/combines_match"] is combines.start_game
        assert routes["/combines_event"] is combines.handle_event
        assert routes["/devleague_match"] is devleague.start_game
        assert routes["/devleague_event"] is devleague.handle_event

    async def test_lobby_urls_reach_the_right_systems_runner_over_http(self):
        # Combines is on and Dev League is off, so each URL's answer shows whose runner took it
        guild = MagicMock(spec=discord.Guild)
        guild.id = 1
        cog = _create_cog(_web_runner=None, _web_site=None)
        cog.bot = MagicMock()
        cog.bot.get_guild.return_value = guild
        cog._get_combines_active = AsyncMock(return_value=True)
        cog._get_devleague_active = AsyncMock(return_value=False)
        cog._combines_runner = LobbyRunner(cog, CombinesLeague(cog))
        cog._devleague_runner = LobbyRunner(cog, DevLeague(cog))
        cog._combines_runner.create_channels = AsyncMock(return_value=[])
        lobby = {
            "id": 101,
            "lobby_user": "rsc",
            "lobby_pass": "rsc",
            "home_wins": 0,
            "away_wins": 0,
            "reported_rsc_id": None,
            "confirmed_rsc_id": None,
            "completed": False,
            "cancelled": False,
            "tier": "Elite",
            "guild_id": "1",
            "home": [],
            "away": [],
        }

        with patch("rsc.core.web.TCPSite", return_value=AsyncMock()):
            await cog.start_webapp()
        async with TestClient(TestServer(cog._web_app)) as client:
            combines_match = await client.post("/combines_match", json={"101": lobby})
            devleague_match = await client.post("/devleague_match", json={"101": lobby})
            combines_event = await client.post("/combines_event", data="not json")
            devleague_event = await client.post("/devleague_event", data="not json")
        await cog._web_runner.cleanup()
        await asyncio.gather(*cog._combines_runner.background_tasks)

        assert (combines_match.status, devleague_match.status) == (200, 503)
        assert (combines_event.status, devleague_event.status) == (400, 400)


class TestApplicationEmojis:
    """The LIVE dot is cosmetic, so resolving it must never fail setup."""

    def _cog(self, *, existing=(), create=None, fetch_exc=None):
        bot = MagicMock()
        bot.fetch_application_emojis = AsyncMock(return_value=list(existing), side_effect=fetch_exc)
        bot.create_application_emoji = AsyncMock(return_value=create)
        return _create_cog(bot=bot, _live_emoji=None)

    def _emoji(self, name="live"):
        emoji = MagicMock(spec=discord.Emoji)
        emoji.name = name
        emoji.__str__.return_value = f"<a:{name}:123>"
        return emoji

    async def test_uses_existing_emoji(self):
        live = self._emoji()
        cog = self._cog(existing=[self._emoji("other"), live])
        await cog.prepare_application_emojis()
        assert cog._live_emoji is live
        cog.bot.create_application_emoji.assert_not_awaited()
        assert cog.live_emoji() == "<a:live:123>"

    async def test_uploads_when_missing(self):
        created = self._emoji()
        cog = self._cog(create=created)
        await cog.prepare_application_emojis()
        kwargs = cog.bot.create_application_emoji.await_args.kwargs
        assert kwargs["name"] == "live"
        assert kwargs["image"].startswith(b"GIF89a")
        assert cog._live_emoji is created

    async def test_resolves_only_once(self):
        cog = self._cog(existing=[self._emoji()])
        await cog.prepare_application_emojis()
        await cog.prepare_application_emojis()
        cog.bot.fetch_application_emojis.assert_awaited_once()

    @pytest.mark.parametrize(
        "exc",
        [discord.MissingApplicationID(), discord.HTTPException(MagicMock(status=500, reason="Error"), "boom")],
    )
    async def test_failure_falls_back_to_no_emoji(self, exc):
        cog = self._cog(fetch_exc=exc)
        await cog.prepare_application_emojis()
        assert cog._live_emoji is None
        assert cog.live_emoji() == ""
