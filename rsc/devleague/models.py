from pydantic import BaseModel
from rsc.combines.models import CombineEvent, CombineEventType, CombinesLobby


class DevLeagueStatus(BaseModel):
    # An unknown player gets back only `error`, so every other field may be missing
    checked_in: bool = False
    error: str | None = None
    player: str | None = None
    rsc_id: str | None = None
    tier: str | None = None


class DevLeagueCheckInOut(BaseModel):
    error: str | None = None
    success: str | None = None


# Game lobby webhooks share the combines payload shape.
DevLeagueLobby = CombinesLobby
DevLeagueEvent = CombineEvent
DevLeagueEventType = CombineEventType
