import pytest

from rsc.devleague.tiers import lobby_channel_name
from rsc.lobbies.channels import is_lobby_channel, parse_lobby_channel


@pytest.mark.parametrize(
    ("name", "parsed"),
    [
        # Combines keeps the tier as sent
        ("Premier-101-home", ("Premier", 101, "home")),
        ("Elite-4812-away", ("Elite", 4812, "away")),
        # Dev League uses a slug
        ("splus-101-home", ("splus", 101, "home")),
        ("f-2684-away", ("f", 2684, "away")),
        # Tiers outside the letter scheme still parse, so their lobbies tear down
        ("tier2-101-home", ("tier2", 101, "home")),
        ("a--101-home", ("a-", 101, "home")),
        ("dev 1-101-away", ("dev 1", 101, "away")),
    ],
)
def test_parses_both_naming_styles(name, parsed):
    assert parse_lobby_channel(name) == parsed


@pytest.mark.parametrize(
    "name",
    ["general", "combines-waiting-room-1", "a-42-lobby", "a-x-home", "veteran-81", "-101-home", "101-home", "a-101-home-2"],
)
def test_non_lobby_channels_do_not_parse(name):
    assert parse_lobby_channel(name) is None


@pytest.mark.parametrize("tier", ["S+", "A", "Tier 2", "A-"])
def test_dev_league_names_round_trip(tier):
    for side in ("home", "away"):
        parsed = parse_lobby_channel(lobby_channel_name(tier, 42, side))
        assert parsed is not None
        assert parsed[1:] == (42, side)


class TestIsLobbyChannel:
    @pytest.mark.parametrize("name", ["Elite-1-home", "splus-1-away"])
    def test_matches_its_own_channels(self, name):
        assert is_lobby_channel(name, 1)

    @pytest.mark.parametrize("name", ["Elite-101-home", "Elite-11-away", "splus-4801-home", "Elite-10-home", "1-home"])
    def test_another_lobby_whose_id_ends_or_starts_the_same_does_not_match(self, name):
        assert not is_lobby_channel(name, 1)
