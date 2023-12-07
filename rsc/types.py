from typing import TypedDict


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
    gm: int
    player_in: int
    player_out: int
    team: str
    tier: str
