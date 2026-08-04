import asyncio
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from dotenv import load_dotenv

import aiohttp
import pytest
import discord

from rsc.core import RSC
from rsc.exceptions import RscException

from rscapi import Configuration

from .utils import random_string, generate_discord_id

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

GUILD_ID = 395806681994493964  # RSC 3v3
NICKM_ID = 138778232802508801  # nickm discord ID
STAGING_URL = "https://staging-api.rscna.com/api/v1/"
# STAGING_URL = "http://127.0.0.1:8000/api/v1/"
LEAGUE_ID = 1

# Live API calls need far more headroom than the 10s default used by unit tests.
INTEGRATION_TIMEOUT = 30
# How long to wait when probing whether the staging server is up at all.
HEALTHCHECK_TIMEOUT = 5

# Transport level failures mean the staging server is unreachable, not that the
# code under test is broken. These are reported as skips rather than failures.
TRANSPORT_ERRORS = (aiohttp.ClientError, asyncio.TimeoutError)


@pytest.fixture(scope="session", autouse=True)
def load_env():
    load_dotenv()


def pytest_collection_modifyitems(config, items):
    """Give integration tests a longer timeout than the unit suite."""
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(pytest.mark.timeout(INTEGRATION_TIMEOUT))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    """Report staging outages as skips instead of failures.

    Only applies to integration tests. A transport error or a 5xx means the
    staging server is unhealthy; neither says anything about our code.
    """
    if "integration" not in item.keywords:
        return (yield)

    try:
        return (yield)
    except TRANSPORT_ERRORS as exc:
        pytest.skip(f"Staging API unreachable: {exc!r}")
    except RscException as exc:
        if exc.status and exc.status >= 500:
            pytest.skip(f"Staging API returned HTTP {exc.status}")
        raise


@pytest.fixture(scope="session")
def staging_reachable() -> bool:
    """Probe the staging server once per session.

    Any HTTP response (including 401/403) proves the server is up. Only a
    transport failure counts as unreachable.
    """
    try:
        with urllib.request.urlopen(STAGING_URL, timeout=HEALTHCHECK_TIMEOUT):
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


@pytest.fixture
def mock_guild():
    """Create a mock Discord guild for testing."""
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.name = "RSC 3v3"
    guild.icon = MagicMock()
    guild.icon.url = "https://example.com/icon.png"
    guild.text_channels = []
    guild.roles = []
    guild.get_channel = MagicMock(return_value=None)
    guild.get_role = MagicMock(return_value=None)
    guild.get_member = MagicMock(return_value=None)
    return guild


@pytest.fixture
def mock_member():
    """Create a mock Discord member for testing."""
    member = MagicMock(spec=discord.Member)
    member.id = NICKM_ID
    member.name = "nickm"
    member.display_name = "nickm"
    member.mention = f"<@{NICKM_ID}>"
    member.display_avatar = "https://example.com/avatar.png"
    member.guild = MagicMock(spec=discord.Guild)
    member.guild.id = GUILD_ID
    member.roles = []
    return member


@pytest.fixture
def mock_executor():
    """Create a mock Discord member to act as a transaction executor."""
    member = MagicMock(spec=discord.Member)
    member.id = 222222222
    member.name = "Executor"
    member.display_name = "Executor"
    member.mention = "<@222222222>"
    return member


@pytest.fixture
def mock_player_out():
    """Create a mock Discord member to act as a subbed-out player."""
    member = MagicMock(spec=discord.Member)
    member.id = 333333333
    member.name = "PlayerOut"
    member.display_name = "PlayerOut"
    member.mention = "<@333333333>"
    return member


@pytest.fixture
def api_key() -> str:
    """Get API key from environment variable."""
    key = os.getenv("RSC_API_KEY")
    if not key:
        pytest.skip("RSC_API_KEY environment variable not set")
    return key


@pytest.fixture
def api_url():
    """Get API URL"""
    return STAGING_URL


@pytest.fixture
def api_conf(api_url, api_key, staging_reachable) -> Configuration:
    """Return a basic API configuration dictionary."""
    if not staging_reachable:
        pytest.skip(f"Staging API is unreachable ({api_url})")
    print()
    return Configuration(host=api_url, api_key={"Api-Key": api_key}, api_key_prefix={"Api-Key": "Api-Key"})


class MockBot(RSC):
    def __init__(self, guild, api_conf, league_id: int = LEAGUE_ID):
        # Skip the parent __init__ to avoid dependency issues
        self.bot = MagicMock()

        # Set up mock configuration
        self.guild_id = guild.id
        self._league = {guild.id: league_id}
        self._api_conf = {}
        self._api_conf[guild.id] = api_conf

        # Cache
        self._franchise_cache = {GUILD_ID: []}
        self._team_cache = {GUILD_ID: []}
        self._tier_cache = {GUILD_ID: []}

        self._get_api_url = AsyncMock(return_value=self._api_conf[self.guild_id].host)


@pytest.fixture
def rsc_bot(mock_guild, api_conf) -> RSC:
    return MockBot(mock_guild, api_conf)

@pytest.fixture
def rsc_bot_no_key(mock_guild, staging_reachable) -> RSC:
    """Testable version of MemberMixIn with minimal dependencies."""
    if not staging_reachable:
        pytest.skip(f"Staging API is unreachable ({STAGING_URL})")
    api_conf_no_key = Configuration(host=STAGING_URL)  # Create a copy without the API key

    return MockBot(mock_guild, api_conf_no_key)


@pytest.fixture
def rsc_bot_invalid_key(mock_guild, staging_reachable) -> RSC:
    """Testable version of MemberMixIn with minimal dependencies."""
    if not staging_reachable:
        pytest.skip(f"Staging API is unreachable ({STAGING_URL})")
    api_conf_invalid_key = Configuration(host=STAGING_URL, api_key={"Api-Key": "invalid_key"}, api_key_prefix={"Api-Key": "Api-Key"})

    return MockBot(mock_guild, api_conf_invalid_key)


@pytest.fixture(scope="function")
def generated_discord_member():
    member = MagicMock(spec=discord.Member)
    member.id = generate_discord_id()
    name = random_string()
    member.name = name
    member.display_name = name
    member.mention = f"<@{member.id}>"
    member.tracker_link = f"https://rocketleague.tracker.network/rocket-league/profile/steam/{name}/overview"
    return member
