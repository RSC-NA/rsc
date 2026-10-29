import pytest

from rsc.devleague import api as devleague_api
from rsc.devleague.models import DevLeagueCheckInOut, DevLeagueStatus


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self):
        return self.payload


class _FakeSession:
    def __init__(self, response: _FakeResponse, calls: list[dict], args: tuple, kwargs: dict):
        self.response = response
        self.calls = calls
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def get(self, url: str, params: dict):
        self.calls.append({"url": url, "params": params})
        return self.response


def _patch_client_session(monkeypatch, payload):
    response = _FakeResponse(payload)
    calls = []
    sessions = []

    def factory(*args, **kwargs):
        session = _FakeSession(response, calls, args, kwargs)
        sessions.append(session)
        return session

    monkeypatch.setattr(devleague_api.aiohttp, "ClientSession", factory)
    return calls, sessions


@pytest.mark.parametrize(
    ("endpoint", "path", "payload", "model", "session_kwargs"),
    [
        (
            devleague_api.dev_league_status,
            "/api/status",
            {"checked_in": True, "error": None, "player": "Player", "rsc_id": "RSC-1", "tier": "Major"},
            DevLeagueStatus,
            {"trust_env": True},
        ),
        (
            devleague_api.dev_league_check_in,
            "/api/check_in",
            {"error": None, "success": "checked in"},
            DevLeagueCheckInOut,
            {"trust_env": True},
        ),
        (
            devleague_api.dev_league_check_out,
            "/api/check_out",
            {"error": None, "success": "checked out"},
            DevLeagueCheckInOut,
            {},
        ),
    ],
)
async def test_devleague_endpoint(monkeypatch, mock_member, endpoint, path, payload, model, session_kwargs):
    calls, sessions = _patch_client_session(monkeypatch, payload)

    result = await endpoint(mock_member)

    assert isinstance(result, model)
    assert calls == [
        {
            "url": f"{devleague_api.DEVLEAGUE_API_URL}{path}",
            "params": {"discord_id": mock_member.id},
        },
    ]
    assert sessions[0].kwargs == session_kwargs


def test_status_for_unknown_player():
    # The server's whole reply when the Discord ID has no contract
    status = DevLeagueStatus.model_validate({"error": "Player not found", "discord_id": "1"})

    assert status.error == "Player not found"
    assert (status.player, status.rsc_id, status.tier, status.checked_in) == (None, None, None, False)


def test_status_without_error_key():
    status = DevLeagueStatus(player="Player", rsc_id="RSC-1", tier="Major", checked_in=False)

    assert status.error is None


def test_check_in_out_without_optional_keys():
    result = DevLeagueCheckInOut(success="checked in")

    assert result.error is None
