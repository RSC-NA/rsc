from dataclasses import dataclass
from typing import TypedDict

import ballchasing
import discord
import math
from rscapi.models.match import Match

from rsc.const import DEV_LEAGUE_EMOJI, STAR_EMOJI, TROPHY_EMOJI, COOKIE_EMOJI, COMBINE_CUP_EMOJI


# Number of dev league trophies before conversion to cookie
COOKIE_COUNT = 4


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
    visible: bool


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
    trophy: int = 0
    star: int = 0
    devleague: int = 0
    combine_cup: int = 0

    @property
    def total(self) -> int:
        return self.trophy + self.star + self.devleague + self.combine_cup

    def __str__(self) -> str:
        dev_count = self.devleague % 4
        cookie_count = math.floor(self.devleague / 4)

        return (
            f"{TROPHY_EMOJI * self.trophy}"
            f"{STAR_EMOJI * self.star}"
            f"{DEV_LEAGUE_EMOJI * dev_count}"
            f"{COOKIE_EMOJI * cookie_count}"
            f"{COMBINE_CUP_EMOJI * self.combine_cup}"
        )

    def __eq__(self, other: object):
        if isinstance(other, int):
            return self.total == other
        if isinstance(other, Accolades):
            return self.total == other.total
        return NotImplemented

    def __gt__(self, other: object):
        if isinstance(other, int):
            return self.total > other
        if isinstance(other, Accolades):
            return self.total > other.total
        return NotImplemented

    def __lt(self, other: object):
        if isinstance(other, int):
            return self.total < other
        if isinstance(other, Accolades):
            return self.total < other.total
        return NotImplemented

    def __ge__(self, other: object):
        if isinstance(other, int):
            return self.total >= other
        if isinstance(other, Accolades):
            return self.total >= other.total
        return NotImplemented

    def __le(self, other: object):
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
    PermFAChannel: int | None
    PermFAMsgIds: list[int] | None


class CombineSettings(TypedDict):
    Active: bool
    CombinesApi: str | None
    CombinesCategory: discord.CategoryChannel | None


class LLMSettings(TypedDict):
    LLMActive: bool
    LLMBlacklist: list[discord.TextChannel] | None
    OpenAIKey: str | None
    OpenAIOrg: str | None
    SimilarityCount: int
    SimilarityThreshold: float


class TransactionSettings(TypedDict):
    TransChannel: discord.TextChannel | None
    TransDMs: bool
    TransLogChannel: discord.TextChannel | None
    TransNotifications: bool
    TransGMNotifications: bool
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
