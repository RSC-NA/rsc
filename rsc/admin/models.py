from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from rsc.enums import MatchFormat, MatchType


@dataclass
class BulkRetireResult:
    """Per-player outcomes of a batch retire. Failures are collected, never raised."""

    retired: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


@dataclass
class DepartedReport:
    """League players who are active in the API but no longer in the discord server.

    `departed` only ever holds IDs Discord positively confirmed as gone via a
    `fetch_member` NotFound. `lookup_failed` is the "could not tell" bucket and is
    never actionable. `aborted` being set means a guardrail tripped and the run is
    not trustworthy -- report it and act on nobody.
    """

    departed: list[int] = field(default_factory=list)
    lookup_failed: list[int] = field(default_factory=list)
    labels: dict[int, str] = field(default_factory=dict)
    total_active: int = 0
    aborted: str | None = None


class CreateMatchData(BaseModel):
    day: int
    match_type: MatchType = Field(alias="type")
    match_format: MatchFormat = Field(alias="format")
    home_team: str = Field(alias="home")
    away_team: str = Field(alias="away")
