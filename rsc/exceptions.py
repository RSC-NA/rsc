import json
import logging
from collections.abc import Collection, Mapping
from typing import Any, ClassVar

from rscapi.exceptions import ApiException

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

    _by_status: ClassVar[dict[int, type["ApiError"]]] = {}
    _by_error_type: ClassVar[dict[str, type["ApiError"]]] = {}

    def __init_subclass__(cls, *, statuses: Collection[int] = (), error_type: str | None = None, **kwargs: object):
        super().__init_subclass__(**kwargs)
        for status in statuses:
            ApiError._by_status[status] = cls
        if error_type is not None:
            ApiError._by_error_type[error_type] = cls

    def __init__(self, status: int, message: str, *, error_type: str | None = None, extra: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.message: str = message
        self.status = status
        self.error_type = error_type
        self.extra: dict[str, Any] = dict(extra or {})

    @classmethod
    def from_exception(cls, exc: ApiException) -> "ApiError":
        envelope = _json_object(exc.body)
        message = envelope.get("message") or exc.reason or "The RSC API returned an error without a message."
        error_type = envelope.get("type")
        error_type = error_type if isinstance(error_type, str) else None
        extra = envelope.get("extra")
        error_cls = cls._by_error_type.get(error_type or "") or cls._by_status.get(exc.status) or ApiError
        return error_cls(
            exc.status or 0,
            message if isinstance(message, str) else str(message),
            error_type=error_type,
            extra=extra if isinstance(extra, Mapping) else None,
        )

    def __str__(self) -> str:
        parts = [f"[{self.status}]"]
        if self.error_type:
            parts.append(f"{self.error_type}:")
        parts.append(self.message)
        if self.extra:
            parts.append(f"(extra: {self.extra})")
        return " ".join(parts)


def _json_object(body: str | None) -> dict[str, Any]:
    if not body:
        return {}
    try:
        parsed = json.loads(body)
    except ValueError:
        log.warning(f"RSC API sent an error body that is not JSON: {body[:200]!r}")
        return {}
    return parsed if isinstance(parsed, dict) else {}


class NotFoundError(ApiError, statuses={404}):
    """The RSC API has no such record"""


class ConflictError(ApiError, statuses={409}):
    """The request conflicts with the record's current state"""


class ServerError(ApiError, statuses=range(500, 600)):
    """The RSC API failed on its side"""


class SignupsClosedError(ApiError, error_type="SignupsClosedException"):
    """The season is not taking signups right now"""


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
