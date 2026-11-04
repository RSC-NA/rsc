import logging
from collections.abc import Collection, Mapping
from typing import Any, ClassVar

from rscapi.exceptions import ApiException
from rscapi.models.error import Error
from rscapi.models.error_code_enum import ErrorCodeEnum

log = logging.getLogger("red.rsc.exceptions")


class RscException(Exception):  # noqa: N818
    """Base exception type for RSC Bot"""

    def __init__(self, message: str | None = None):
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message or self.__doc__ or type(self).__name__


class LeagueNotConfigured(RscException):
    """Guild does not have a league configured"""


class SiteUnavailable(RscException):
    """The combines or Dev League site couldn't be reached, or sent back something unusable"""


class ApiError(RscException):
    """The RSC API answered a request with an error."""

    _by_code: ClassVar[dict[ErrorCodeEnum, type["ApiError"]]] = {}
    _by_status: ClassVar[dict[int, type["ApiError"]]] = {}

    def __init_subclass__(cls, *, codes: Collection[ErrorCodeEnum] = (), statuses: Collection[int] = (), **kwargs: object):
        super().__init_subclass__(**kwargs)
        for code in codes:
            ApiError._by_code[code] = cls
        for status in statuses:
            ApiError._by_status[status] = cls

    def __init__(self, status: int, message: str, *, code: ErrorCodeEnum | None = None, extra: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.message: str = message
        self.status = status
        self.code = code
        self.extra: dict[str, Any] = dict(extra or {})

    @classmethod
    def from_exception(cls, exc: ApiException) -> "ApiError":
        status = exc.status or 0
        if isinstance(exc.data, Error):
            error_cls = cls._by_code.get(exc.data.code) or cls._by_status.get(status) or ApiError
            return error_cls(status, exc.data.message, code=exc.data.code, extra=exc.data.extra)

        if exc.body:
            log.warning(f"RSC API sent an error body that is not its error envelope: {exc.body[:200]!r}")
        error_cls = cls._by_status.get(status) or ApiError
        return error_cls(status, exc.reason or "The RSC API returned an error without a message.")

    def __str__(self) -> str:
        parts = [f"[{self.status}]"]
        if self.code:
            parts.append(f"{self.code.value}:")
        parts.append(self.message)
        if self.extra:
            parts.append(f"(extra: {self.extra})")
        return " ".join(parts)


class NotFoundError(ApiError, statuses={404}):
    """The RSC API has no such record"""


class ConflictError(ApiError, statuses={409}):
    """The request conflicts with the record's current state"""


class ServerError(ApiError, statuses=range(500, 600)):
    """The RSC API failed on its side"""


class SignupsClosedError(ApiError, codes={ErrorCodeEnum.SIGNUPS_CLOSED}):
    """The season is not taking signups right now"""


class PlayerNotInLeagueError(ApiError, codes={ErrorCodeEnum.PLAYER_NOT_IN_LEAGUE}):
    """The player is already out of the league"""


# Discord


class DiscordNameTooLong(ValueError):  # noqa: N818
    """A member's RSC name and prefix do not fit in a discord nickname.

    A data problem (the API name is too long), not a bug, so callers can report
    it and keep going instead of aborting a sync. Subclasses `ValueError` so the
    existing `except ValueError` handling still catches it.
    """

    def __init__(self, member_id: int, nickname: str):
        self.member_id = member_id
        self.nickname = nickname
        super().__init__(f"Discord name is too long ({member_id}): {nickname}")


# Transactions


class TradeParserException(RscException):
    """Error occurred during trade parsing"""


class MalformedTransactionResponse(RscException):
    """TransactionResponse did not contain expected data"""
