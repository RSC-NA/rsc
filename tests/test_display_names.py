"""Tests for recovering an RSC name from a Discord display name.

The bot writes nicknames as `f"{prefix} | {name} {accolades}"`. Anything that
looks a player up by name has to undo both ends first, and the counts quoted
here come from the 15,195 names the members endpoint returns.
"""

from unittest.mock import MagicMock

import discord
import pytest

from rsc import const
from rsc.utils.utils import (
    rsc_name_from_display_name,
    rsc_name_from_member,
    strip_franchise_prefix,
    strip_trailing_accolades,
)

TROPHY = const.TROPHY_EMOJI
STAR = const.STAR_EMOJI
CROWN = const.DEV_LEAGUE_EMOJI
COOKIE = const.COOKIE_EMOJI
CUP = const.COMBINE_CUP_EMOJI


@pytest.mark.parametrize(
    ("display_name", "expected"),
    [
        # The nickname shapes the bot itself writes.
        (f"RF | nickm {TROPHY}", "nickm"),
        ("TQD | FrostyBrew", "FrostyBrew"),
        ("FA | FrostyBrew", "FrostyBrew"),
        ("DE | someone", "someone"),
        (f"<0> | SavedHawk {STAR}{STAR}", "SavedHawk"),
        ("50 | slendxa", "slendxa"),
        (f"MV | Squashy {TROPHY}{STAR}{CROWN}{COOKIE}{CUP}", "Squashy"),
        # No prefix, no accolades.
        ("nickm", "nickm"),
        # Real RSC names that contain their own pipe. The segment before it is
        # too long to be a franchise prefix, so it stays.
        ("Santiago | Kreiker", "Santiago | Kreiker"),
        ("Pure | Rugged!", "Pure | Rugged!"),
        ("TyTy0804 | Bean King", "TyTy0804 | Bean King"),
        ("Bizonitax|Giveaway", "Bizonitax|Giveaway"),
        # Real RSC names that a general emoji sweep would destroy.
        ("アクム", "アクム"),
        ("𝚜𝚞", "𝚜𝚞"),
        ("Neb♡", "Neb♡"),
        ("Resonant ¯\\_(ツ)_/¯", "Resonant ¯\\_(ツ)_/¯"),
        (f"TQD | {STAR}Jaden_6{STAR}", f"{STAR}Jaden_6"),
    ],
)
def test_rsc_name_from_display_name(display_name: str, expected: str):
    assert rsc_name_from_display_name(display_name) == expected


def test_prefix_is_only_dropped_when_it_could_be_one():
    """A prefix is 2-3 characters with no whitespace in both leagues."""
    assert strip_franchise_prefix("TQD | FrostyBrew") == "FrostyBrew"
    assert strip_franchise_prefix("WILD | McTw1sted") == "WILD | McTw1sted"
    assert strip_franchise_prefix("Nick | GK") == "Nick | GK"


def test_accolades_only_come_off_the_end():
    """Nine RSC names carry an accolade emoji inside the name itself."""
    assert strip_trailing_accolades(f"nickm {TROPHY}{TROPHY}") == "nickm"
    assert strip_trailing_accolades(f"{CROWN}QueenTreehuggerr") == f"{CROWN}QueenTreehuggerr"
    assert strip_trailing_accolades(f"{TROPHY}(OFU-[shadoWslayer]-UWE){TROPHY}") == f"{TROPHY}(OFU-[shadoWslayer]-UWE)"


def test_a_nickname_with_no_name_left_falls_back_to_the_nickname():
    """An empty name filter matches every player in the league rather than none."""
    assert strip_trailing_accolades(TROPHY) == ""
    assert rsc_name_from_display_name(f"TQD | {TROPHY}") == f"TQD | {TROPHY}"


def test_rsc_name_from_member_reads_the_nickname():
    member = MagicMock(spec=discord.Member)
    member.display_name = f"RF | nickm {TROPHY}"

    assert rsc_name_from_member(member) == "nickm"
