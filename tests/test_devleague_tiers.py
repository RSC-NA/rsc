import pytest

from rsc.devleague.tiers import (
    UNKNOWN_TIER_RANK,
    channel_sort_key,
    lobby_channel_name,
    parse_lobby_channel,
    tier_rank,
    tier_slug,
)


@pytest.mark.parametrize(
    ("tier", "slug"),
    [("S+", "splus"), ("S", "s"), ("A", "a"), ("f", "f"), (" B ", "b")],
)
def test_tier_slug(tier, slug):
    assert tier_slug(tier) == slug


def test_tier_rank_orders_splus_to_f():
    tiers = ["F", "C", "S", "A", "S+", "E", "D", "B"]
    assert sorted(tiers, key=tier_rank) == ["S+", "S", "A", "B", "C", "D", "E", "F"]


def test_tier_rank_accepts_slug():
    assert tier_rank("splus") == tier_rank("S+")


@pytest.mark.parametrize("tier", ["veteran", "", "S++"])
def test_unknown_tier_sorts_last(tier):
    assert tier_rank(tier) == UNKNOWN_TIER_RANK
    assert tier_rank(tier) > tier_rank("F")


def test_channel_name_round_trip():
    name = lobby_channel_name("S+", 42, "home")
    assert name == "splus-42-home"
    assert parse_lobby_channel(name) == ("splus", 42, "home")


@pytest.mark.parametrize("name", ["general", "S+-42-home", "a-42-lobby", "a-x-home", "veteran-81"])
def test_parse_ignores_non_game_channels(name):
    assert parse_lobby_channel(name) is None
    assert channel_sort_key(name) is None


def test_sort_key_orders_tier_then_id_then_side():
    names = ["b-3-away", "splus-9-home", "b-3-home", "a-5-home", "b-1-home", "splus-9-away"]
    assert sorted(names, key=channel_sort_key) == [
        "splus-9-home",
        "splus-9-away",
        "a-5-home",
        "b-1-home",
        "b-3-home",
        "b-3-away",
    ]
