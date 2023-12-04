import json
import logging
from rscapi.exceptions import ApiException as RscApiException

log = logging.getLogger("red.rsc.exceptions")


async def translate_api_error(exc: RscApiException):
    log.debug(f"ApiException Status: {exc.status}")
    if exc.status == 500:
        raise InternalServerError(response=exc)

    if not exc.body:
        raise RscException(response=exc)

    log.debug(f"ApiException Body: {exc.body}")
    body = json.loads(exc.body)
    reason = body.get("detail", None)

    if not reason:
        raise RscException(response=exc)

    # TransactionsExceptions
    if reason.startswith("Cannot cut a player past the transactions end date for"):
        raise PastTransactionsEndDate(response=exc)
    elif reason.startswith("Unable to find team name "):
        raise TeamDoesNotExist(response=exc)
    elif reason.startswith("Cannot admin override transaction for league you are not an admin in"):
        raise NotAdmin(response=exc)
    elif reason.startswith("Cannot cut a player during the offseason, reason was:"):
        raise NotAllowedInOffseason(response=exc)
    elif reason.startswith("Player cannot be cut as they are not finished their IR period yet."):
        raise MustFinishIRPeriod(response=exc)
    elif reason == "Cut is past the offseason cut deadline.":
        raise PastOffseasonDeadline(response=exc)
    elif reason.startswith("Player cannot be cut until"):
        raise NotEnoughMatchDays(response=exc)
    elif reason.endswith(" is not currently playing this season."):
        raise NotLeaguePlayer(response=exc)

    # Default
    raise RscException(response=exc)
        





class RscException(Exception):
    """Base exception type for RSC Bot"""

    def __init__(self, *args, **kwargs):
        self.response = kwargs.pop("response", None)
        if self.response is not None and isinstance(self.response, RscApiException):
            self.status = self.response.status
            try:
                body = json.loads(self.response.body)
                self.reason = body.get("detail", None)
                self.type = body.get("type", None)
            except json.JSONDecodeError:
                log.error(f"Unable to JSON decode API exception body. Status: {self.status}")
                self.reason = "Received unknown error from server."
                self.type = "UnknownError"

        super().__init__(*args, **kwargs)

# Generic

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