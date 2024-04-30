from dataclasses import dataclass
from typing import TypedDict

import ballchasing
import discord
from rscapi.models.match import Match

from rsc.const import DEV_LEAGUE_EMOJI, STAR_EMOJI, TROPHY_EMOJI


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


class AdminSettings(TypedDict):
    ActivityCheckMsgId: int | None
    AgmMessage: str | None
    Dates: str | None
    IntentChannel: discord.TextChannel | None
    IntentMissingRole: discord.Role | None
    IntentMissingMsg: str | None


class CombineSettings(TypedDict):
    Active: bool
    CombinesApi: str | None
    CombinesCategory: discord.CategoryChannel | None


class LLMSettings(TypedDict):
    LLMActive: bool
    OpenAIKey: str | None
    OpenAIOrg: str | None
    SimilarityCount: int
    SimilarityThreshold: float


class TransactionSettings(TypedDict):
    TransChannel: discord.TextChannel | None
    TransDMs: bool
    TransLogChannel: discord.TextChannel | None
    TransNotifications: bool
    TransRole: discord.Role | None
    CutMessage: str | None
    ContractExpirationMessage: str | None
    Substitutes: list[Substitute]


class WelcomeSettings(TypedDict):
    WelcomeChannel: discord.TextChannel | None
    WelcomeMsg: str | None
    WelcomeRoles: list[discord.Role]
    WelcomeStatus: bool


class ModThreadSettings(TypedDict):
    PrimaryCategory: discord.CategoryChannel | None
    ManagementRole: discord.Role | None
    Groups: dict[str, ThreadGroup]


class NumbersSettings(TypedDict):
    NumbersRole: discord.Role | None


class BallchasingResult(TypedDict):
    valid: bool
    away_wins: int
    home_wins: int
    match: Match
    replays: set[ballchasing.models.Replay]
    execution_time: float
    link: str | None


class BallchasingCollisions(TypedDict):
    total_replays: int
    unknown: set[ballchasing.models.Replay]
    collisions: set[ballchasing.models.Replay]
