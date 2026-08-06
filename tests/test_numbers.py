from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rscapi.exceptions import ApiException

from rsc.exceptions import RscException
from rsc.numbers.numbers import NumberMixIn


def _create_mixin(**attrs):
    saved = NumberMixIn.__abstractmethods__
    NumberMixIn.__abstractmethods__ = frozenset()
    try:
        mixin = object.__new__(NumberMixIn)
    finally:
        NumberMixIn.__abstractmethods__ = saved
    for key, value in attrs.items():
        setattr(mixin, key, value)
    return mixin


class TestMmrPullsApi:
    async def test_returns_mmr_pull_results(self, mock_guild, mock_member):
        pulled_before = datetime(2026, 5, 21, 12, 0, tzinfo=UTC)
        pulled_after = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
        resp = MagicMock()
        resp.results = [MagicMock(), MagicMock()]
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.numbers_mmr_list.return_value = resp
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.numbers.numbers.NumbersApi", return_value=mock_api):
                result = await mixin.mmr_pulls(
                    mock_guild,
                    pulled_before=pulled_before,
                    pulled_after=pulled_after,
                    player=mock_member,
                    rscid="abc123",
                    rscid_begin="abc",
                    rscid_end="xyz",
                    psyonix_season=17,
                )

        assert result is resp.results
        mock_api.numbers_mmr_list.assert_awaited_once_with(
            pulled=None,
            pulled_before=pulled_before.isoformat(),
            pulled_after=pulled_after.isoformat(),
            discord_id=mock_member.id,
            rscid="abc123",
            rscid_begin="abc",
            rscid_end="xyz",
            psyonix_season=17,
            limit=1000,
        )

    async def test_raises_rsc_exception(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.numbers_mmr_list.side_effect = ApiException(status=500, reason="Error")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.numbers.numbers.NumbersApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.mmr_pulls(mock_guild)
