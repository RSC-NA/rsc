"""What combines lobbies do differently. The shared runner is tested in test_lobby_runner.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rsc import const
from rsc.combines import models
from rsc.combines.lobby import LobbyMessages
from rsc.combines.runner import ANNOUNCE_CHANNEL, CombinesLeague
from rsc.combines.views import LobbyCard, LobbyKind, LobbyScore
from rsc.exceptions import SiteUnavailable

GUILD_ID = 395806681994493964


def _player(discord_id: int, team: str) -> dict:
    return {"discord_id": str(discord_id), "rsc_id": f"RSC{discord_id}", "match_id": 101, "team": team, "name": f"player{discord_id}"}


def _lobby_payload() -> dict:
    return {
        "id": 101,
        "lobby_user": "rsc",
        "lobby_pass": "rsc",
        "home_wins": 0,
        "away_wins": 0,
        "reported_rsc_id": None,
        "confirmed_rsc_id": None,
        "completed": False,
        "cancelled": False,
        "tier": "Premier",
        "guild_id": str(GUILD_ID),
        "home": [_player(i, "home") for i in (1, 2, 3)],
        "away": [_player(i, "away") for i in (4, 5, 6)],
    }


def _named(spec, name: str) -> MagicMock:
    channel = MagicMock(spec=spec)
    channel.name = name
    return channel


def _guild(*, channels=(), roles=()) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.channels = list(channels)
    guild.roles = [_named(discord.Role, r) for r in roles]
    return guild


def _league() -> CombinesLeague:
    return CombinesLeague(MagicMock())


class TestCombinesLeague:
    def test_channels_keep_the_tier_as_sent(self):
        lobby = models.CombinesLobby(**_lobby_payload())
        assert [_league().channel_name(lobby, side) for side in ("home", "away")] == ["Premier-101-home", "Premier-101-away"]

    def test_card_links_to_the_combine(self):
        assert _league().match_url(models.CombinesLobby(**_lobby_payload())) == "https://devleague.rscna.com/combine/101"

    def test_cards_are_kept_under_the_combines_config_group(self):
        cog = MagicMock()
        assert CombinesLeague(cog).store(_guild()) is cog.config.custom.return_value
        cog.config.custom.assert_called_once_with("Combines", str(GUILD_ID))

    async def test_settings_come_from_the_combines_getters(self):
        league = _league()
        category = MagicMock(spec=discord.CategoryChannel)
        league.cog._get_combines_active = AsyncMock(return_value=True)
        league.cog._get_combines_category = AsyncMock(return_value=category)

        assert await league.active(_guild()) is True
        assert await league.category(_guild()) is category

    async def test_announces_in_the_channel_named_for_it(self):
        channel = _named(discord.TextChannel, ANNOUNCE_CHANNEL)
        assert await _league().announce_channel(_guild(channels=[channel])) is channel

    @pytest.mark.parametrize("channels", [[], [_named(discord.VoiceChannel, ANNOUNCE_CHANNEL)]])
    async def test_missing_or_non_text_announcement_channel_is_none(self, channels):
        assert await _league().announce_channel(_guild(channels=channels)) is None

    def test_muted_role_cannot_join(self):
        guild = _guild(roles=[const.LEAGUE_ROLE, const.MUTED_ROLE])
        ((muted, overwrite),) = _league().extra_overwrites(guild).items()
        assert muted is guild.roles[1]
        assert (overwrite.connect, overwrite.speak) == (False, False)

    def test_no_muted_role_adds_nothing(self):
        assert _league().extra_overwrites(_guild(roles=[const.LEAGUE_ROLE])) == {}


def _entry(executor_id: int | None = 1) -> LobbyMessages:
    card = LobbyCard(
        kind=LobbyKind.COMBINE,
        lobby_id=101,
        tier="Premier",
        lobby_name="rsc",
        lobby_pass="rsc",
        home=("<@1>",),
        away=("<@4>",),
        lobby_maker="P1",
        home_vc_url=None,
        away_vc_url=None,
        match_url="https://devleague.rscna.com/combine/101",
        started_at=discord.utils.utcnow(),
    )
    return LobbyMessages(card=card, channel_id=1, message_id=2, executor_id=executor_id)


class TestCombineFinalScore:
    def _league(self) -> CombinesLeague:
        league = _league()
        league.cog._get_combines_api = AsyncMock(return_value="https://combines.example/api/")
        return league

    def _guild(self) -> MagicMock:
        guild = MagicMock()
        guild.get_member.return_value = MagicMock(spec=discord.Member)
        return guild

    async def test_reads_the_score_from_the_api(self):
        finished = models.CombinesLobby.model_validate({**_lobby_payload(), "home_wins": 3, "away_wins": 1, "completed": True})
        with patch("rsc.combines.runner.api.combines_lobby", AsyncMock(return_value=finished)) as lookup:
            score = await self._league().final_score(self._guild(), _entry())
        assert score == LobbyScore(home_wins=3, away_wins=1)
        assert lookup.await_args is not None and lookup.await_args.kwargs["lobby_id"] == 101

    async def test_cancelled_lobby_has_no_score(self):
        cancelled = models.CombinesLobby.model_validate({**_lobby_payload(), "cancelled": True})
        with patch("rsc.combines.runner.api.combines_lobby", AsyncMock(return_value=cancelled)):
            assert await self._league().final_score(self._guild(), _entry()) is None

    async def test_api_status_reply_or_error_has_no_score(self):
        status = models.CombinesStatus(status="error", message="nope")
        with patch("rsc.combines.runner.api.combines_lobby", AsyncMock(return_value=status)):
            assert await self._league().final_score(self._guild(), _entry()) is None
        with patch("rsc.combines.runner.api.combines_lobby", AsyncMock(side_effect=SiteUnavailable("down"))):
            assert await self._league().final_score(self._guild(), _entry()) is None

    async def test_no_executor_skips_the_lookup(self):
        with patch("rsc.combines.runner.api.combines_lobby", AsyncMock()) as lookup:
            assert await self._league().final_score(self._guild(), _entry(executor_id=None)) is None
        lookup.assert_not_awaited()
