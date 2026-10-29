import pytest

from rsc.devleague.tiers import (
    UNKNOWN_TIER_RANK,
    channel_sort_key,
    lobby_channel_name,
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


def test_channel_name_uses_the_slug():
    assert lobby_channel_name("S+", 42, "home") == "splus-42-home"


@pytest.mark.parametrize("name", ["general", "a-42-lobby", "a-x-home", "veteran-81"])
def test_non_game_channels_have_no_sort_key(name):
    assert channel_sort_key(name) is None


def _game_channel_key(name: str) -> tuple[int, int, bool]:
    key = channel_sort_key(name)
    assert key is not None, name
    return key


def test_sort_key_orders_tier_then_id_then_side():
    names = ["b-3-away", "splus-9-home", "b-3-home", "a-5-home", "b-1-home", "splus-9-away"]
    assert sorted(names, key=_game_channel_key) == [
        "splus-9-home",
        "splus-9-away",
        "a-5-home",
        "b-1-home",
        "b-3-home",
        "b-3-away",
    ]
