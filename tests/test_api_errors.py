from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rscapi.exceptions import ApiException
from rscapi.models.error_code_enum import ErrorCodeEnum
from tests.utils import api_error, api_exception, raw_api_exception

from rsc.embeds import ApiExceptionErrorEmbed
from rsc.exceptions import (
    ApiError,
    ConflictError,
    LeagueNotConfigured,
    NotFoundError,
    RscException,
    ServerError,
    SignupsClosedError,
)
from rsc.leagues.leagues import LeagueMixIn


def _league_mixin(guild_id: int) -> LeagueMixIn:
    saved = LeagueMixIn.__abstractmethods__
    LeagueMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(LeagueMixIn)
    finally:
        LeagueMixIn.__abstractmethods__ = saved
    m._api_conf = {guild_id: MagicMock()}
    return m


class TestApiClientBoundary:
    async def test_api_failure_reaches_the_caller_with_the_server_message(self, mock_guild):
        mixin = _league_mixin(mock_guild.id)
        mock_api = AsyncMock()
        mock_api.leagues_list.side_effect = api_exception(404, "League not found", code=ErrorCodeEnum.NOT_FOUND)

        with (
            patch("rsc.abc.ApiClient"),
            patch("rsc.leagues.leagues.LeaguesApi", return_value=mock_api),
            pytest.raises(NotFoundError) as caught,
        ):
            await mixin.leagues(mock_guild)

        assert caught.value.status == 404
        assert caught.value.message == "League not found"
        assert isinstance(caught.value.__cause__, ApiException)

    async def test_other_exceptions_pass_through_unchanged(self, mock_guild):
        mixin = _league_mixin(mock_guild.id)
        mock_api = AsyncMock()
        mock_api.leagues_list.side_effect = TimeoutError()

        with (
            patch("rsc.abc.ApiClient"),
            patch("rsc.leagues.leagues.LeaguesApi", return_value=mock_api),
            pytest.raises(TimeoutError),
        ):
            await mixin.leagues(mock_guild)


class TestFromException:
    @pytest.mark.parametrize(
        ("status", "code", "expected"),
        [
            (405, ErrorCodeEnum.SIGNUPS_CLOSED, SignupsClosedError),
            (404, ErrorCodeEnum.NOT_FOUND, NotFoundError),
            (409, ErrorCodeEnum.INTENT_CONFLICT, ConflictError),
            (500, ErrorCodeEnum.SERVER_ERROR, ServerError),
            (503, ErrorCodeEnum.SERVICE_UNAVAILABLE, ServerError),
            (400, ErrorCodeEnum.CUT_MIN_MATCH_DAYS, ApiError),
        ],
    )
    def test_picks_the_most_specific_class(self, status, code, expected):
        assert type(api_error(status, code=code)) is expected

    def test_keeps_the_envelope(self):
        exc = api_error(
            400,
            "Player X cannot be cut until 2 match days have passed.",
            code=ErrorCodeEnum.CUT_MIN_MATCH_DAYS,
            extra={"remaining_match_days": 2},
        )

        assert exc.status == 400
        assert exc.message == "Player X cannot be cut until 2 match days have passed."
        assert exc.code is ErrorCodeEnum.CUT_MIN_MATCH_DAYS
        assert exc.extra == {"remaining_match_days": 2}
        assert str(exc) == (
            "[400] cut_min_match_days: Player X cannot be cut until 2 match days have passed. (extra: {'remaining_match_days': 2})"
        )

    def test_nested_validation_errors_parse(self):
        exc = api_error(400, "Validation Error", code=ErrorCodeEnum.VALIDATION_ERROR, extra={"fields": {"name": ["required"]}})

        assert exc.extra == {"fields": {"name": ["required"]}}

    @pytest.mark.parametrize(
        ("status", "body", "expected"),
        [
            (502, "<html><body>502 Bad Gateway</body></html>", ServerError),
            (503, "", ServerError),
            (404, '{"message": "Not found.", "extra": {}, "type": "NotFound", "status_code": 404}', NotFoundError),
        ],
        ids=["html", "empty", "envelope without code"],
    )
    def test_body_that_is_not_the_envelope_falls_back_to_status_and_http_reason(self, status, body, expected):
        error = ApiError.from_exception(raw_api_exception(status, body))

        assert type(error) is expected
        assert error.message == HTTPStatus(status).phrase
        assert error.code is None

    def test_every_api_error_is_an_rsc_exception(self):
        assert isinstance(api_error(409), RscException)


class TestApiExceptionErrorEmbed:
    def test_shows_the_server_message_and_status(self):
        embed = ApiExceptionErrorEmbed(api_error(404, "League not found"))

        assert embed.description == "League not found"
        assert {f.name: f.value for f in embed.fields} == {"Status": "404", "Type": "NotFoundError"}

    def test_lists_extra_details(self):
        embed = ApiExceptionErrorEmbed(api_error(400, "Cut rejected", extra={"tier": "Elite"}))

        assert embed.description == "Cut rejected\n\ntier: Elite\n"

    def test_non_api_error_has_no_status(self):
        embed = ApiExceptionErrorEmbed(LeagueNotConfigured())

        assert embed.description == "An unknown error occurred..."
        assert [f.name for f in embed.fields] == ["Type"]
