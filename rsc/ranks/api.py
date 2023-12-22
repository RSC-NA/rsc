import logging
from urllib.parse import urljoin

import aiohttp
from pydantic import parse_obj_as

from rsc.const import RAPIDAPI_URL
from rsc.enums import RLChallengeType, RLRegion, RLStatType
from rsc.exceptions import RapidApiTimeOut, RapidQuotaExceeded
from rsc.ranks import models

log = logging.getLogger("red.rsc.ranks.api")


class RapidApi:
    def __init__(self, token: str, url: str = RAPIDAPI_URL):
        self.token = token
        self.url = url
        self.headers = {
            "User-Agent": "RSCBot",
            "Accept-Encoding": "identity",
            "X-RapidAPI-Key": self.token,
            "X-RapidAPI-Host": self.url.removeprefix("https://"),
        }

    async def ranks(self, player: str) -> models.PlayerRanks:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            url = urljoin(self.url, f"/ranks/{player}")
            resp = await session.get(url=url)
            data = await resp.json()
            await self._check_response(data)
            return models.PlayerRanks(**data)

    async def stat(self, stat_type: RLStatType, player: str) -> models.Stat:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            url = urljoin(self.url, f"/stat/{player}/{stat_type.value.lower()}")
            resp = await session.get(url=url)
            data = await resp.json()
            await self._check_response(data)
            return models.Stat(**data)

    async def profile(self, player: str) -> models.Profile:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            url = urljoin(self.url, f"/profile/{player}")
            resp = await session.get(url=url)
            data = await resp.json()
            await self._check_response(data)
            return models.Profile(**data)

    async def club(self, player: str) -> models.Club:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            url = urljoin(self.url, f"/club/{player}")
            resp = await session.get(url=url)
            data = await resp.json()
            await self._check_response(data)
            return models.Club(**data)

    async def titles(self, player: str) -> list[models.Title]:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            url = urljoin(self.url, f"/titles/{player}")
            resp = await session.get(url=url)
            data = await resp.json()
            await self._check_response(data)
            title_list = data.get("titles")
            if not title_list:
                return []
            return parse_obj_as(list[models.Title], title_list)

    async def blog(self) -> models.Profile:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            url = urljoin(self.url, "/blog")
            resp = await session.get(url=url)
            data = await resp.json()
            await self._check_response(data)
            return models.Profile(**data)

    async def challenges(self, challenge_type: RLChallengeType) -> str:
        # async with aiohttp.ClientSession(headers=self.headers) as session:
        #     url = urljoin(self.url, f"/challenges/{challenge_type}")
        #     resp = await session.get(url=url)
        #     await self._check_rate_limited(resp)
        raise NotImplementedError  # Endpoint broken

    async def esports(self) -> str:
        # async with aiohttp.ClientSession(headers=self.headers) as session:
        #     url = urljoin(self.url, "/esports")
        #     resp = await session.get(url=url)
        #     await self._check_response(resp)
        raise NotImplementedError  # Endpoint broken

    async def population(self) -> models.Population:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            url = urljoin(self.url, "/population")
            resp = await session.get(url=url)
            data = await resp.json()
            await self._check_response(data)
            return models.Population(**data)

    async def news(self) -> models.ArticleResult:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            url = urljoin(self.url, "/news")
            resp = await session.get(url=url)
            data = await resp.json()
            await self._check_response(data)
            return models.ArticleResult(**data)

    async def shop(self) -> str:
        # async with aiohttp.ClientSession(headers=self.headers) as session:
        #     url = urljoin(self.url, f"/shops/featured")
        #     resp = await session.get(url=url)
        #     return await self._check_response(resp)
        raise NotImplementedError  # Endpoint broken

    async def tournaments(self, region: RLRegion) -> models.TournamentResult:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            url = urljoin(self.url, f"/tournaments/{region}")
            resp = await session.get(url=url)
            data = await resp.json()
            await self._check_response(resp)
            return models.TournamentResult(**data)

    async def _check_response(self, data: dict):
        log.debug(data)
        msg = data.get("message")
        if msg and msg.startswith("You have exceeded the"):
            log.warning("RapidAPI quota has been exceeded...")
            raise RapidQuotaExceeded

        msgs = data.get("messages")
        if msgs and msgs.startswith("The request to the API has timed out."):
            log.warning("Request to RapidAPI timed out.")
            raise RapidApiTimeOut
        log.debug("No rate limit found")
