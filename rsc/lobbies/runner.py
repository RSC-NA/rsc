"""Start and tear down combines and Dev League lobbies from the website's webhooks.

Both systems get the same two webhooks: a batch of lobbies to start, and an event
when a match finishes. `LobbyRunner` handles both once, for either system. Each
system subclasses `LobbyLeague` with only what differs: its settings, channel
names, card link and the few extras it alone has.
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Coroutine, Iterator
from pprint import pformat
from typing import TYPE_CHECKING, Any

import discord
import pydantic
from aiohttp import web
from redbot.core.config import Group

from rsc.combines.lobby import LobbyMessages, finish_lobby, lobby_card, lobby_messages, post_lobby
from rsc.combines.models import CombineEvent, CombineEventType, CombinesLobby
from rsc.combines.views import LobbyKind, LobbyScore
from rsc.lobbies.channels import Side, is_lobby_channel
from rsc.utils import utils

if TYPE_CHECKING:
    from rsc.abc import RSCMixIn

log = logging.getLogger("red.rsc.lobbies.runner")

# Discord allows 50 channels per category. Leave headroom before overflowing.
CATEGORY_CHANNEL_LIMIT = 40
# A full category overflows into "<name>-2", then "-3" and "-4"
OVERFLOW_CATEGORIES = range(2, 5)

Overwrites = dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite]


class LobbyLeague(ABC):
    """What one system does differently. `LobbyRunner` does everything else."""

    kind: LobbyKind
    # Names the system in logs, e.g. "Combines"
    name: str
    # Names one lobby in logs, e.g. "combine lobby" -> "combine lobby 101"
    label: str

    def __init__(self, cog: "RSCMixIn"):
        self.cog = cog

    @abstractmethod
    def store(self, guild: discord.Guild) -> Group:
        """The Config group that keeps this system's `LobbyMessages`."""

    @abstractmethod
    async def active(self, guild: discord.Guild) -> bool: ...

    @abstractmethod
    async def category(self, guild: discord.Guild) -> discord.CategoryChannel | None: ...

    @abstractmethod
    async def announce_channel(self, guild: discord.Guild) -> discord.TextChannel | None: ...

    @abstractmethod
    def channel_name(self, lobby: CombinesLobby, side: Side) -> str:
        """`<tier>-<id>-<side>`. Teardown finds the channels again by parsing this."""

    @abstractmethod
    def match_url(self, lobby: CombinesLobby) -> str: ...

    def extra_overwrites(self, guild: discord.Guild) -> Overwrites:
        """Permission overwrites on top of the shared ones."""
        return {}

    async def place(self, category: discord.CategoryChannel, home: discord.VoiceChannel, away: discord.VoiceChannel) -> None:
        """Move a new lobby's channels into position. They stay where Discord put them by default."""
        return None

    async def final_score(self, guild: discord.Guild, entry: LobbyMessages) -> LobbyScore | None:
        """The series score for the Final card, or None to show the card without one."""
        return None


class LobbyRunner:
    """Creates, announces and tears down one system's lobbies."""

    # Players get a moment after the match before their voice channels vanish
    TEARDOWN_DELAY = 30

    def __init__(self, cog: "RSCMixIn", league: LobbyLeague):
        self.cog = cog
        self.league = league
        # (guild ID, lobby ID) of lobbies being created or still up. New channels can
        # take a moment to reach the guild cache, so a duplicate webhook could slip past
        # the channel name check without this.
        self.active_lobbies: set[tuple[int, int]] = set()
        self.background_tasks: set[asyncio.Task] = set()

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    # Webhooks

    async def start_game(self, request: web.Request) -> web.Response:
        """A batch of lobbies to start, keyed by lobby id."""
        log.debug(f"Received request to create {self.league.name} games")

        try:
            data = await request.json()
        except json.JSONDecodeError:
            log.warning(f"Received {self.league.name} game webhook with no JSON data")
            return web.Response(status=400)  # 400 Bad Request

        if not isinstance(data, dict):
            log.warning(f"Received {self.league.name} game webhook that is not a JSON object")
            return web.Response(status=400)  # 400 Bad Request

        lobbies: list[CombinesLobby] = []
        try:
            for v in data.values():
                log.debug(f"{self.league.name} raw lobby: {v}")
                lobbies.append(CombinesLobby(**v))
        except pydantic.ValidationError as exc:
            log.exception(f"Error deserializing {self.league.name} game lobby", exc_info=exc)
            return web.Response(status=400)  # 400 Bad Request

        if not lobbies:
            log.warning(f"Received {self.league.name} game webhook with no lobbies")
            return web.Response(status=400)  # 400 Bad Request

        # Checked up front so the caller still gets a 503 when nothing can be created.
        for guild_id in {lobby.guild_id for lobby in lobbies}:
            guild = self.cog.bot.get_guild(guild_id)
            if not guild:
                log.warning(f"Bot is not in the {self.league.name} guild ID: {guild_id}")
                return web.Response(status=503)  # 503 Service Unavailable
            if not await self.league.active(guild):
                log.warning(f"{self.league.name} is not active in guild ID: {guild_id}")
                return web.Response(status=503)  # 503 Service Unavailable

        # Channel creation is rate limited by Discord and can outlast the caller's
        # HTTP timeout. Respond now so a timed out request is not retried into
        # duplicate lobbies.
        self._spawn(self._create_all(lobbies))
        return web.Response(status=200)

    async def handle_event(self, request: web.Request) -> web.Response:
        """A match event. Only "Finished Game" does anything: it tears the lobby down."""
        log.debug(f"Received {self.league.name} event")

        try:
            data = await request.json()
            log.debug(f"body:\n\n{pformat(data)}\n\n")
            event = CombineEvent(**data)
        except json.JSONDecodeError:
            log.warning(f"Received {self.league.name} event with no JSON data")
            return web.Response(status=400)  # 400 Bad Request
        except pydantic.ValidationError as exc:
            log.exception(f"Error deserializing {self.league.name} event", exc_info=exc)
            return web.Response(status=400)  # 400 Bad Request

        guild = self.cog.bot.get_guild(event.guild_id)
        if not guild:
            log.error(f"Bot is not in the {self.league.name} guild ID: {event.guild_id}")
            return web.Response(status=503)  # 503 Service Unavailable

        if event.message_type is not CombineEventType.Finished:
            return web.Response(status=501)  # 501 Not Implemented
        if not event.match_id:
            log.warning(f"Received a finished {self.league.label} with no id.")
            return web.Response(status=400)  # 400 Bad Request

        self._spawn(self.teardown(guild, lobby_id=event.match_id))
        return web.Response(status=200)  # 200 OK

    # Start

    async def _create_all(self, lobbies: list[CombinesLobby]) -> None:
        # One failed lobby must not stop the rest from being created.
        for lobby in lobbies:
            key = (lobby.guild_id, lobby.id)
            if key in self.active_lobbies:
                log.warning(f"{self.league.label.capitalize()} {lobby.id} is already active. Skipping duplicate.")
                continue

            self.active_lobbies.add(key)
            channels: list[discord.VoiceChannel] = []
            try:
                channels = await self.create_channels(lobby)
            except Exception as exc:
                log.exception(f"Error creating {self.league.label} {lobby.id}", exc_info=exc)
            finally:
                # Nothing was created, so let a later request try again.
                if not channels:
                    self.active_lobbies.discard(key)

    async def create_channels(self, lobby: CombinesLobby) -> list[discord.VoiceChannel]:
        """Create a lobby's home and away channels and announce it. Empty when nothing was created."""
        label = f"{self.league.label} {lobby.id}"
        log.debug(f"Creating {label} channels")

        guild = self.cog.bot.get_guild(lobby.guild_id)
        if not guild:
            log.warning(f"Bot left the {self.league.name} guild before {label} was created")
            return []

        if not await self.league.active(guild):
            log.warning(f"{self.league.name} stopped before {label} was created")
            return []

        category = await self.league.category(guild)
        if not category:
            log.error(f"{self.league.name} category not configured. Can't create {label}.")
            return []

        home_name = self.league.channel_name(lobby, "home")
        away_name = self.league.channel_name(lobby, "away")
        for name in (home_name, away_name):
            exists = discord.utils.get(guild.channels, name=name)
            if exists:
                log.error(f"{label.capitalize()} already exists: {exists.name}")
                return []

        players = await self.cog.combine_players_from_lobby(guild, lobby)
        if not players:
            log.error(f"{label.capitalize()} has no players in the guild")
            return []

        try:
            league_role = await utils.get_league_role(guild)
        except ValueError:
            log.error(f"League role does not exist. Can't create {label}.")
            return []

        target = await self.target_category(guild, category)

        # Only league members can join. Everyone else can see the channel.
        overwrites: Overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                connect=False,
                speak=False,
                send_messages=False,
                add_reactions=False,
            ),
            league_role: discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                speak=True,
                stream=True,
                send_messages=True,
                add_reactions=True,
            ),
            **self.league.extra_overwrites(guild),
        }

        reason = f"Starting {label}"
        home = await target.create_voice_channel(name=home_name, overwrites=overwrites, reason=reason, user_limit=5)
        away = await target.create_voice_channel(name=away_name, overwrites=overwrites, reason=reason, user_limit=5)

        try:
            await self.league.place(target, home, away)
        except discord.HTTPException as exc:
            log.warning(f"Unable to move {label} into place", exc_info=exc)

        announce_channel = await self.league.announce_channel(guild)
        if announce_channel:
            await self.announce(guild, lobby, [home, away], announce_channel)
        else:
            log.warning(f"{self.league.name} announcement channel not found. {label.capitalize()} has no card.")

        return [home, away]

    async def target_category(self, guild: discord.Guild, category: discord.CategoryChannel) -> discord.CategoryChannel:
        """The configured category, or an overflow category if it is full."""
        if len(category.channels) <= CATEGORY_CHANNEL_LIMIT:
            return category

        log.debug(f"{self.league.name} category is full, looking for the next available category")
        for i in OVERFLOW_CATEGORIES:
            name = f"{category.name}-{i}"
            next_category = discord.utils.get(guild.channels, name=name)

            if not next_category:
                log.debug(f"Creating overflow {self.league.name} category: {name}")
                return await guild.create_category(
                    name=name,
                    position=category.position + 1,
                    reason=f"{self.league.name} channels have maxed out.",
                )

            if not isinstance(next_category, discord.CategoryChannel):
                log.warning(f"{self.league.name} overflow name is already in use and not a category: {next_category}")
                continue

            if len(next_category.channels) <= CATEGORY_CHANNEL_LIMIT:
                return next_category

        log.warning(f"All {self.league.name} overflow categories are full. Using the configured category.")
        return category

    def categories(self, guild: discord.Guild, category: discord.CategoryChannel) -> Iterator[discord.CategoryChannel]:
        """The configured category followed by any overflow categories that exist."""
        yield category
        for i in OVERFLOW_CATEGORIES:
            overflow = discord.utils.get(guild.categories, name=f"{category.name}-{i}")
            if overflow:
                yield overflow

    async def announce(
        self,
        guild: discord.Guild,
        lobby: CombinesLobby,
        channels: list[discord.VoiceChannel],
        announce_channel: discord.TextChannel,
    ) -> discord.Message:
        """Post the lobby's card, DM it to every player, and remember it for teardown."""
        if len(channels) != 2:
            raise ValueError(f"Must provide 2 voice channels to announce a {self.league.label}.")

        card = lobby_card(
            guild,
            lobby,
            kind=self.league.kind,
            channels=channels,
            match_url=self.league.match_url(lobby),
            started_at=discord.utils.utcnow(),
        )
        return await post_lobby(self.cog, guild, lobby, card, announce_channel, self.league.store(guild), self.active_lobbies)

    # Teardown

    async def teardown(self, guild: discord.Guild, lobby_id: int) -> None:
        """Turn the lobby's card Final and delete its voice channels."""
        await asyncio.sleep(self.TEARDOWN_DELAY)

        log.debug(f"Tearing down {self.league.label} {lobby_id}")
        self.active_lobbies.discard((guild.id, lobby_id))

        # The voice channels and lobby details are done with, so the card turns Final
        store = self.league.store(guild)
        entry = await lobby_messages(store, lobby_id)
        if entry:
            await finish_lobby(self.cog, entry, store, await self.league.final_score(guild, entry))

        category = await self.league.category(guild)
        if not category:
            log.error(f"{self.league.name} category not configured. Can't tear down {self.league.label} {lobby_id}.")
            return

        for cat in self.categories(guild, category):
            for channel in cat.voice_channels:
                if is_lobby_channel(channel.name, lobby_id):
                    log.debug(f"Deleting {channel.name}")
                    await channel.delete(reason=f"{self.league.label.capitalize()} {lobby_id} has finished.")
