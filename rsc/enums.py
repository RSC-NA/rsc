import logging
import math
from enum import IntEnum, StrEnum

log = logging.getLogger("red.rsc.enums")


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
    PERMFA_W = "PW"  # Permanent FA in Waiting
    WAIVER_CLAIM = "WC"  # Waiver Claim
    WAIVER_RELEASE = "WR"  # Waiver Release
    RENEWED = "RN"  # Renewed

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
            case Status.PERMFA_W:
                return "Permanent FA (Waiting)"
            case Status.WAIVER_CLAIM:
                return "Waiver Claim"
            case Status.WAIVER_RELEASE:
                return "Waiver Release"
            case Status.RENEWED:
                return "Renewed"
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
    PLAYER_TRADE = "PTD"  # Player Trade
    SUBSTITUTION = "SUB"  # Substitution
    TEMP_FA = "TMP"  # Temporary Free Agent
    PROMOTION = "PRO"  # Promotion
    RELEGATION = "RLG"  # Relegation
    RESIGN = "RES"  # Re-sign
    INACTIVE_RESERVE = "IR"  # Inactive Reserve
    RETIRE = "RET"  # Retire
    WAIVER_RELEASE = "WVR"  # Waiver Release
    AGM_IR = "AIR"  # AGM Inactive Reserve
    IR_RETURN = "IRT"  # IR Return
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


class IntentResponse:
    RETURN = ""
    NOT = ""


class SubStatus(IntEnum):
    NOT = 0  # Not subbed
    OUT = 1  # Subbed Out
    IN = 2  # Subbed In


class RegionPreference(StrEnum):
    EAST = "EST"  # US East
    WEST = "WST"  # US West
    EU = "EU"  # Europe

    @property
    def full_name(self) -> str:
        match self:
            case RegionPreference.EAST:
                return "US East"
            case RegionPreference.WEST:
                return "US West"
            case RegionPreference.EU:
                return "Europe"
            case _:
                raise ValueError(f"Unknown Region: {self}")


class PlayerType(StrEnum):
    NEW = "NEW"
    FORMER = "FORMER"


class Platform(StrEnum):
    STEAM = "STEAM"
    PLAYSTATION = "PS"
    XBOX = "XBOX"
    EPIC = "EPIC"
    SWITCH = "SWITCH"


class Referrer(StrEnum):
    REDDIT = "REDDIT"
    TWITCH = "TWITCH"
    FRIEND = "FRIEND"
    MLE = "MLE"
    BALLCHASING = "BALLCHASING"
    OTHER = "OTHER"


# Game Enums (originally for RapidApi which has been deprecated)


class RLStatType(StrEnum):
    ASSISTS = "Assists"
    GOALS = "Goals"
    MVPS = "MVPs"
    SAVES = "Saves"
    SHOTS = "Shots"
    WINS = "Wins"


class RLChallengeType(StrEnum):
    WEEKLY = "weekly"
    SEASON = "season"


class RLRegion(StrEnum):
    AE = "asia-east"
    AMAIN = "asia-se-mainland"
    AMARITIME = "asia-se-maritime"
    EU = "europe"
    INDIA = "india"
    MENA = "middle-east"
    OCE = "oceania"
    SAFRICA = "south-africa"
    SAMERICA = "south-america"
    USEAST = "us-east"
    USWEST = "us-west"


class RankedPlaylist(StrEnum):
    DUEL = "Duel (Ranked)"
    DOUBLES = "Doubles (Ranked)"
    STANDARD = "Standard (Ranked)"
    HOOPS = "Hoops"
    RUMBLE = "Rumble"
    DROPSHOT = "Dropshot"
    SNOWDAY = "Snow Day"


class RewardLevel(StrEnum):
    BRONZE = "Bronze"
    SILVER = "Silver"
    GOLD = "Gold"
    PLATINUM = "Platinum"
    DIAMOND = "Diamond"
    CHAMP = "Champion"
    GC = "Grand Champion"
    SSL = "Supersonic Legend"
    NONE = "None"


# Moderation


class StrikeType(IntEnum):
    MINOR = 0
    NORMAL = 1
    SERIOUS = 2
    OTHER = 3


class StrikePunishment(IntEnum):
    WARNING = 0  # "Warning"
    SHORT = 1  # "Short Timeout"
    TIMEOUT = 2  # "Standard timeout"
    LONG = 3  # "Long Timeout and 1 match suspension"
    EXTENDED = 4  # "Extended Timeout and 2 match suspension"
    SEVERE = 5  # "Severe timeout and 3 match suspension"
    SEASON = 6  # "7 day timeout and season suspension",
    ENFORCED = 7  # "14 day timeout"
    TRADE = 8  # "Banned from trade channel indefinitely"
    EVENT = 9  # "Indefinite ban from all RSC events"
    REMOVAL = 10  # "Removed from the relevant event and the next instance of it"
    BAN = 11  # Ban


# Other


class AnsiColor(IntEnum):
    BLACK = 30
    BLUE = 94
    CYAN = 96
    DARK_CYAN = 36
    GREEN = 32
    PUPLE = 95
    RED = 31
    YELLOW = 93

    def colored_text(self, content: str) -> str:
        return f"\u001b[0;{self.value}m{content}\u001b[0m"

    def bold_colored_text(self, content: str) -> str:
        return f"\u001b[1;{self.value}m{content}\u001b[0m"

    def underlined_colored_text(self, content: str) -> str:
        return f"\u001b[4;{self.value}m{content}\u001b[0m"

    @staticmethod
    def rgb_to_ansii256(hex: str) -> int:
        b = bytearray.fromhex(hex.lstrip("#"))
        if len(b) != 3:
            raise ValueError("Invalid RGB hex string")

        red = b[0]
        green = b[1]
        blue = b[2]
        log.debug(f"Red: {red} Green: {green} Blue: {blue}")

        if red == green and green == blue:
            if red < 8:
                log.debug("red < 8")
                return 16

            if red > 248:
                log.debug("red > 248")
                return 231

            log.debug("Other Red")
            return round((((red - 8) / 247) * 24) + 232)

        return (
            16
            + (36 * round(red / 255 * 5))
            + (6 * round(green / 255 * 5))
            + round(blue / 255 * 5)
        )

    @staticmethod
    def ansi256_to_ansi(code: int) -> int:
        log.debug(f"Code: {code}")
        if code < 8:
            return 30 + code

        if code < 16:
            return 90 + (code - 8)

        red: float = 0
        green: float = 0
        blue: float = 0

        if code >= 232:
            red = (((code - 232) * 10) + 8) / 255
            green = red
            blue = red
        else:
            code -= 16

            remainder = code % 36

            red = math.floor(code / 36) / 5
            green = math.floor(remainder / 6) / 5
            blue = (remainder % 6) / 5

        value = max(red, green, blue) * 2

        if value == 0:
            return 30

        result = 30 + ((round(blue) << 2) | (round(green) << 1) | round(red))

        if value == 2:
            result += 60

        return result

    @staticmethod
    def from_rgb_hex(hex: str, bold=False, underline=False) -> str:
        """Example input: #FFFFFF (Not functional TODO)"""
        aformat = 0

        a256code = AnsiColor.rgb_to_ansii256(hex)
        acode = AnsiColor.ansi256_to_ansi(a256code)

        log.debug(f"RGB -> Ansi Code: {acode}")

        if bold:
            aformat = 1
        elif underline:
            aformat = 4

        return f"\u001b[{aformat};{acode}m"
