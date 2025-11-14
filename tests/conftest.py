import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from dotenv import load_dotenv

import pytest
import discord

from rsc.core import RSC

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


@pytest.fixture(scope="session", autouse=True)
def load_env():
    load_dotenv()


@pytest.fixture
def mock_guild():
    """Create a mock Discord guild for testing."""
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.name = "RSC 3v3"
    return guild


@pytest.fixture
def mock_member():
    """Create a mock Discord member for testing."""
    member = MagicMock(spec=discord.Member)
    member.id = NICKM_ID
    member.name = "nickm"
    member.display_name = "nickm"
    member.mention = f"<@{NICKM_ID}>"
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
def api_conf(api_url, api_key) -> Configuration:
    """Return a basic API configuration dictionary."""
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
    """Testable version of MemberMixIn with minimal dependencies."""

    return MockBot(mock_guild, api_conf)


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
