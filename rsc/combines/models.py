from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class CombineStatusType(StrEnum):
    Success = "success"
    Error = "error"


class CombineEventType(StrEnum):
    InvalidScore = "Invalid Score"
    ScoreMismatch = "Score Report Mismatch"
    Finished = "Finished Game"
    ScoreReported = "Reported Score"
    GameComplete = "Game Complete"
    CheckIn = "Checked In"


class CombineActor(BaseModel):
    nickname: str
    discord_id: int


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
    tier: str
    guild_id: int = Field(strict=False)
    home: list[CombinesPlayer]
    away: list[CombinesPlayer]


class CombineEvent(BaseModel):
    actor: CombineActor
    status: str
    message_type: CombineEventType
    message: str
    match_id: int | None
    guild_id: int = Field(strict=False)
