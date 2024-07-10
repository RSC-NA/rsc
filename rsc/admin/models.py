from pydantic import BaseModel, Field

from rsc.enums import MatchFormat, MatchType


class CreateMatchData(BaseModel):
    day: int
    match_type: MatchType = Field(alias="type")
    match_format: MatchFormat = Field(alias="format")
    home_team: str = Field(alias="home")
    away_team: str = Field(alias="away")
