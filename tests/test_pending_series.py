from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from rscapi.exceptions import ApiException, NotFoundException
from rscapi.models.pending_series import PendingSeries

from rsc.exceptions import RscException
from rsc.matches.matches import MatchMixIn
from rsc.teams.teams import TeamMixIn


def _create(cls, **attrs):
    saved = cls.__abstractmethods__
    cls.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(cls)
    finally:
        cls.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _series(home=True) -> PendingSeries:
    series = PendingSeries.from_dict(
        {
            "tier": "Master",
            "round": 2,
            "round_label": "Quarterfinals",
            "match_format": "BO5",
            "num_games": 5,
            "date": "2026-11-02T22:30:00-05:00",
            "home": home,
            "team": {"id": 1, "name": "Giraffes"},
            "possible_opponents": [{"id": 2, "name": "Wheelchairs"}, {"id": 3, "name": "Wet Willies"}],
            "feeder_match": {
                "id": 9,
                "day": 1,
                "date": "2026-11-02T21:45:00-05:00",
                "match_format": "BO5",
                "home_team": {"id": 2, "name": "Wheelchairs"},
                "away_team": {"id": 3, "name": "Wet Willies"},
            },
        }
    )
    assert series is not None
    return series


class TestPendingSeriesApi:
    async def _call(self, mock_guild, **api_behaviour):
        mixin = _create(TeamMixIn, _api_conf={mock_guild.id: MagicMock()}, _league={mock_guild.id: 1})
        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            for name, value in api_behaviour.items():
                setattr(mock_api.teams_pending_series_retrieve, name, value)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                return await mixin.pending_series(mock_guild, 1)

    async def test_returns_the_series(self, mock_guild):
        series = _series()
        assert await self._call(mock_guild, return_value=series) is series

    async def test_no_pending_series_is_none(self, mock_guild):
        assert await self._call(mock_guild, side_effect=NotFoundException(status=404, reason="Not Found")) is None

    async def test_other_api_errors_raise(self, mock_guild):
        with pytest.raises(RscException):
            await self._call(mock_guild, side_effect=ApiException(status=500, reason="Error"))


class TestBuildPendingSeriesEmbed:
    async def _embed(self, mock_guild, **kwargs) -> discord.Embed:
        mixin = _create(MatchMixIn)
        with patch("rsc.matches.matches.tier_color_by_name", AsyncMock(return_value=discord.Color.purple())):
            return await mixin.build_pending_series_embed(mock_guild, _series(**kwargs))

    @staticmethod
    def _field(embed: discord.Embed, name: str) -> str:
        value = next(field.value for field in embed.fields if field.name == name)
        assert value is not None
        return value

    async def test_names_the_series_its_start_and_both_possible_opponents(self, mock_guild):
        embed = await self._embed(mock_guild)

        assert embed.title == "Quarterfinals Match: November 2, 2026"
        assert embed.description == "**Giraffes**\nversus\n**Winner of Wheelchairs / Wet Willies**"
        assert "<t:1793676600:F>" in self._field(embed, "Starts")
        assert self._field(embed, "Format") == "Best of 5"
        opponent = self._field(embed, "Opponent")
        assert "Wildcard series **Wheelchairs** vs **Wet Willies** at <t:1793673900:t>" in opponent

    async def test_says_the_lobby_comes_once_the_feeder_is_reported(self, mock_guild):
        embed = await self._embed(mock_guild)

        assert "once that series is reported" in self._field(embed, "Lobby Info")

    @pytest.mark.parametrize(
        ("home", "expected"),
        [(True, "**HOME** team"), (False, "**AWAY** team"), (None, "depends on who wins")],
    )
    async def test_home_side(self, mock_guild, home, expected):
        embed = await self._embed(mock_guild, home=home)

        assert expected in self._field(embed, "Home Team")


class TestMatchCommandFallsBackToThePendingSeries:
    async def _run(self, mock_guild, pending):
        mixin = _create(
            MatchMixIn,
            next_match=AsyncMock(return_value=None),
            pending_series=AsyncMock(return_value=pending),
            team_id_by_name=AsyncMock(return_value=1),
        )
        interaction = MagicMock()
        interaction.guild = mock_guild
        interaction.user = MagicMock(spec=discord.Member)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        with patch("rsc.matches.matches.tier_color_by_name", AsyncMock(return_value=discord.Color.purple())):
            # The unbound command callback, called the way discord.py calls it on the cog.
            match_cmd = cast("Any", MatchMixIn._match_cmd.callback)
            await match_cmd(mixin, interaction, team="Giraffes")
        call = interaction.followup.send.await_args
        assert call is not None
        return call.kwargs["embed"]

    async def test_a_bye_seed_sees_its_pending_series(self, mock_guild):
        embed = await self._run(mock_guild, _series())

        assert embed.title == "Quarterfinals Match: November 2, 2026"

    async def test_no_match_and_no_pending_series_says_so(self, mock_guild):
        embed = await self._run(mock_guild, None)

        assert embed.description == "You do not have any upcoming matches."
