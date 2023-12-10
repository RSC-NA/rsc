from enum import StrEnum, IntEnum

class ModActionType(StrEnum):
     MUTE = "MUTE"
     KICK = "KICK"
     BAN = "BAN"

class BulkRoleAction(StrEnum):
    ADD = "add"
    REMOVE = "remove"

class LogLevel(StrEnum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    DEBUG = "DEBUG"


class StatsType(StrEnum):
    REGULAR = "REG"  # Regular Season Stats
    POSTSEASON = ("PST",)  # Post Season Stats


class MatchType(StrEnum):
    REGULAR = "REG"  # Regular Season
    PRESEASON = "PRE"  # Pre-season
    POSTSEASON = "PST"  # Post-Season
    FINALS = "FNL"  # Finals


class MatchFormat(StrEnum):
    GAME_SERIES = "GMS"  # Game Series
    BEST_OF_THREE = "BO3"  # Best of Three
    BEST_OF_FIVE = "BO5"  # Best of Five
    BEST_OF_SEVEN = "BO7"  # Best of Seven


class Division(StrEnum):
    OCEAN = "O"  # Ocean
    MOUNTAIN = "M"  # Mountain
    EMBER = "E"  # Ember
    CLOUD = "C"  # Cloud
    NONE = "N"  # None


class Conference(StrEnum):
    LUNAR = "L"  # Lunar
    SOLAR = "S"  # Solar
    NONE = "N"  # None


class DaysOfWeek(IntEnum):
    MONDAY = 0  # Monday
    TUESDAY = 1  # Tuesday
    WEDNESDAY = 2  # Wednesday
    THURSDAY = 3  # Thursday
    FRIDAY = 4  # Friday
    SATURDAY = 5  # Saturday
    SUNDAY = 6  # Sunday
    FLEX = -1  # Flex Scheduling


class APIKeyInfo(StrEnum):
    ADMIN = "A"  # Admin
    BOT = "B"  # Bot
    DEVELOPER = "D"  # Developer


class StaffPositions(StrEnum):
    TM = "TM"  # Transactions
    STATS = "STATS"  # Stats
    EVENTS = "EVENTS"  # Events
    NUMBERS = "NUMS"  # Numbers
    MEDIA = "MEDIA"  # Media
    DEVELOPMENT = "DEV"  # Development
    ADMIN = "ADM"  # Admin
    STAFF = "STAFF"  # Staff
    MMR = "MMR"  # MMR Puller


class Status(StrEnum):
    DRAFT_ELIGIBLE = "DE"  # Draft Eligible
    FREE_AGENT = "FA"  # Free Agent
    ROSTERED = "RO"  # Rostered
    IR = "IR"  # Inactive Reserve
    WAIVERS = "WV"  # Waivers
    AGMIR = "AR"  # AGM IR
    FORMER = "FR"  # Former
    BANNED = "BN"  # Banned
    UNSIGNED_GM = "UG"  # GM (Unsigned)
    PERM_FA = "PF"  # Permanent Free Agent
    WAIVER_CLAIM = ("WC",)  # Waiver Claim

    @property
    def full_name(self) -> str:
        match self:
            case Status.DRAFT_ELIGIBLE:
                return "Draft Eligible"
            case Status.FREE_AGENT:
                return "Free Agent"
            case Status.ROSTERED:
                return "Rostered"
            case Status.IR:
                return "Inactive Reserve"
            case Status.WAIVERS:
                return "Waivers"
            case Status.AGMIR:
                return "AGM IR"
            case Status.FORMER:
                return "Former Player"
            case Status.BANNED:
                return "Banned"
            case Status.UNSIGNED_GM:
                return "Unsigned GM"
            case Status.PERM_FA:
                return "Permanent FA"
            case Status.WAIVER_CLAIM:
                return "Waiver Claim"
            case _:
                return "Unknown"


class TransactionWeek(StrEnum):
    OFFSEASON = "OFF"  # Offseason
    PRESEASON = "PRE"  # Preseason
    REGULAR = "REG"  # Regular Season


class TransactionType(StrEnum):
    NONE = "NON"  # Invalid Transaction
    CUT = "CUT"  # Cut
    PICKUP = "PKU"  # Pickup
    TRADE = "TRD"  # Trade
    SUBSTITUTION = "SUB"  # Substitution
    TEMP_FA = "TMP"  # Temporary Free Agent
    PROMOTION = "PRO"  # Promotion
    RELEGATION = "RLG"  # Relegation
    RESIGN = "RES"  # Re-sign
    INACTIVE_RESERVE = "IR"  # Inactive Reserve
    RETIRE = "RET"  # Retire
    WAIVER_RELEASE = "WVR"  # Waiver Release
    AGM_IR = "AIR"  # AGM Inactive Reserve
    DRAFT = "DFT"  # Draft Player

    @property
    def full_name(self) -> str:
        return self.name.replace("_", " ").title()


class MMRPullType(StrEnum):
    SEASON = "SN"  # Season
    HISTORY = "HS"  # Historical


class TrackerLinksStatus(StrEnum):
    NEW = "NEW"  # New
    STALE = "STL"  # Stale
    PULLED = "PLD"  # Pulled
    FAILED = "FLD"  # Failed

    @property
    def full_name(self) -> str:
        return self.name.capitalize()

class MatchTeamEnum(StrEnum):
    HOME = "HME"  # Home
    AWAY = "AWY"  # Away
    ALL = "ALL"  # All Games

    @property
    def full_name(self) -> str:
        return self.name.capitalize()

class SubStatus(IntEnum):
    NOT = 0  # Not subbed
    OUT = 1  # Subbed Out
    IN = 2  # Subbed In


class RegionPreference(StrEnum):
    EAST = ("EST",)  # US East
    WEST = ("WST",)  # US West
    EU = ("EU",)  # Europe

    @property
    def full_name(self) -> str:
        return self.name.capitalize()
