from rsc.const import TROPHY_EMOJI, DEV_LEAGUE_EMOJI, STAR_EMOJI
from dataclasses import dataclass


from typing import TypedDict, NewType

class RebrandTeamDict(TypedDict):
    name: str
    tier: str
    tier_id: int


class CheckIn(TypedDict):
    """
    Free Agent Check In

    date: String of datetime() indicating when the player checked in
    player: Discord ID of the player
    tier: Tier name
    """

    date: str
    player: int
    tier: str


class Substitute(TypedDict):
    date: str
    franchise: str
    gm: int
    player_in: int
    player_out: int
    team: str
    tier: str


class ThreadGroup(TypedDict):
    category: int
    role: int


@dataclass
class Accolades:
    trophy: int
    star: int
    devleague: int

    @property
    def total(self) -> int:
        return self.trophy + self.star + self.devleague

    def __str__(self) -> str:
        return f"{TROPHY_EMOJI * self.trophy}{STAR_EMOJI * self.star}{DEV_LEAGUE_EMOJI * self.devleague}"

    def __eq__(self, other):
        if isinstance(other, int):
            return self.total == other
        if isinstance(other, Accolades):
            return self.total == other.total
        return NotImplemented

    def __gt__(self, other):
        if isinstance(other, int):
            return self.total > other
        if isinstance(other, Accolades):
            return self.total > other.total
        return NotImplemented

    def __lt(self, other):
        if isinstance(other, int):
            return self.total < other
        if isinstance(other, Accolades):
            return self.total < other.total
        return NotImplemented

    def __ge__(self, other):
        if isinstance(other, int):
            return self.total >= other
        if isinstance(other, Accolades):
            return self.total >= other.total
        return NotImplemented

    def __le(self, other):
        if isinstance(other, int):
            return self.total <= other
        if isinstance(other, Accolades):
            return self.total <= other.total
        return NotImplemented