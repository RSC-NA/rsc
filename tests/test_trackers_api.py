import sys
from pathlib import Path

import pytest

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rscapi import TrackerLinksApi

from rsc.core import RSC
from rsc.enums import TrackerLinksStatus
from rsc.exceptions import RscException

pytestmark = pytest.mark.integration


class TestTrackerLinksApiContract:
    """Verify all expected rscapi TrackerLinksApi methods exist without calling them."""

    EXPECTED_METHODS = [
        "tracker_links_list",
        "tracker_links_list_without_preload_content",
        "tracker_links_links_stats_list",
        "tracker_links_next_list",
        "tracker_links_create",
        "tracker_links_destroy",
        "tracker_links_unlink_create",
        "tracker_links_link_create",
        "tracker_links_retrieve",
        "tracker_links_migrate_pulls_create",
    ]

    @pytest.mark.parametrize("method_name", EXPECTED_METHODS)
    def test_method_exists(self, method_name: str):
        """Ensure TrackerLinksApi has the expected method."""
        assert hasattr(TrackerLinksApi, method_name), f"TrackerLinksApi missing expected method: {method_name}"
        assert callable(getattr(TrackerLinksApi, method_name)), f"TrackerLinksApi.{method_name} is not callable"


class TestTrackersApiCalls:
    """Test RSC API calls for tracker functions without exceptions."""

    @pytest.mark.asyncio
    async def test_trackers_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that trackers() API call doesn't raise exceptions."""
        result = await rsc_bot.trackers(mock_guild)
        assert result is not None
        assert isinstance(result, list)
        print(f"✓ trackers() returned {len(result)} tracker(s)")

    @pytest.mark.asyncio
    async def test_trackers_with_status_filter(self, rsc_bot: RSC, mock_guild):
        """Test that trackers() with status filter doesn't raise exceptions."""
        result = await rsc_bot.trackers(mock_guild, status=TrackerLinksStatus.PULLED)
        assert result is not None
        assert isinstance(result, list)
        print(f"✓ trackers(status=PULLED) returned {len(result)} tracker(s)")

    @pytest.mark.asyncio
    async def test_trackers_with_player_int(self, rsc_bot: RSC, mock_guild, mock_member):
        """Test that trackers() with player int filter doesn't raise exceptions."""
        result = await rsc_bot.trackers(mock_guild, player=mock_member.id)
        assert result is not None
        assert isinstance(result, list)
        print(f"✓ trackers(player={mock_member.id}) returned {len(result)} tracker(s)")

    @pytest.mark.asyncio
    async def test_trackers_with_player_member(self, rsc_bot: RSC, mock_guild, mock_member):
        """Test that trackers() with player Member filter doesn't raise exceptions."""
        result = await rsc_bot.trackers(mock_guild, player=mock_member)
        assert result is not None
        assert isinstance(result, list)
        print(f"✓ trackers(player=Member) returned {len(result)} tracker(s)")

    @pytest.mark.asyncio
    async def test_trackers_with_limit_offset(self, rsc_bot: RSC, mock_guild):
        """Test that trackers() with limit and offset doesn't raise exceptions."""
        result = await rsc_bot.trackers(mock_guild, limit=10, offset=0)
        assert result is not None
        assert isinstance(result, list)
        assert len(result) <= 10
        print(f"✓ trackers(limit=10, offset=0) returned {len(result)} tracker(s)")


class TestTrackerStatsApiCalls:
    """Test RSC API calls for tracker stats."""

    @pytest.mark.asyncio
    async def test_tracker_stats_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that tracker_stats() API call doesn't raise exceptions."""
        result = await rsc_bot.tracker_stats(mock_guild)
        assert result is not None
        assert isinstance(result, list)
        print(f"✓ tracker_stats() returned {len(result)} stat(s)")
        for s in result:
            print(f"  - Status: {s.status}, Count: {s.count}")


class TestNextTrackerApiCalls:
    """Test RSC API calls for next tracker."""

    @pytest.mark.asyncio
    async def test_next_tracker_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that next_tracker() API call doesn't raise exceptions."""
        result = await rsc_bot.next_tracker(mock_guild)
        assert result is not None
        assert isinstance(result, list)
        assert len(result) <= 25
        print(f"✓ next_tracker() returned {len(result)} tracker(s)")

    @pytest.mark.asyncio
    async def test_next_tracker_with_limit(self, rsc_bot: RSC, mock_guild):
        """Test that next_tracker() with limit doesn't raise exceptions."""
        result = await rsc_bot.next_tracker(mock_guild, limit=5)
        assert result is not None
        assert isinstance(result, list)
        assert len(result) <= 5
        print(f"✓ next_tracker(limit=5) returned {len(result)} tracker(s)")


class TestFetchTrackerByIdApiCalls:
    """Test RSC API calls for fetching tracker by ID."""

    @pytest.mark.asyncio
    async def test_fetch_tracker_by_id_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that fetch_tracker_by_id() API call doesn't raise exceptions."""
        trackers = await rsc_bot.trackers(mock_guild, limit=1)
        if not trackers:
            pytest.skip("No trackers found to test fetch_tracker_by_id")

        tracker = trackers[0]
        if not tracker.id:
            pytest.skip("Tracker has no ID")

        result = await rsc_bot.fetch_tracker_by_id(mock_guild, tracker_id=tracker.id)
        assert result is not None
        assert result.id == tracker.id
        print(f"✓ fetch_tracker_by_id({tracker.id}) returned tracker")
        print(f"  - Platform: {result.platform}, Status: {result.status}")


class TestTrackerDataStructures:
    """Test that API responses have expected structure."""

    @pytest.mark.asyncio
    async def test_tracker_link_structure(self, rsc_bot: RSC, mock_guild):
        """Test that TrackerLink objects have expected attributes."""
        trackers = await rsc_bot.trackers(mock_guild, limit=1)
        if not trackers:
            pytest.skip("No trackers found to test structure")

        tracker = trackers[0]
        assert hasattr(tracker, "id"), "TrackerLink should have 'id' attribute"
        assert hasattr(tracker, "link"), "TrackerLink should have 'link' attribute"
        assert hasattr(tracker, "platform"), "TrackerLink should have 'platform' attribute"
        assert hasattr(tracker, "platform_id"), "TrackerLink should have 'platform_id' attribute"
        assert hasattr(tracker, "status"), "TrackerLink should have 'status' attribute"
        assert hasattr(tracker, "last_updated"), "TrackerLink should have 'last_updated' attribute"
        assert hasattr(tracker, "pulls"), "TrackerLink should have 'pulls' attribute"
        assert hasattr(tracker, "name"), "TrackerLink should have 'name' attribute"
        assert hasattr(tracker, "discord_id"), "TrackerLink should have 'discord_id' attribute"
        print(f"✓ TrackerLink structure valid - ID: {tracker.id}, Platform: {tracker.platform}")

    @pytest.mark.asyncio
    async def test_tracker_stats_structure(self, rsc_bot: RSC, mock_guild):
        """Test that TrackerLinkStats objects have expected attributes."""
        stats = await rsc_bot.tracker_stats(mock_guild)
        if not stats:
            pytest.skip("No tracker stats found to test structure")

        stat = stats[0]
        assert hasattr(stat, "status"), "TrackerLinkStats should have 'status' attribute"
        assert hasattr(stat, "count"), "TrackerLinkStats should have 'count' attribute"
        print(f"✓ TrackerLinkStats structure valid - Status: {stat.status}, Count: {stat.count}")


class TestTrackerMutationApiCalls:
    """Test mutating tracker API calls. Skipped by default to avoid side effects."""

    @pytest.mark.asyncio
    async def test_add_tracker_api_call(self, rsc_bot: RSC, mock_guild, generated_discord_member):
        """Test that add_tracker() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.add_tracker(
                mock_guild,
                player=generated_discord_member,
                tracker=generated_discord_member.tracker_link,
            )
            assert result is not None
            print(f"✓ add_tracker() created tracker - ID: {result.id}")

            # Clean up
            await rsc_bot.rm_tracker(mock_guild, tracker_id=result.id)
            print(f"✓ Cleaned up tracker {result.id}")
        except RscException as e:
            if e.type == "MissingObjectException":
                pytest.skip(f"Generated test member is not present in the API: {e.reason}")
            pytest.fail(f"add_tracker() raised RscException: {e}")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Deleting trackers has side effects; enable when safe to test.")
    async def test_rm_tracker_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that rm_tracker() API call doesn't raise exceptions."""
        trackers = await rsc_bot.trackers(mock_guild, limit=1)
        if not trackers:
            pytest.skip("No trackers found to test rm_tracker")

        tracker = trackers[0]
        if not tracker.id:
            pytest.skip("Tracker has no ID")

        await rsc_bot.rm_tracker(mock_guild, tracker_id=tracker.id)
        print(f"✓ rm_tracker({tracker.id}) succeeded")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Linking trackers has side effects; enable when safe to test.")
    async def test_link_tracker_api_call(self, rsc_bot: RSC, mock_guild, mock_member, mock_executor):
        """Test that link_tracker() API call doesn't raise exceptions."""
        trackers = await rsc_bot.trackers(mock_guild, limit=1)
        if not trackers:
            pytest.skip("No trackers found to test link_tracker")

        tracker = trackers[0]
        if not tracker.id:
            pytest.skip("Tracker has no ID")

        result = await rsc_bot.link_tracker(mock_guild, tracker_id=tracker.id, player=mock_member, executor=mock_executor)
        assert result is not None
        print(f"✓ link_tracker({tracker.id}) returned linked tracker")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Unlinking trackers has side effects; enable when safe to test.")
    async def test_unlink_tracker_api_call(self, rsc_bot: RSC, mock_guild, mock_member, mock_executor):
        """Test that unlink_tracker() API call doesn't raise exceptions."""
        trackers = await rsc_bot.trackers(mock_guild, limit=1)
        if not trackers:
            pytest.skip("No trackers found to test unlink_tracker")

        tracker = trackers[0]
        if not tracker.id:
            pytest.skip("Tracker has no ID")

        result = await rsc_bot.unlink_tracker(mock_guild, tracker_id=tracker.id, player=mock_member, executor=mock_executor)
        assert result is not None
        print(f"✓ unlink_tracker({tracker.id}) returned unlinked tracker")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Migrating pulls has side effects; enable when safe to test.")
    async def test_migrate_tracker_pulls_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that migrate_tracker_pulls() API call doesn't raise exceptions."""
        trackers = await rsc_bot.trackers(mock_guild, limit=2)
        if len(trackers) < 2:
            pytest.skip("Need at least 2 trackers to test migrate_tracker_pulls")

        source = trackers[0]
        dest = trackers[1]
        if not (source.id and dest.id):
            pytest.skip("Trackers missing IDs")

        result = await rsc_bot.migrate_tracker_pulls(mock_guild, source=source.id, dest=dest.id)
        assert result is not None
        print(f"✓ migrate_tracker_pulls({source.id} -> {dest.id}) succeeded")


class TestTrackersApiStatusFilters:
    """Test trackers API with each status filter to catch schema changes."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", list(TrackerLinksStatus))
    async def test_trackers_by_status(self, rsc_bot: RSC, mock_guild, status: TrackerLinksStatus):
        """Test that trackers() with each status value doesn't raise exceptions."""
        result = await rsc_bot.trackers(mock_guild, status=status)
        assert result is not None
        assert isinstance(result, list)
        print(f"✓ trackers(status={status.name}) returned {len(result)} tracker(s)")
