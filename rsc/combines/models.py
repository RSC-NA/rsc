from datetime import datetime

from pydantic import BaseModel


class CombinesStatus(BaseModel):
    status: str
    message: str


class CombinesPlayerLobbyInfo(BaseModel):
    id: int
    match_dtg: datetime
    season: int
    lobby_user: str
    lobby_pass: str
    home_wins: int
    away_wins: int
    reported_rsc_id: str | None
    confirmed_rsc_id: str | None
    completed: bool
    cancelled: bool
    rsc_id: str
    team: str


class CombinesPlayer(BaseModel):
    discord_id: int
    rsc_id: str
    match_id: int
    team: str
    name: str


class CombinesLobby(BaseModel):
    id: int
    lobby_user: str
    lobby_pass: str
    home_wins: int
    away_wins: int
    reported_rsc_id: str | None
    confirmed_rsc_id: str | None
    completed: bool
    cancelled: bool
    home: list[CombinesPlayer]
    away: list[CombinesPlayer]
