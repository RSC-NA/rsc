"""What Dev League lobbies do differently. The shared runner is tested in test_lobby_runner.py."""

from unittest.mock import AsyncMock, MagicMock

import discord

from rsc.devleague.api import DEVLEAGUE_API_URL
from rsc.devleague.models import DevLeagueLobby
from rsc.devleague.runner import DevLeague

GUILD_ID = 991044575567179856


def _lobby(tier: str = "S+") -> DevLeagueLobby:
    return DevLeagueLobby(
        id=101,
        lobby_user="dl",
        lobby_pass="rsc",
        home_wins=0,
        away_wins=0,
        reported_rsc_id=None,
        confirmed_rsc_id=None,
        completed=False,
        cancelled=False,
        tier=tier,
        guild_id=GUILD_ID,
        home=[],
        away=[],
    )


def _channel(name: str, channel_id: int, position: int = 0) -> MagicMock:
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.name = name
    channel.id = channel_id
    channel.position = position
    return channel


def _guild() -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild._state = MagicMock()
    guild._state.http.bulk_channel_update = AsyncMock()
    return guild


def _category(guild, voice_channels) -> MagicMock:
    category = MagicMock(spec=discord.CategoryChannel)
    category.guild = guild
    category.voice_channels = list(voice_channels)
    return category


def _league() -> DevLeague:
    return DevLeague(MagicMock())


class TestDevLeague:
    def test_channels_use_the_tier_slug(self):
        assert [_league().channel_name(_lobby(), side) for side in ("home", "away")] == ["splus-101-home", "splus-101-away"]

    def test_card_links_to_the_match(self):
        assert _league().match_url(_lobby()) == f"{DEVLEAGUE_API_URL}/match/101"

    def test_cards_are_kept_under_the_dev_league_config_group(self):
        cog = MagicMock()
        assert DevLeague(cog).store(_guild()) is cog.config.custom.return_value
        cog.config.custom.assert_called_once_with("DevLeague", str(GUILD_ID))

    async def test_settings_come_from_the_dev_league_getters(self):
        league = _league()
        category, announce = MagicMock(spec=discord.CategoryChannel), MagicMock(spec=discord.TextChannel)
        league.cog._get_devleague_active = AsyncMock(return_value=True)
        league.cog._get_devleague_category = AsyncMock(return_value=category)
        league.cog._get_devleague_announce_channel = AsyncMock(return_value=announce)

        assert await league.active(_guild()) is True
        assert await league.category(_guild()) is category
        assert await league.announce_channel(_guild()) is announce

    def test_no_extra_overwrites(self):
        assert _league().extra_overwrites(_guild()) == {}


class TestPlaceByTier:
    async def test_inserts_new_lobby_in_tier_order(self):
        guild = _guild()
        existing = [
            _channel("waiting-room", 1, position=0),
            _channel("splus-1-home", 2, position=1),
            _channel("splus-1-away", 3, position=2),
            _channel("c-2-home", 4, position=3),
            _channel("c-2-away", 5, position=4),
        ]
        home, away = _channel("a-3-home", 10, position=5), _channel("a-3-away", 11, position=6)
        # The cache may or may not already hold the new channels.
        await _league().place(_category(guild, [*existing, home]), home, away)

        assert guild._state.http.bulk_channel_update.await_args is not None
        payload = guild._state.http.bulk_channel_update.await_args.args[1]
        assert [p["id"] for p in payload] == [1, 2, 3, 10, 11, 4, 5]
        assert [p["position"] for p in payload] == list(range(7))

    async def test_lowest_tier_goes_last(self):
        guild = _guild()
        existing = [_channel("s-1-home", 1, 0), _channel("s-1-away", 2, 1)]
        home, away = _channel("f-3-home", 10), _channel("f-3-away", 11)

        await _league().place(_category(guild, existing), home, away)

        assert guild._state.http.bulk_channel_update.await_args is not None
        payload = guild._state.http.bulk_channel_update.await_args.args[1]
        assert [p["id"] for p in payload] == [1, 2, 10, 11]
