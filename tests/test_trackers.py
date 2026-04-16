from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from rscapi.exceptions import ApiException

from rsc.exceptions import RscException
from rsc.trackers.trackers import TrackerMixIn

GUILD_ID = 395806681994493964


def _create_mixin(**attrs):
    saved = TrackerMixIn.__abstractmethods__
    TrackerMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(TrackerMixIn)
    finally:
        TrackerMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


class TestTrackersApi:
    async def test_returns_trackers(self, mock_guild):
        resp = MagicMock()
        resp.results = [MagicMock()]
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.trackers.trackers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tracker_links_list.return_value = resp
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.trackers.trackers.TrackerLinksApi", return_value=mock_api):
                result = await mixin.trackers(mock_guild)

        assert len(result) == 1

    async def test_raises_rsc_exception(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.trackers.trackers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tracker_links_list.side_effect = ApiException(status=500, reason="Error")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.trackers.trackers.TrackerLinksApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.trackers(mock_guild)

    async def test_accepts_member_player(self, mock_guild, mock_member):
        resp = MagicMock()
        resp.results = []
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.trackers.trackers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tracker_links_list.return_value = resp
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.trackers.trackers.TrackerLinksApi", return_value=mock_api):
                await mixin.trackers(mock_guild, player=mock_member)

        call_kwargs = mock_api.tracker_links_list.call_args[1]
        assert call_kwargs["discord_id"] == mock_member.id

    async def test_accepts_int_player(self, mock_guild):
        resp = MagicMock()
        resp.results = []
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.trackers.trackers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tracker_links_list.return_value = resp
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.trackers.trackers.TrackerLinksApi", return_value=mock_api):
                await mixin.trackers(mock_guild, player=12345)

        call_kwargs = mock_api.tracker_links_list.call_args[1]
        assert call_kwargs["discord_id"] == 12345


class TestTrackerStatsApi:
    async def test_returns_stats(self, mock_guild):
        stats = [MagicMock()]
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.trackers.trackers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tracker_links_links_stats.return_value = stats
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.trackers.trackers.TrackerLinksApi", return_value=mock_api):
                result = await mixin.tracker_stats(mock_guild)

        assert len(result) == 1


class TestNextTrackerApi:
    async def test_returns_trackers(self, mock_guild):
        trackers = [MagicMock()]
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.trackers.trackers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tracker_links_next.return_value = trackers
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.trackers.trackers.TrackerLinksApi", return_value=mock_api):
                result = await mixin.next_tracker(mock_guild)

        assert len(result) == 1


class TestAddTrackerApi:
    async def test_adds_tracker(self, mock_guild, mock_member):
        created = MagicMock()
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.trackers.trackers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tracker_links_create.return_value = created
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.trackers.trackers.TrackerLinksApi", return_value=mock_api):
                result = await mixin.add_tracker(mock_guild, player=mock_member, tracker="https://tracker.gg/1")

        assert result is created


class TestRmTrackerApi:
    async def test_removes_tracker(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.trackers.trackers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tracker_links_delete.return_value = None
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.trackers.trackers.TrackerLinksApi", return_value=mock_api):
                await mixin.rm_tracker(mock_guild, tracker_id=5)

        mock_api.tracker_links_delete.assert_awaited_once_with(5)


class TestUnlinkTrackerApi:
    async def test_unlinks_tracker(self, mock_guild, mock_member, mock_executor):
        unlinked = MagicMock()
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.trackers.trackers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tracker_links_unlink.return_value = unlinked
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.trackers.trackers.TrackerLinksApi", return_value=mock_api):
                result = await mixin.unlink_tracker(mock_guild, tracker_id=5, player=mock_member, executor=mock_executor)

        assert result is unlinked


class TestLinkTrackerApi:
    async def test_links_tracker(self, mock_guild, mock_member, mock_executor):
        linked = MagicMock()
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.trackers.trackers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tracker_links_link.return_value = linked
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.trackers.trackers.TrackerLinksApi", return_value=mock_api):
                result = await mixin.link_tracker(mock_guild, tracker_id=5, player=mock_member, executor=mock_executor)

        assert result is linked


class TestFetchTrackerByIdApi:
    async def test_fetches_tracker(self, mock_guild):
        tracker = MagicMock()
        tracker.id = 42
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.trackers.trackers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tracker_links_read.return_value = tracker
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.trackers.trackers.TrackerLinksApi", return_value=mock_api):
                result = await mixin.fetch_tracker_by_id(mock_guild, tracker_id=42)

        assert result.id == 42


class TestMigrateTrackerPullsApi:
    async def test_migrates_pulls(self, mock_guild):
        migrated = MagicMock()
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.trackers.trackers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tracker_links_migrate_pulls.return_value = migrated
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.trackers.trackers.TrackerLinksApi", return_value=mock_api):
                result = await mixin.migrate_tracker_pulls(mock_guild, source=1, dest=2)

        assert result is migrated
