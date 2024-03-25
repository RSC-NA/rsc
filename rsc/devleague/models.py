from pydantic import BaseModel


class DevLeagueStatus(BaseModel):
    checked_in: bool
    error: str | None
    player: str
    rsc_id: str
    tier: str


class DevLeagueCheckInOut(BaseModel):
    error: str | None
    success: str | None
