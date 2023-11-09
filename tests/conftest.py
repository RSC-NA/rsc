import os

from rscapi import (
    Configuration,
    ApiClient,
    FranchisesApi,
    LeaguePlayersApi,
    LeaguesApi,
    MatchesApi,
    MembersApi,
    NumbersApi,
    SeasonsApi,
    TeamsApi,
    TiersApi,
    TrackerLinksApi,
)
import pytest
import asyncio

import logging

log = logging.getLevelName(__name__)

# Env
from dotenv import load_dotenv

load_dotenv()


@pytest.fixture(scope="session")
def event_loop():
    """Have to define event_loop as session scope to use other fixtures in that scope"""
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
@pytest.mark.asyncio
async def key():
    yield os.environ["RSC_API_KEY"]


@pytest.fixture(scope="session")
@pytest.mark.asyncio
async def url():
    yield os.environ["RSC_API_URL"]


@pytest.fixture(scope="session")
@pytest.mark.asyncio
async def config(key, url):
    yield Configuration(host=url, api_key=key)


@pytest.fixture(scope="session", autouse=True)
@pytest.mark.asyncio
async def client(config):
    async with ApiClient(config) as api:
        yield api

@pytest.fixture(scope="class", autouse=True)
@pytest.mark.asyncio
async def FranchiseApi(client):
    yield FranchisesApi(client)

@pytest.fixture(scope="class", autouse=True)
@pytest.mark.asyncio
async def LeaguePlayerApi(client):
    yield LeaguePlayersApi(client)

@pytest.fixture(scope="class", autouse=True)
@pytest.mark.asyncio
async def LeagueApi(client):
    yield LeaguesApi(client)

@pytest.fixture(scope="class", autouse=True)
@pytest.mark.asyncio
async def MatchApi(client):
    yield MatchesApi(client)

@pytest.fixture(scope="class", autouse=True)
@pytest.mark.asyncio
async def MemberApi(client):
    yield MembersApi(client)

@pytest.fixture(scope="class", autouse=True)
@pytest.mark.asyncio
async def NumberApi(client):
    yield NumbersApi(client)

@pytest.fixture(scope="class", autouse=True)
@pytest.mark.asyncio
async def SeasonApi(client):
    yield SeasonsApi(client)

@pytest.fixture(scope="class", autouse=True)
@pytest.mark.asyncio
async def TeamApi(client):
    yield TeamsApi(client)

@pytest.fixture(scope="class", autouse=True)
@pytest.mark.asyncio
async def TierApi(client):
    yield TiersApi(client)

@pytest.fixture(scope="class", autouse=True)
@pytest.mark.asyncio
async def TrackerApi(client):
    yield TrackerLinksApi(client)