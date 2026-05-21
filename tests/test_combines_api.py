import pytest

from rsc.combines import api as combines_api
from rsc.combines.models import CombinesLobby, CombinesStatus
from rsc.exceptions import BadGateway


class _FakeResponse:
    def __init__(self, payload, status: int = 200):
        self.payload = payload
        self.status = status

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


def _patch_client_session(monkeypatch, payload, status: int = 200):
    response = _FakeResponse(payload, status=status)
    calls = []
    sessions = []

    def factory(*args, **kwargs):
        session = _FakeSession(response, calls, args, kwargs)
        sessions.append(session)
        return session

    monkeypatch.setattr(combines_api.aiohttp, "ClientSession", factory)
    return calls, sessions


def _lobby_payload() -> dict:
    return {
        "id": 5,
        "lobby_user": "RSC5",
        "lobby_pass": "secret",
        "home_wins": 1,
        "away_wins": 0,
        "reported_rsc_id": None,
        "confirmed_rsc_id": None,
        "completed": False,
        "cancelled": False,
        "tier": "Major",
        "guild_id": 395806681994493964,
        "home": [
            {"discord_id": 111, "rsc_id": "RSC-1", "match_id": 5, "team": "home", "name": "Home"},
        ],
        "away": [
            {"discord_id": 222, "rsc_id": "RSC-2", "match_id": 5, "team": "away", "name": "Away"},
        ],
    }


@pytest.mark.parametrize(
    ("endpoint", "path"),
    [
        (combines_api.combines_check_in, "check_in"),
        (combines_api.combines_check_out, "check_out"),
    ],
)
async def test_combines_status_endpoints(monkeypatch, mock_member, endpoint, path):
    calls, sessions = _patch_client_session(monkeypatch, {"status": "success", "message": "ok"})

    result = await endpoint("https://combines.example/api/", mock_member)

    assert isinstance(result, CombinesStatus)
    assert result.status == "success"
    assert calls == [
        {
            "url": f"https://combines.example/api/{path}",
            "params": {"discord_id": mock_member.id, "guild_id": mock_member.guild.id},
        },
    ]
    assert sessions[0].kwargs == {"trust_env": True}


async def test_combines_active_returns_lobbies(monkeypatch, mock_member):
    calls, sessions = _patch_client_session(monkeypatch, {"5": _lobby_payload()})

    result = await combines_api.combines_active("https://combines.example/api/", mock_member)

    assert len(result) == 1
    assert isinstance(result[0], CombinesLobby)
    assert result[0].id == 5
    assert calls[0]["url"] == "https://combines.example/api/active"
    assert calls[0]["params"] == {"discord_id": mock_member.id, "guild_id": mock_member.guild.id}
    assert sessions[0].kwargs == {"trust_env": True}


async def test_combines_active_returns_status(monkeypatch, mock_member):
    _patch_client_session(monkeypatch, {"status": "error", "message": "closed"})

    result = await combines_api.combines_active("https://combines.example/api/", mock_member)

    assert isinstance(result, CombinesStatus)
    assert result.message == "closed"


async def test_combines_lobby_returns_lobby(monkeypatch, mock_member):
    calls, sessions = _patch_client_session(monkeypatch, {"5": _lobby_payload()})

    result = await combines_api.combines_lobby("https://combines.example/api/", executor=mock_member, lobby_id=5)

    assert isinstance(result, CombinesLobby)
    assert result.id == 5
    assert calls == [
        {
            "url": "https://combines.example/api/lobby/5",
            "params": {"discord_id": mock_member.id, "guild_id": mock_member.guild.id},
        },
    ]
    assert sessions[0].kwargs == {"trust_env": True}


async def test_combines_lobby_rejects_empty_payload(monkeypatch, mock_member):
    _patch_client_session(monkeypatch, {})

    with pytest.raises(ValueError, match="valid JSON object"):
        await combines_api.combines_lobby("https://combines.example/api/", executor=mock_member)


async def test_combines_endpoint_raises_bad_gateway(monkeypatch, mock_member):
    _patch_client_session(monkeypatch, {}, status=502)

    with pytest.raises(BadGateway):
        await combines_api.combines_check_in("https://combines.example/api/", mock_member)
