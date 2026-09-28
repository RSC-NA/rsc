"""Dev League tier helpers.

Dev League tiers are letter grades: `S+`, `S`, `A`, `B`, ... `F`. `+` is not
channel-safe, so channel names use a lowercase slug (`S+` -> `splus`).
"""

import re
from typing import Literal

Side = Literal["home", "away"]

GAME_CHANNEL_RE = re.compile(r"^(?P<tier>[a-z]+)-(?P<id>\d+)-(?P<side>home|away)$")

# Rank for tiers that don't fit the letter scheme, so they sort after F.
UNKNOWN_TIER_RANK = 100


def tier_slug(tier: str) -> str:
    """Channel-safe tier name. `S+` -> `splus`, `A` -> `a`."""
    return tier.strip().lower().replace("+", "plus")


def tier_rank(tier: str) -> int:
    """Sort rank for a raw tier or its slug. Lower is higher tier: S+ < S < A < ... < F."""
    slug = tier_slug(tier)
    if slug == "splus":
        return 0
    if slug == "s":
        return 1
    if len(slug) == 1 and "a" <= slug <= "z":
        return 2 + (ord(slug) - ord("a"))
    return UNKNOWN_TIER_RANK


def lobby_channel_name(tier: str, lobby_id: int, side: Side) -> str:
    return f"{tier_slug(tier)}-{lobby_id}-{side}"


def parse_lobby_channel(name: str) -> tuple[str, int, Side] | None:
    """Split a game channel name into (tier slug, lobby id, side), or None if it isn't one."""
    match = GAME_CHANNEL_RE.match(name)
    if not match:
        return None
    side: Side = "home" if match["side"] == "home" else "away"
    return match["tier"], int(match["id"]), side


def channel_sort_key(name: str) -> tuple[int, int, bool] | None:
    """Ordering for game channels in a category: tier, then lobby id, home before away."""
    parsed = parse_lobby_channel(name)
    if not parsed:
        return None
    tier, lobby_id, side = parsed
    return tier_rank(tier), lobby_id, side == "away"
