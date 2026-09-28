from pydantic import BaseModel
from rsc.combines.models import CombineEvent, CombineEventType, CombinesLobby


class DevLeagueStatus(BaseModel):
    checked_in: bool
    error: str | None
    player: str
    rsc_id: str
    tier: str


class DevLeagueCheckInOut(BaseModel):
    error: str | None
    success: str | None


# Game lobby webhooks share the combines payload shape.
DevLeagueLobby = CombinesLobby
DevLeagueEvent = CombineEvent
DevLeagueEventType = CombineEventType
