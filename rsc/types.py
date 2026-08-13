from dataclasses import dataclass
from typing import TypedDict

import discord
import math
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
            return (
                self.trophy == other.trophy
                and self.star == other.star
                and self.devleague == other.devleague
                and self.combine_cup == other.combine_cup
            )
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.trophy, self.star, self.devleague, self.combine_cup))

    def __gt__(self, other: object):
        if isinstance(other, int):
            return self.total > other
        if isinstance(other, Accolades):
            return self.total > other.total
        return NotImplemented

    def __lt__(self, other: object):
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

    def __le__(self, other: object):
        if isinstance(other, int):
            return self.total <= other
        if isinstance(other, Accolades):
            return self.total <= other.total
        return NotImplemented


class AdminSettings(TypedDict):
    ActivityCheckMissingRole: discord.Role | None
    ActivityCheckMsgId: int | None
    ActivityCheckDmLastSeason: int | None
    ActivityCheckDmLastRun: int | None  # unix timestamp, rendered with discord <t:> markup
    ActivityCheckDmLastExecutor: int | None
    AgmMessage: str | None
    Dates: str | None
    IntentChannel: discord.TextChannel | None
    IntentMissingRole: discord.Role | None
    IntentMissingMsg: str | None
    IntentDmLastSeason: int | None
    IntentDmLastRun: int | None  # unix timestamp, rendered with discord <t:> markup
    IntentDmLastExecutor: int | None
    PermFAChannel: int | None
    PermFAMsgIds: list[int] | None
    RetireAuditEnabled: bool


class CombineSettings(TypedDict):
    Active: bool
    CombinesApi: str | None
    CombinesCategory: discord.CategoryChannel | None


class LLMSettings(TypedDict):
    LLMActive: bool
    LLMBlacklist: list[discord.TextChannel] | None
    OpenAIKey: str | None
    OpenAIOrg: str | None
    # Spend controls. The league is funded personally, so the agent is capped
    # per user and per guild rather than left open-ended.
    LLMUserCooldown: int
    LLMUserDailyCap: int
    LLMGuildDailyCap: int
    LLMPublicAsk: bool


class LLMUsageRecord(TypedDict):
    """Per-day question and token counts, keyed by (guild id, user id).

    Persisted rather than held in memory because an in-memory counter resets on
    every cog reload, which is exactly when someone who had hit their cap would
    try again.
    """

    day: str | None
    count: int
    tokens: int


class TransactionSettings(TypedDict):
    """Transaction channel configuration.

    The three `Trade*` keys govern what the bot does when the API reports a trade
    performed through the web UI (a `PTR` league event). Announcements and role
    updates get separate switches because the role/nickname half is destructive:
    it drives edits to real members from an external system.

    `AnnouncedTrades` is a bounded ring of transaction ids already announced. It
    is the only guard that survives a cursor rewind or a poll batch re-running
    after a reload, so it must be persisted.
    """

    TransChannel: discord.TextChannel | None
    TransDMs: bool
    TransLogChannel: discord.TextChannel | None
    TransNotifications: bool
    TransGMNotifications: bool
    TransRole: discord.Role | None
    CutMessage: str | None
    ContractExpirationMessage: str | None
    Substitutes: list[Substitute]
    TradeAnnouncements: bool
    TradeRoleUpdates: bool
    AnnouncedTrades: list[int]


class EventSettings(TypedDict):
    """Per guild configuration for the league event poller.

    `ConfirmedId` is a lagged watermark, not a simple "last seen id". Postgres
    hands out sequence values before commit, so a lower id can become visible
    after a higher one was already read. `SeenIds` holds ids above the watermark
    that were already processed and must be persisted, otherwise a restart
    replays the lag window into the log channel.

    Filters store enum *values* (`"TRN"`), never names.
    """

    EventsEnabled: bool
    EventChannel: int | None
    EventInterval: int
    ConfirmedId: int
    ConfirmedCreatedAt: str | None
    SeenIds: list[int]
    CategoryFilter: list[str]
    ActionFilter: list[str]
    SeverityFilter: list[str]
    IncludePrivate: bool
    IncludeGlobal: bool
    TotalProcessed: int


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
