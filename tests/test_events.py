import sys
from datetime import UTC, datetime
from pathlib import Path

import discord
import pytest

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rsc.embeds import BlueEmbed, EmbedLimits
from rsc.enums import EventAction, EventCategory
from rsc.events.events import EventMixIn
from rsc.events.formatters import build_event_embed, generic_event_embed
from rsc.events.models import (
    MAX_EMBEDS_PER_MESSAGE,
    WATERMARK_LAG,
    LeagueEventData,
    plan_batch,
)

NOW = 10_000.0


def evt(event_id: int, **kwargs) -> LeagueEventData:
    kwargs.setdefault("category", EventCategory.TRANSACTION.value)
    kwargs.setdefault("action", EventAction.PLAYER_SIGNED.value)
    return LeagueEventData(id=event_id, **kwargs)


def plan(events, confirmed_id=0, seen_ids=None, history=None, now=NOW, **kwargs):
    return plan_batch(
        events,
        confirmed_id=confirmed_id,
        seen_ids=set() if seen_ids is None else set(seen_ids),
        watermark_history=[] if history is None else history,
        now=now,
        **kwargs,
    )


class TestPlanBatchOrdering:
    def test_sorts_ascending_regardless_of_input_order(self):
        """The poller requests `ordering=id`, but this must not depend on it.

        Ordering is a server-side default that could change; processing order is
        a correctness property of the cursor, so it is enforced here too.
        """
        result = plan([evt(3), evt(1), evt(2)])
        assert [e.id for e in result.to_process] == [1, 2, 3]

    def test_ignores_events_at_or_below_the_watermark(self):
        result = plan([evt(1), evt(2), evt(3)], confirmed_id=2)
        assert [e.id for e in result.to_process] == [3]

    def test_batch_cap_slices_from_the_front(self):
        result = plan([evt(i) for i in range(1, 11)], max_events=4)
        assert [e.id for e in result.to_process] == [1, 2, 3, 4]
        assert result.remaining == 6

    def test_empty_response_is_a_no_op(self):
        result = plan([], confirmed_id=7)
        assert result.to_process == []
        assert result.confirmed_id == 7
        assert result.remaining == 0


class TestPlanBatchDeduplication:
    def test_seen_ids_are_not_reprocessed(self):
        result = plan([evt(1), evt(2), evt(3)], seen_ids={1, 2})
        assert [e.id for e in result.to_process] == [3]

    def test_processed_ids_are_added_to_seen(self):
        result = plan([evt(1), evt(2)])
        assert result.seen_ids == {1, 2}

    def test_seen_ids_are_pruned_once_confirmed(self):
        """Ids at or below the watermark no longer need tracking."""
        history = [(NOW - WATERMARK_LAG - 1, 5)]
        result = plan([], confirmed_id=0, seen_ids={1, 2, 3, 6, 7}, history=history)
        assert result.confirmed_id == 5
        assert result.seen_ids == {6, 7}

    def test_restart_does_not_replay_the_lag_window(self):
        """SeenIds is persisted precisely so a reload does not re-post."""
        first = plan([evt(1), evt(2), evt(3)])
        # Same response again on the next tick, watermark not yet matured.
        second = plan(
            [evt(1), evt(2), evt(3)],
            seen_ids=first.seen_ids,
            history=first.watermark_history,
            now=NOW + 30,
        )
        assert second.to_process == []


class TestPlanBatchWatermark:
    def test_watermark_does_not_advance_before_the_lag_elapses(self):
        result = plan([evt(1), evt(2), evt(3)])
        assert result.confirmed_id == 0
        assert result.watermark_history == [(NOW, 3)]

    def test_watermark_advances_once_the_observation_matures(self):
        history = [(NOW - WATERMARK_LAG - 1, 3)]
        result = plan([], confirmed_id=0, seen_ids={1, 2, 3}, history=history)
        assert result.confirmed_id == 3
        assert result.watermark_history == []

    def test_late_committing_lower_id_is_still_processed(self):
        """The bug the whole design exists to prevent.

        Postgres allocates sequence values before commit, so a transaction
        holding ids 500-600 can commit *after* 601 is already visible. A naive
        max(id) cursor would jump to 601 and lose 500-600 forever.
        """
        # Poll 1: only the higher id has committed.
        first = plan([evt(601)])
        assert [e.id for e in first.to_process] == [601]
        # The watermark stays put, so id__gt does not skip past the gap.
        assert first.confirmed_id == 0

        # Poll 2, moments later: the big transaction commits.
        second = plan(
            [evt(500), evt(601)],
            confirmed_id=first.confirmed_id,
            seen_ids=first.seen_ids,
            history=first.watermark_history,
            now=NOW + 30,
        )
        assert [e.id for e in second.to_process] == [500]

    def test_capped_batch_never_confirms_past_what_was_processed(self):
        """The frontier must not run ahead of the events actually handled."""
        result = plan([evt(i) for i in range(1, 21)], max_events=5, now=NOW)
        assert result.watermark_history == [(NOW, 5)]

        # Even after maturing, it only advances to the 5th event.
        matured = plan(
            [],
            confirmed_id=0,
            seen_ids=result.seen_ids,
            history=[(NOW - WATERMARK_LAG - 1, 5)],
        )
        assert matured.confirmed_id == 5

    def test_watermark_never_moves_backwards(self):
        history = [(NOW - WATERMARK_LAG - 1, 3)]
        result = plan([], confirmed_id=10, history=history)
        assert result.confirmed_id == 10

    def test_no_candidate_recorded_when_nothing_is_new(self):
        result = plan([evt(1)], confirmed_id=5)
        assert result.watermark_history == []
        assert result.confirmed_id == 5

    def test_drains_a_backlog_across_ticks(self):
        events = [evt(i) for i in range(1, 13)]
        confirmed, seen, history, now = 0, set(), [], NOW
        processed = []

        for _ in range(4):
            result = plan_batch(
                events,
                confirmed_id=confirmed,
                seen_ids=seen,
                watermark_history=history,
                now=now,
                max_events=5,
            )
            processed.extend(e.id for e in result.to_process)
            confirmed, seen, history = result.confirmed_id, result.seen_ids, result.watermark_history
            now += 30

        assert processed == list(range(1, 13))


class TestLeagueEventData:
    def test_known_enums_parse(self):
        event = evt(1, category="TRN", action="WCW")
        assert event.event_category is EventCategory.TRANSACTION
        assert event.event_action is EventAction.WAIVER_CLAIM_WON

    def test_unknown_enums_degrade_to_none(self):
        """Client drift must not raise. It renders as a generic embed."""
        event = evt(1, category="ZZZ", action="QQQ")
        assert event.event_category is None
        assert event.event_action is None

    def test_from_raw_parses_a_json_payload(self):
        event = LeagueEventData.from_raw(
            {
                "id": 42,
                "league": 1,
                "category": "TRN",
                "action": "WCL",
                "actor": {"name": "nickm", "discord_id": 138778232802508801},
                "object_id": 9,
                "payload": {"waiver_claim": {"player_name": "someone"}},
                "is_public": True,
                "created_at": "2026-08-04T12:00:00Z",
            }
        )
        assert event is not None
        assert event.id == 42
        assert event.actor_name == "nickm"
        assert event.actor_discord_id == 138778232802508801
        assert event.created_at == datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

    def test_from_raw_rejects_an_event_without_an_id(self):
        """The id is the cursor and cannot be substituted."""
        assert LeagueEventData.from_raw({"category": "TRN"}) is None

    def test_from_raw_survives_an_unparseable_timestamp(self):
        event = LeagueEventData.from_raw({"id": 1, "created_at": "not-a-date"})
        assert event is not None
        assert event.created_at is None

    def test_from_api_rejects_an_event_without_an_id(self):
        from rscapi.models.league_event_list import LeagueEventList

        assert LeagueEventData.from_api(LeagueEventList(category="TRN")) is None

    def test_from_api_normalizes_enums_to_plain_str(self):
        """Filters compare against config values, which are plain strings."""
        from rscapi.models.league_event_list import LeagueEventList

        event = LeagueEventData.from_api(LeagueEventList(id=1, category="TRN", action="PTR"))
        assert event is not None
        assert type(event.category) is str
        assert event.category == "TRN"


class TestFormatters:
    def test_unknown_action_renders_generically(self):
        """Falls back to the category label and flags that the bot is behind."""
        embed = build_event_embed(evt(1, action="QQQ", payload={"a": 1}))
        assert embed.title == "Transaction Event"
        assert embed.footer.text is not None
        assert "QQQ" in [f.value for f in embed.fields]

    def test_fully_unknown_event_still_renders(self):
        embed = build_event_embed(evt(1, category="ZZZ", action="QQQ", payload={"a": 1}))
        assert embed.title == "League Event"

    def test_waiver_claim_renders_its_payload(self):
        event = evt(
            1,
            action=EventAction.WAIVER_CLAIM_WON.value,
            payload={
                "waiver_claim": {
                    "player_name": "somebody",
                    "franchise_name": "Some Franchise",
                    "tier_name": "Elite",
                    "outcome": "won",
                }
            },
        )
        embed = build_event_embed(event)
        assert embed.title == "Waiver Claim Won"
        values = [f.value for f in embed.fields]
        assert "somebody" in values
        assert "Some Franchise" in values

    def test_malformed_payload_falls_back_instead_of_raising(self):
        event = evt(1, action=EventAction.WAIVER_CLAIM_WON.value, payload="not a dict")
        embed = build_event_embed(event)
        assert embed.title is not None

    def test_payload_markdown_is_escaped(self):
        event = evt(
            1,
            action=EventAction.WAIVER_CLAIM_WON.value,
            payload={"waiver_claim": {"player_name": "**@everyone**"}},
        )
        embed = build_event_embed(event)
        player = next(f.value for f in embed.fields if f.name == "Player")
        assert player is not None
        assert "**" not in player

    def test_oversized_payload_does_not_exceed_embed_limits(self):
        event = evt(1, payload={"blob": "x" * 50_000})
        embed = generic_event_embed(event)
        assert not embed.exceeds_limits()

    @pytest.mark.parametrize("action", list(EventAction))
    def test_every_action_renders(self, action: EventAction):
        """No action may raise, including ones with no dedicated formatter."""
        embed = build_event_embed(evt(1, action=action.value, payload={"k": "v"}))
        assert embed.title

    @pytest.mark.parametrize(
        ("severity", "colour"),
        [
            ("INF", discord.Color.blue()),
            ("WRN", discord.Color.yellow()),
            ("ERR", discord.Color.orange()),
            ("CRT", discord.Color.red()),
        ],
    )
    def test_severity_drives_embed_colour(self, severity: str, colour: discord.Color):
        embed = build_event_embed(evt(1, category="SYS", action="MPF", severity=severity))
        assert embed.color == colour

    def test_severity_overrides_a_formatter_colour(self):
        """A failed waiver claim must not render green just because it was 'won'."""
        event = evt(
            1,
            action=EventAction.WAIVER_CLAIM_WON.value,
            severity="CRT",
            payload={"waiver_claim": {"player_name": "somebody"}},
        )
        assert build_event_embed(event).color == discord.Color.red()

    def test_system_event_renders_with_severity_field(self):
        embed = build_event_embed(
            evt(1, category="SYS", action="TKF", severity="ERR", payload={"task": "mmr_pull"})
        )
        assert embed.title == "Task Failed"
        assert any(f.name == "Severity" for f in embed.fields)

    def test_global_event_is_marked(self):
        event = LeagueEventData(id=1, league=None, category="SYS", action="MPF", severity="ERR")
        embed = build_event_embed(event)
        assert any(f.name == "Scope" for f in embed.fields)

    def test_unknown_severity_does_not_raise(self):
        embed = build_event_embed(evt(1, severity="ZZZ"))
        assert embed.title


class TestFilters:
    """Filters are display only and compare against config values, not names."""

    @staticmethod
    def check(event: LeagueEventData, categories=None, actions=None, severities=None) -> bool:
        return EventMixIn._passes_filter(
            event,
            {
                "CategoryFilter": categories or [],
                "ActionFilter": actions or [],
                "SeverityFilter": severities or [],
            },
        )

    def test_empty_filters_allow_everything(self):
        assert self.check(evt(1))

    def test_category_filter_matches_on_value(self):
        assert self.check(evt(1, category="TRN"), categories=["TRN"])
        assert not self.check(evt(1, category="ANN"), categories=["TRN"])

    def test_action_filter_matches_on_value(self):
        assert self.check(evt(1, action="PSG"), actions=["PSG"])
        assert not self.check(evt(1, action="PCT"), actions=["PSG"])

    def test_enum_names_do_not_match(self):
        """Storing names instead of values would silently never match."""
        assert not self.check(evt(1, category="TRN"), categories=["TRANSACTION"])

    def test_both_filters_must_pass(self):
        event = evt(1, category="TRN", action="PSG")
        assert not self.check(event, categories=["TRN"], actions=["PCT"])

    def test_severity_filter_matches_on_value(self):
        assert self.check(evt(1, severity="ERR"), severities=["ERR", "CRT"])
        assert not self.check(evt(1, severity="INF"), severities=["ERR", "CRT"])

    def test_missing_severity_is_not_excluded_by_a_filter(self):
        """Omission must not drop an event; only an explicit mismatch does."""
        assert self.check(evt(1, severity=None), severities=["ERR"])


class TestEmbedChunking:
    def test_respects_the_ten_embed_message_cap(self):
        embeds = [BlueEmbed(title=f"e{i}") for i in range(25)]
        chunks = EventMixIn._chunk_embeds(embeds)
        assert all(len(c) <= MAX_EMBEDS_PER_MESSAGE for c in chunks)
        assert sum(len(c) for c in chunks) == 25

    def test_respects_the_total_character_cap(self):
        """6000 chars is a per-message total across all embeds, not per embed."""
        embeds = [BlueEmbed(title="x", description="y" * 2000) for _ in range(5)]
        chunks = EventMixIn._chunk_embeds(embeds)
        assert all(sum(len(e) for e in c) <= EmbedLimits.Total for c in chunks)
        assert sum(len(c) for c in chunks) == 5

    def test_empty_input_produces_no_messages(self):
        assert EventMixIn._chunk_embeds([]) == []
