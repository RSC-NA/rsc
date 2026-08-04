"""Tests for announcing trades performed outside Discord.

The builder tests are driven from realistic `TransactionResponseSerializer` payloads
parsed through `TransactionResponse.from_dict`, which is exactly what the handler
does with a `PTR` event payload.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from rscapi.models.transaction_response import TransactionResponse

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rsc.embeds import EmbedLimits
from rsc.events.models import LeagueEventData
from rsc.transactions.trade_announce import (
    TRADE_ANNOUNCE_MAX_AGE,
    announce_trade,
    apply_trade_role_updates,
    build_trade_embed_from_response,
    process_trade_event,
)

GUILD_ID = 1
LEAGUE_ID = 7

WOLVES_GM = 100
FLARES_GM = 200
COMETS_GM = 300


def franchise(name: str, gm_id: int, gm_name: str = "GM", prefix: str = "XX", fid: int | None = None) -> dict:
    return {"gm": {"rsc_name": gm_name, "discord_id": gm_id}, "name": name, "id": fid, "prefix": prefix}


def player_update(
    discord_id: int | None,
    dest_name: str,
    dest_gm: int,
    team_name: str = "Comets",
    *,
    player_name: str = "SomePlayer",
    dest_id: int | None = 12,
    new_team: bool = True,
) -> dict:
    """A player move. `player.team` is the POST-trade team, matching the API."""
    return {
        "player": {
            "id": 4821,
            "league": {"id": LEAGUE_ID, "name": "RSC 3v3", "guild_id": GUILD_ID},
            "status": "RO",
            "season": 21,
            "captain": False,
            "contract_length": 2,
            "current_mmr": 1600,
            "base_mmr": 1600,
            "team": {
                "name": team_name,
                "franchise": {
                    "name": dest_name,
                    "id": dest_id,
                    "gm": {"rsc_name": "GM", "discord_id": dest_gm},
                    "prefix": "XX",
                },
                "id": 331,
            },
            "last_updated": "2026-08-04T18:22:11Z",
            "previous_teams": [],
            "player": {"name": player_name, "rsc_id": "RSC000123", "discord_id": discord_id},
            "tier": {"name": "Master", "id": 3, "color": 1, "position": 2},
            "sub_status": 0,
            "waiver_period_end_date": None,
            "signed_date": "2026-06-01T00:00:00Z",
        },
        "old_team": {"id": 208, "name": "Wolves", "tier": "Master"},
        "new_team": {"id": 331, "name": team_name, "tier": "Master"} if new_team else None,
    }


def pick_trade(
    dest_name: str,
    dest_gm: int,
    *,
    source_name: str | None = None,
    source_gm: int | None = None,
    round_no: int | None = 1,
    number: int | None = 4,
    tier: str = "Master",
    future: bool = False,
) -> dict:
    return {
        "pick": {
            "id": 9931,
            "number": number,
            "round": round_no,
            "tier": tier,
            "future_pick": future,
            "future_season": 0,
            "pick_from": "SF",
            "original_pick": "TW",
        },
        "source": franchise(source_name, source_gm) if source_name and source_gm else None,
        "destination": franchise(dest_name, dest_gm),
    }


def response(
    *,
    players: list[dict] | None = None,
    picks: list[dict] | None = None,
    first: dict | None = None,
    second: dict | None = None,
    ttype: str = "TRD",
    transaction_id: int = 55123,
) -> TransactionResponse:
    return TransactionResponse.from_dict(
        {
            "player_updates": players,
            "pick_trades": picks,
            "date": "2026-08-04T18:22:11Z",
            "week": "REG",
            "week_no": 4,
            "match_day": 8,
            "type": ttype,
            "notes": "test trade",
            "first_franchise": first,
            "second_franchise": second,
            "executor": {"rsc_name": "Staff", "rsc_id": "RSC1", "discord_id": 999},
            "id": transaction_id,
        }
    )


@pytest.fixture
def guild() -> MagicMock:
    g = MagicMock(spec=discord.Guild)
    g.id = GUILD_ID
    g.name = "Test Guild"
    g.icon = None
    g.get_member = MagicMock(return_value=None)
    return g


def field_names(embed) -> list[str]:
    return [f.name for f in embed.fields]


def field_by_prefix(embed, prefix: str) -> str:
    return next(f.value for f in embed.fields if f.name and f.name.startswith(prefix))


class TestGrouping:
    async def test_one_field_per_franchise(self, guild):
        resp = response(
            players=[player_update(111, "Thunder Wolves", WOLVES_GM)],
            picks=[pick_trade("Solar Flares", FLARES_GM)],
        )
        _, embed = await build_trade_embed_from_response(guild, resp)

        assert len(embed.fields) == 2

    async def test_interleaved_input_does_not_duplicate_a_franchise(self, guild):
        """`itertools.groupby` only groups adjacent runs, so this ordering would
        emit the same franchise twice. Keying on a dict makes it impossible."""
        resp = response(
            players=[
                player_update(111, "Thunder Wolves", WOLVES_GM),
                player_update(222, "Solar Flares", FLARES_GM),
                player_update(333, "Thunder Wolves", WOLVES_GM),
            ],
        )
        _, embed = await build_trade_embed_from_response(guild, resp)

        assert len(embed.fields) == 2
        wolves = field_by_prefix(embed, "Thunder Wolves")
        assert "<@!111>" in wolves
        assert "<@!333>" in wolves

    async def test_franchise_as_both_pick_source_and_player_destination_collapses(self, guild):
        resp = response(
            players=[player_update(111, "Thunder Wolves", WOLVES_GM)],
            picks=[pick_trade("Solar Flares", FLARES_GM, source_name="Thunder Wolves", source_gm=WOLVES_GM)],
        )
        _, embed = await build_trade_embed_from_response(guild, resp)

        assert len(embed.fields) == 2

    async def test_null_franchise_id_does_not_split_a_franchise(self, guild):
        """`PlayerFranchise.id` is Optional while `TransactionFranchise.id` is not,
        so keying on id would split one franchise across two fields."""
        resp = response(
            players=[player_update(111, "Thunder Wolves", WOLVES_GM, dest_id=None)],
            picks=[pick_trade("Thunder Wolves", WOLVES_GM)],
        )
        _, embed = await build_trade_embed_from_response(guild, resp)

        assert len(embed.fields) == 1

    async def test_franchise_with_nothing_received_is_omitted(self, guild):
        resp = response(
            players=[player_update(111, "Thunder Wolves", WOLVES_GM)],
            first=franchise("Thunder Wolves", WOLVES_GM),
            second=franchise("Solar Flares", FLARES_GM),
        )
        _, embed = await build_trade_embed_from_response(guild, resp)

        assert len(embed.fields) == 1


class TestLines:
    async def test_player_line_includes_destination_team(self, guild):
        resp = response(players=[player_update(111, "Thunder Wolves", WOLVES_GM, team_name="Comets")])
        _, embed = await build_trade_embed_from_response(guild, resp)

        assert field_by_prefix(embed, "Thunder Wolves") == "<@!111> to Comets"

    async def test_player_without_new_team_omits_the_destination(self, guild):
        resp = response(players=[player_update(111, "Thunder Wolves", WOLVES_GM, new_team=False)])
        _, embed = await build_trade_embed_from_response(guild, resp)

        assert field_by_prefix(embed, "Thunder Wolves") == "<@!111>"

    async def test_player_without_discord_id_falls_back_to_name(self, guild):
        resp = response(players=[player_update(None, "Thunder Wolves", WOLVES_GM, player_name="NoDiscord")])
        _, embed = await build_trade_embed_from_response(guild, resp)

        assert "NoDiscord" in field_by_prefix(embed, "Thunder Wolves")

    @pytest.mark.parametrize(
        ("round_no", "expected"),
        [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th")],
    )
    async def test_pick_round_ordinals(self, guild, round_no, expected):
        resp = response(picks=[pick_trade("Solar Flares", FLARES_GM, round_no=round_no)])
        _, embed = await build_trade_embed_from_response(guild, resp)

        assert field_by_prefix(embed, "Solar Flares").startswith(expected)

    async def test_null_round_does_not_render_noneth(self, guild):
        """`TransactionPick.round` is Optional; the original builder produced
        `"Noneth"` for a null round."""
        resp = response(picks=[pick_trade("Solar Flares", FLARES_GM, round_no=None)])
        _, embed = await build_trade_embed_from_response(guild, resp)

        value = field_by_prefix(embed, "Solar Flares")
        assert "Noneth" not in value
        assert "Unknown Round" in value

    async def test_null_pick_number_omits_the_parenthetical(self, guild):
        resp = response(picks=[pick_trade("Solar Flares", FLARES_GM, number=None)])
        _, embed = await build_trade_embed_from_response(guild, resp)

        assert field_by_prefix(embed, "Solar Flares") == "1st Round Master"

    async def test_future_pick_has_no_number(self, guild):
        resp = response(picks=[pick_trade("Solar Flares", FLARES_GM, future=True)])
        _, embed = await build_trade_embed_from_response(guild, resp)

        assert field_by_prefix(embed, "Solar Flares") == "Future 1st Round Master"

    async def test_source_is_shown_when_it_differs_from_destination(self, guild):
        resp = response(
            picks=[pick_trade("Solar Flares", FLARES_GM, source_name="Thunder Wolves", source_gm=WOLVES_GM)]
        )
        _, embed = await build_trade_embed_from_response(guild, resp)

        assert field_by_prefix(embed, "Solar Flares").startswith(f"<@!{WOLVES_GM}> ")

    async def test_source_is_hidden_when_it_matches_the_destination(self, guild):
        resp = response(
            picks=[pick_trade("Solar Flares", FLARES_GM, source_name="Solar Flares", source_gm=FLARES_GM)]
        )
        _, embed = await build_trade_embed_from_response(guild, resp)

        assert field_by_prefix(embed, "Solar Flares").startswith("1st Round")


class TestLabelsAndPings:
    async def test_gm_rsc_name_used_when_member_is_not_in_the_server(self, guild):
        resp = response(players=[player_update(111, "Thunder Wolves", WOLVES_GM)])
        _, embed = await build_trade_embed_from_response(guild, resp)

        assert field_names(embed) == ["Thunder Wolves (GM)"]

    async def test_ping_list_includes_gms_and_traded_players(self, guild):
        resp = response(
            players=[player_update(111, "Thunder Wolves", WOLVES_GM)],
            picks=[pick_trade("Solar Flares", FLARES_GM)],
        )
        ping_ids, _ = await build_trade_embed_from_response(guild, resp)

        assert set(ping_ids) == {WOLVES_GM, FLARES_GM, 111}

    async def test_ping_list_has_no_duplicates(self, guild):
        resp = response(
            players=[
                player_update(111, "Thunder Wolves", WOLVES_GM),
                player_update(222, "Thunder Wolves", WOLVES_GM),
            ],
        )
        ping_ids, _ = await build_trade_embed_from_response(guild, resp)

        assert len(ping_ids) == len(set(ping_ids))


class TestEmbedLimits:
    async def test_large_pick_dump_stays_within_embed_limits(self, guild):
        """A bare add_field would 400 the send past 1024 chars."""
        picks = [
            pick_trade("Solar Flares", FLARES_GM, source_name="Thunder Wolves", source_gm=WOLVES_GM, number=n)
            for n in range(60)
        ]
        _, embed = await build_trade_embed_from_response(guild, response(picks=picks))

        assert not embed.exceeds_limits()

    async def test_truncation_is_disclosed(self, guild):
        picks = [pick_trade("Solar Flares", FLARES_GM, number=n) for n in range(400)]
        _, embed = await build_trade_embed_from_response(guild, response(picks=picks))

        assert embed.footer.text is not None
        assert not embed.exceeds_limits()

    async def test_field_values_never_exceed_the_cap(self, guild):
        picks = [pick_trade("Solar Flares", FLARES_GM, number=n) for n in range(60)]
        _, embed = await build_trade_embed_from_response(guild, response(picks=picks))

        for f in embed.fields:
            assert f.value is not None
            assert len(f.value) <= EmbedLimits.Field.Value


class TestPickOnlyTrade:
    async def test_pick_only_trade_still_renders(self, guild):
        """`player_updates` is Optional and empty for a pure futures trade."""
        resp = response(players=None, picks=[pick_trade("Solar Flares", FLARES_GM)])
        _, embed = await build_trade_embed_from_response(guild, resp)

        assert len(embed.fields) == 1


class FakeValue:
    def __init__(self, store: dict, key: str):
        self._store, self._key = store, key

    async def __call__(self):
        return self._store[self._key]

    async def set(self, value):
        self._store[self._key] = value


class FakeGroup:
    def __init__(self, store: dict):
        self._store = store

    def __getattr__(self, name: str) -> FakeValue:
        return FakeValue(self._store, name)

    async def all(self) -> dict:
        return dict(self._store)


class FakeConfig:
    def __init__(self, store: dict):
        self._store = store

    def custom(self, *_args) -> FakeGroup:
        return FakeGroup(self._store)


def make_cog(store: dict, *, channel: MagicMock | None = None) -> MagicMock:
    cog = MagicMock()
    cog.config = FakeConfig(store)
    cog._league = {GUILD_ID: LEAGUE_ID}
    cog._trans_channel = AsyncMock(return_value=channel)
    cog.tiers = AsyncMock(return_value=[])
    cog._try_post_embeds = AsyncMock()
    cog.transaction_history_by_id = AsyncMock()
    return cog


def trade_settings(**overrides) -> dict:
    store = {"TradeAnnouncements": True, "TradeRoleUpdates": True, "AnnouncedTrades": []}
    store.update(overrides)
    return store


def make_channel() -> MagicMock:
    channel = MagicMock()
    sent = []
    msg = MagicMock()
    msg.edit = AsyncMock()
    msg.jump_url = "https://discord.com/x"

    async def send(**kwargs):
        sent.append(kwargs)
        return msg

    channel.send = send
    channel.sent = sent
    return channel


def trade_event(created_at: datetime | None = None, league: int | None = LEAGUE_ID, **kw) -> LeagueEventData:
    resp = response(**kw)
    return LeagueEventData(
        id=9012,
        league=league,
        category="TRN",
        action="PTR",
        severity="INF",
        object_id=55123,
        # model_dump, never to_dict: every field on these generated models is
        # marked readOnly, so to_dict drops all of them.
        payload={"transaction": resp.model_dump(mode="json")},
        is_public=True,
        created_at=created_at or datetime.now(UTC),
    )


class TestProcessTradeEvent:
    async def test_announces_and_records_the_transaction(self, guild):
        store = trade_settings()
        channel = make_channel()
        cog = make_cog(store, channel=channel)

        await process_trade_event(cog, guild, trade_event(players=[player_update(111, "Wolves", WOLVES_GM)]))

        assert len(channel.sent) == 1
        assert store["AnnouncedTrades"] == [55123]

    async def test_replayed_transaction_is_not_announced_twice(self, guild):
        store = trade_settings(AnnouncedTrades=[55123])
        channel = make_channel()
        cog = make_cog(store, channel=channel)

        await process_trade_event(cog, guild, trade_event(players=[player_update(111, "Wolves", WOLVES_GM)]))

        assert channel.sent == []

    async def test_event_from_another_league_is_ignored(self, guild):
        """`IncludeGlobal` scopes by guild, so foreign-league events can arrive."""
        store = trade_settings()
        channel = make_channel()
        cog = make_cog(store, channel=channel)

        await process_trade_event(cog, guild, trade_event(league=999, players=[player_update(111, "W", WOLVES_GM)]))

        assert channel.sent == []
        assert store["AnnouncedTrades"] == []

    async def test_stale_event_is_not_announced(self, guild):
        store = trade_settings()
        channel = make_channel()
        cog = make_cog(store, channel=channel)
        old = datetime.now(UTC) - TRADE_ANNOUNCE_MAX_AGE - timedelta(minutes=1)

        await process_trade_event(cog, guild, trade_event(created_at=old, players=[player_update(111, "W", WOLVES_GM)]))

        assert channel.sent == []

    async def test_announcements_disabled_skips_the_send(self, guild):
        store = trade_settings(TradeAnnouncements=False)
        channel = make_channel()
        cog = make_cog(store, channel=channel)

        await process_trade_event(cog, guild, trade_event(players=[player_update(111, "W", WOLVES_GM)]))

        assert channel.sent == []
        assert store["AnnouncedTrades"] == []

    async def test_non_trade_transaction_is_ignored(self, guild):
        store = trade_settings()
        channel = make_channel()
        cog = make_cog(store, channel=channel)

        await process_trade_event(cog, guild, trade_event(ttype="CUT", players=[player_update(111, "W", WOLVES_GM)]))

        assert channel.sent == []

    async def test_unparseable_payload_reports_and_refetches(self, guild):
        store = trade_settings()
        cog = make_cog(store, channel=make_channel())
        cog.transaction_history_by_id = AsyncMock(side_effect=Exception("boom"))

        event = LeagueEventData(
            id=1,
            league=LEAGUE_ID,
            category="TRN",
            action="PTR",
            object_id=55123,
            payload={"transaction": "not a dict"},
            created_at=datetime.now(UTC),
        )
        # Must not raise - the poller relies on handlers failing quietly.
        await process_trade_event(cog, guild, event)

        assert cog._try_post_embeds.await_count == 1

    async def test_mentions_are_restricted_to_users(self, guild):
        store = trade_settings()
        channel = make_channel()
        cog = make_cog(store, channel=channel)

        await process_trade_event(cog, guild, trade_event(players=[player_update(111, "W", WOLVES_GM)]))

        mentions = channel.sent[0]["allowed_mentions"]
        assert mentions.users is True
        assert mentions.everyone is False
        assert mentions.roles is False


class TestApplyTradeRoleUpdates:
    async def test_missing_member_is_reported_not_raised(self, guild):
        cog = make_cog(trade_settings())
        resp = response(players=[player_update(111, "Wolves", WOLVES_GM)])

        errors = await apply_trade_role_updates(cog, guild, resp)

        assert len(errors) == 1
        assert "not in the server" in errors[0]

    async def test_player_without_discord_id_is_reported(self, guild):
        cog = make_cog(trade_settings())
        resp = response(players=[player_update(None, "Wolves", WOLVES_GM)])

        errors = await apply_trade_role_updates(cog, guild, resp)

        assert len(errors) == 1
        assert "Discord ID" in errors[0]

    async def test_pick_only_trade_needs_no_role_work(self, guild):
        cog = make_cog(trade_settings())
        resp = response(picks=[pick_trade("Solar Flares", FLARES_GM)])

        assert await apply_trade_role_updates(cog, guild, resp) == []


class TestAnnounceTrade:
    async def test_returns_none_when_channel_is_unconfigured(self, guild):
        cog = make_cog(trade_settings(), channel=None)
        resp = response(players=[player_update(111, "Wolves", WOLVES_GM)])

        assert await announce_trade(cog, guild, resp) is None

    async def test_content_is_cleared_after_pinging(self, guild):
        channel = make_channel()
        cog = make_cog(trade_settings(), channel=channel)
        resp = response(players=[player_update(111, "Wolves", WOLVES_GM)])

        msg = await announce_trade(cog, guild, resp)

        assert channel.sent[0]["content"]
        assert msg is not None
        msg.edit.assert_awaited_once()
        assert msg.edit.await_args.kwargs["content"] is None
