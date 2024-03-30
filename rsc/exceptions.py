import json
import logging

from rscapi.exceptions import ApiException as RscApiException

log = logging.getLogger("red.rsc.exceptions")


async def translate_api_error(exc: RscApiException):
    log.debug(f"ApiException Status: {exc.status}")
    if exc.status == 500:
        return InternalServerError(response=exc)

    if not exc.body:
        return RscException(response=exc)

    log.debug(f"ApiException Body: {exc.body}")
    body = json.loads(exc.body)
    reason = body.get("detail")

    if not reason:
        return RscException(response=exc)

    # TransactionsExceptions
    if reason.startswith("Cannot cut a player past the transactions end date for"):
        return PastTransactionsEndDate(response=exc)
    elif reason.startswith("Unable to find team name "):
        return TeamDoesNotExist(response=exc)
    elif reason.startswith(
        "Cannot admin override transaction for league you are not an admin in"
    ):
        return NotAdmin(response=exc)
    elif reason.startswith("Cannot cut a player during the offseason, reason was:"):
        return NotAllowedInOffseason(response=exc)
    elif reason.startswith(
        "Player cannot be cut as they are not finished their IR period yet."
    ):
        return MustFinishIRPeriod(response=exc)
    elif reason == "Cut is past the offseason cut deadline.":
        return PastOffseasonDeadline(response=exc)
    elif reason.startswith("Player cannot be cut until"):
        return NotEnoughMatchDays(response=exc)
    elif reason.endswith(" is not currently playing this season."):
        return NotLeaguePlayer(response=exc)

    # Default
    return RscException(response=exc)


class RscException(Exception):
    """Base exception type for RSC Bot"""

    def __init__(self, *args, **kwargs):
        self.response = kwargs.pop("response", None)
        self.message = kwargs.pop("message", None)
        if self.response is not None and isinstance(self.response, RscApiException):
            self.status = self.response.status
            try:
                body = json.loads(self.response.body)
                self.reason = body.get("detail")
                self.type = body.get("type")
            except json.JSONDecodeError:
                log.error(
                    f"Unable to JSON decode API exception body. Status: {self.status}"
                )
                self.reason = "Received unknown error from server."
                self.type = "UnknownError"

        super().__init__(self.message, *args, **kwargs)


# Generic


class LeagueNotConfigured(RscException):
    """Guild does not have a league configured"""


class InternalServerError(RscException):
    """Server returned 500 Internal Server Error"""


# Member


class MemberException(RscException):
    """Generic Member Exception Base Type"""


class MemberDoesNotExist(MemberException):
    """Member does not exist"""


class NotLeaguePlayer(MemberException):
    """Member is not playing in the league this season"""


# League


class LeagueException(RscException):
    """Generic Transaction Exception Base Type"""


class LeagueDoesNotExist(LeagueException):
    """League does not exist"""


# Teams


class TeamsException(RscException):
    """Generic Teams Exception Base Type"""


class TeamDoesNotExist(TeamsException):
    """Team does not exist"""


# Transactions


class TransactionException(RscException):
    """Generic Transaction Exception Base Type"""


class TradeParserException(TransactionException):
    """Error occurred during trade parsing"""


class PastTransactionsEndDate(TransactionException):
    """Attempt to cut a player past the transactions end date"""


class NotAdmin(TransactionException):
    """Attempted admin override in a league that user is not an admin"""


class NotAllowedInOffseason(TransactionException):
    """Transaction is not allowed during the offseason"""


class MustFinishIRPeriod(TransactionException):
    """Player has not finished their IR period"""


class PastOffseasonDeadline(TransactionException):
    """Past offseason deadline"""


class NotEnoughMatchDays(TransactionException):
    """Not enough match days have passed"""


class MalformedTransactionResponse(TransactionException):
    """TransactionResponse did not contain expected data"""
