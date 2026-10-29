"""Lobby voice channel names, shared by combines and Dev League.

Every lobby gets a home and an away channel named `<tier>-<id>-<side>`. The tier
part differs: combines uses the tier as sent (`Premier-101-home`), Dev League a
lowercase slug (`splus-101-home`). Teardown finds a lobby's channels by parsing
the name, so any tier text is accepted here and the id is compared as a number.
"""

import re
from typing import Literal

Side = Literal["home", "away"]

LOBBY_CHANNEL_RE = re.compile(r"^(?P<tier>.+)-(?P<id>\d+)-(?P<side>home|away)$")


def parse_lobby_channel(name: str) -> tuple[str, int, Side] | None:
    """Split a lobby channel name into (tier, lobby id, side), or None if it isn't one."""
    match = LOBBY_CHANNEL_RE.match(name)
    if not match:
        return None
    side: Side = "home" if match["side"] == "home" else "away"
    return match["tier"], int(match["id"]), side


def is_lobby_channel(name: str, lobby_id: int) -> bool:
    """Whether `name` is one of `lobby_id`'s channels. Lobby 1 never matches lobby 101."""
    parsed = parse_lobby_channel(name)
    return parsed is not None and parsed[1] == lobby_id
