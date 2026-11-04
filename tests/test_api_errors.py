from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rscapi.exceptions import ApiException
from tests.utils import api_error, api_exception

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
        mock_api.leagues_list.side_effect = api_exception(404, "League not found", error_type="NotFound")

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
        ("status", "error_type", "expected"),
        [
            (404, "NotFound", NotFoundError),
            (409, "IntentToPlayException", ConflictError),
            (405, "SignupsClosedException", SignupsClosedError),
            (500, "APIException", ServerError),
            (503, "APIException", ServerError),
            (400, "TransactionError", ApiError),
        ],
    )
    def test_picks_the_most_specific_class(self, status, error_type, expected):
        assert type(api_error(status, error_type=error_type)) is expected

    def test_keeps_the_envelope(self):
        exc = api_error(400, "Validation Error", error_type="ValidationError", extra={"fields": {"name": ["This field is required."]}})

        assert exc.status == 400
        assert exc.message == "Validation Error"
        assert exc.error_type == "ValidationError"
        assert exc.extra == {"fields": {"name": ["This field is required."]}}
        assert str(exc) == "[400] ValidationError: Validation Error (extra: {'fields': {'name': ['This field is required.']}})"

    def test_body_that_is_not_json_falls_back_to_the_http_reason(self):
        exc = ApiException(status=502, reason="Bad Gateway")
        exc.body = "<html><body>502 Bad Gateway</body></html>"

        error = ApiError.from_exception(exc)

        assert type(error) is ServerError
        assert error.message == "Bad Gateway"
        assert error.error_type is None

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
