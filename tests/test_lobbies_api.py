from unittest.mock import MagicMock

import aiohttp
import pytest

from rsc.exceptions import SiteUnavailable
from rsc.lobbies import api as lobbies_api

URL = "https://devleague.example/api/status"


class _FakeResponse:
    def __init__(self, status: int = 200, payload=None, error: Exception | None = None):
        self.status = status
        self.payload = payload
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self):
        if self.error:
            raise self.error
        return self.payload


class _FakeSession:
    def __init__(self, response: _FakeResponse | None, error: Exception | None):
        self.response = response
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def get(self, url: str, params: dict):
        if self.error:
            raise self.error
        return self.response


def _patch(monkeypatch, response: _FakeResponse | None = None, error: Exception | None = None) -> None:
    monkeypatch.setattr(lobbies_api.aiohttp, "ClientSession", lambda **kwargs: _FakeSession(response, error))


async def test_parses_the_reply(monkeypatch):
    _patch(monkeypatch, _FakeResponse(payload={"ok": True}))

    assert await lobbies_api.get_json(URL, {"discord_id": 1}, lobbies_api.json_object) == {"ok": True}


@pytest.mark.parametrize(
    "error",
    [
        aiohttp.ClientConnectorError(MagicMock(), OSError("refused")),
        aiohttp.ServerDisconnectedError(),
        TimeoutError(),
    ],
    ids=["refused", "disconnected", "timeout"],
)
async def test_request_failures(monkeypatch, error):
    _patch(monkeypatch, error=error)

    with pytest.raises(SiteUnavailable):
        await lobbies_api.get_json(URL, {}, lobbies_api.json_object)


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_server_errors(monkeypatch, status):
    _patch(monkeypatch, _FakeResponse(status=status, payload={"status": "error"}))

    with pytest.raises(SiteUnavailable, match=str(status)):
        await lobbies_api.get_json(URL, {}, lobbies_api.json_object)


async def test_reply_that_is_not_json(monkeypatch):
    # What aiohttp raises for an HTML error page from a proxy in front of the site
    _patch(monkeypatch, _FakeResponse(error=aiohttp.ContentTypeError(MagicMock(), ())))

    with pytest.raises(SiteUnavailable):
        await lobbies_api.get_json(URL, {}, lobbies_api.json_object)


async def test_reply_parse_rejects(monkeypatch):
    _patch(monkeypatch, _FakeResponse(payload=["not", "an", "object"]))

    with pytest.raises(SiteUnavailable, match="Expected a JSON object"):
        await lobbies_api.get_json(URL, {}, lobbies_api.json_object)


async def test_client_errors_still_return_their_reply(monkeypatch):
    # The site answers a bad request with JSON the caller reads, so only 5xx counts as down
    _patch(monkeypatch, _FakeResponse(status=404, payload={"status": "error", "message": "No lobby"}))

    assert await lobbies_api.get_json(URL, {}, lobbies_api.json_object) == {"status": "error", "message": "No lobby"}
