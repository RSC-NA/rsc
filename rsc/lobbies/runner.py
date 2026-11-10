"""Start and tear down combines and Dev League lobbies from the website's webhooks.

Both systems get the same two webhooks: a batch of lobbies to start, and an event
when a match finishes. `LobbyRunner` handles both once, for either system. Each
system subclasses `LobbyLeague` with only what differs: its settings, channel
names, card link and the few extras it alone has.

The website sends every game it has each time staff press the button, including
ones already up. Each runner queues only the lobbies it hasn't seen, and one worker
creates them one at a time, so repeat presses add nothing and nothing races.
"""

import asyncio
import contextlib
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
from rsc.lobbies.channels import Side, is_lobby_channel, parse_lobby_channel
from rsc.utils import utils

if TYPE_CHECKING:
    from discord.types.guild import ChannelPositionUpdate

    from rsc.abc import RSCMixIn

log = logging.getLogger("red.rsc.lobbies.runner")

# Discord allows 50 channels per category. Leave headroom before overflowing.
CATEGORY_CHANNEL_LIMIT = 40
# A full category overflows into "<name>-2", then "-3" and "-4"
OVERFLOW_CATEGORIES = range(2, 5)
# A lobby still unfinished after this long is given up so the queue keeps moving. The
# next webhook finishes it. Generous, since Discord rate limits can hold a request a while.
LOBBY_TIMEOUT = 120

Overwrites = dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite]


def _sentence(text: str) -> str:
    """Capitalise the first letter only. str.capitalize() would turn "Dev League" into "Dev league"."""
    return text[:1].upper() + text[1:]


class LobbyLeague(ABC):
    """What one system does differently. `LobbyRunner` does everything else."""

    kind: LobbyKind
    # Names the system in logs, e.g. "Combines"
    name: str
    # Names one lobby in logs, e.g. "combine lobby" -> "combine lobby 101"
    label: str
    # One lobby and several in command replies, e.g. "match" and "matches"
    noun: str
    nouns: str

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

    def sort_key(self, name: str) -> tuple[int, ...] | None:
        """Where a lobby channel goes in its category, or None to leave it where Discord put it."""
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
        # (guild ID, lobby ID) of lobbies queued, being created or still up. A webhook
        # queues only lobbies not in here.
        self.active_lobbies: set[tuple[int, int]] = set()
        self.background_tasks: set[asyncio.Task] = set()
        self.queue: asyncio.Queue[CombinesLobby] = asyncio.Queue()
        self.worker: asyncio.Task | None = None
        # Channels created since their category was last sorted. Discord rate limits
        # position updates hard, so each category is sorted once the queue empties.
        self.unsorted: dict[discord.CategoryChannel, list[discord.VoiceChannel]] = {}

    def _spawn(self, coro: Coroutine[Any, Any, None], failure: str) -> None:
        """Run `coro` in the background, logging `failure` with the traceback if it raises."""
        task = asyncio.create_task(coro)
        self.background_tasks.add(task)

        def finished(task: asyncio.Task) -> None:
            self.background_tasks.discard(task)
            if not task.cancelled() and (exc := task.exception()):
                log.error(failure, exc_info=exc)

        task.add_done_callback(finished)

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
        # HTTP timeout, so the lobbies are queued and the reply goes out now.
        self.enqueue(lobbies)
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

        self._spawn(self.teardown(guild, lobby_id=event.match_id), f"Error tearing down {self.league.label} {event.match_id}")
        return web.Response(status=200)  # 200 OK

    async def list_open(self, request: web.Request) -> web.Response:
        """`GET ?guild_id=<id>`: the IDs of every lobby still open there, for test scripts to end."""
        try:
            guild_id = int(request.query["guild_id"])
        except (KeyError, ValueError):
            return web.Response(status=400)  # 400 Bad Request

        guild = self.cog.bot.get_guild(guild_id)
        if not guild:
            return web.Response(status=503)  # 503 Service Unavailable
        return web.json_response({"lobbies": sorted(await self.open_lobbies(guild))})

    # Start

    def enqueue(self, lobbies: list[CombinesLobby]) -> None:
        """Queue each lobby not already queued or up, and make sure the worker is running."""
        new = []
        for lobby in lobbies:
            key = (lobby.guild_id, lobby.id)
            if key in self.active_lobbies:
                continue
            self.active_lobbies.add(key)
            self.queue.put_nowait(lobby)
            new.append(str(lobby.id))

        noun = self.league.noun if len(new) == 1 else self.league.nouns
        queued = f"{len(new)} new {noun}" + (f" ({', '.join(new)})" if new else "")
        log.info(f"{self.league.name}: queued {queued}, {len(lobbies) - len(new)} already queued or up")

        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self._work())

    async def stop(self) -> None:
        """Stop the worker. Lobbies still queued are dropped, and the next webhook queues them again."""
        if self.worker:
            self.worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.worker

    async def _work(self) -> None:
        while True:
            lobby = await self.queue.get()
            try:
                await self._create(lobby)
                if self.queue.empty():
                    await self._sort_new_channels()
            except Exception as exc:
                log.exception(f"Error starting {self.league.label} {lobby.id}", exc_info=exc)
            finally:
                self.queue.task_done()

    async def _create(self, lobby: CombinesLobby) -> None:
        key = (lobby.guild_id, lobby.id)
        label = f"{self.league.label} {lobby.id}"
        if key not in self.active_lobbies:
            log.info(f"{_sentence(label)} finished before it was created. Skipping.")
            return

        channels: list[discord.VoiceChannel] = []
        try:
            channels = await asyncio.wait_for(self.create_channels(lobby), LOBBY_TIMEOUT)
        except Exception as exc:
            log.exception(f"Error creating {label}", exc_info=exc)
        finally:
            # Nothing is up, so let a later webhook try again
            if not channels:
                self.active_lobbies.discard(key)

    async def create_channels(self, lobby: CombinesLobby) -> list[discord.VoiceChannel]:
        """Bring a lobby fully up: both voice channels and its card. Empty when it can't be.

        Each part already there is kept, so a lobby left half made, or sent again after a
        restart, is finished instead of duplicated.
        """
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

        names = [self.league.channel_name(lobby, "home"), self.league.channel_name(lobby, "away")]
        existing = [c if isinstance(c := discord.utils.get(guild.channels, name=name), discord.VoiceChannel) else None for name in names]
        has_card = str(lobby.id) in await self.league.store(guild).LobbyMessages()
        if all(existing) and has_card:
            log.warning(f"{_sentence(label)} is already up. Skipping.")
            return [c for c in existing if c]

        players = await self.cog.combine_players_from_lobby(guild, lobby)
        if not players:
            log.error(f"{_sentence(label)} has no players in the guild")
            return []

        try:
            league_role = await utils.get_league_role(guild)
        except ValueError:
            log.error(f"League role does not exist. Can't create {label}.")
            return []

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

        channels = []
        target: discord.CategoryChannel | None = None
        for name, found in zip(names, existing, strict=True):
            if found:
                log.info(f"{_sentence(label)} already has {name}. Keeping it.")
                channels.append(found)
                continue
            target = target or await self.target_category(guild, category)
            channel = await target.create_voice_channel(name=name, overwrites=overwrites, reason=f"Starting {label}", user_limit=5)
            self.unsorted.setdefault(target, []).append(channel)
            channels.append(channel)

        if not has_card:
            announce_channel = await self.league.announce_channel(guild)
            if announce_channel:
                await self.announce(guild, lobby, channels, announce_channel)
            else:
                log.warning(f"{self.league.name} announcement channel not found. {_sentence(label)} has no card.")

        log.info(f"Started {label}")
        return channels

    async def _sort_new_channels(self) -> None:
        unsorted, self.unsorted = self.unsorted, {}
        for category, new in unsorted.items():
            try:
                await self.place(category, new)
            except discord.HTTPException as exc:
                log.warning(f"Unable to sort {self.league.name} channels in {category.name}", exc_info=exc)

    async def place(self, category: discord.CategoryChannel, new: list[discord.VoiceChannel]) -> None:
        """Slot new channels into the category by the league's `sort_key` with one position update.

        Sent as one bulk update because `channel.move()` builds its payload from the channel
        cache, which may not hold the new channels yet. Nothing is sent when they already sit in order.
        """
        key = self.league.sort_key
        if all(key(c.name) is None for c in new):
            return

        new_ids = {c.id for c in new}
        shown = sorted([*(c for c in category.voice_channels if c.id not in new_ids), *new], key=lambda c: (c.position, c.id))
        ordered = [c for c in shown if c.id not in new_ids]
        for channel in new:
            mine = key(channel.name)
            later = (i for i, c in enumerate(ordered) if mine is not None and (theirs := key(c.name)) is not None and theirs > mine)
            ordered.insert(next(later, len(ordered)), channel)
        if [c.id for c in ordered] == [c.id for c in shown]:
            return

        payload: list[ChannelPositionUpdate] = [{"id": c.id, "position": position} for position, c in enumerate(ordered)]
        await category.guild._state.http.bulk_channel_update(category.guild.id, payload, reason=f"Sorting {self.league.name} channels")

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

    async def teardown(self, guild: discord.Guild, lobby_id: int, *, delay: bool = True) -> None:
        """Turn the lobby's card Final at once, then delete its voice channels after the grace period."""
        log.debug(f"Tearing down {self.league.label} {lobby_id}")
        # Lobby DMs still queued would only show stale details, so they're dropped from here on
        self.active_lobbies.discard((guild.id, lobby_id))

        # The lobby details are done with, so the card turns Final with the score right away
        store = self.league.store(guild)
        entry = await lobby_messages(store, lobby_id)
        if entry:
            await finish_lobby(self.cog, entry, store, await self.league.final_score(guild, entry))

        if delay:
            await asyncio.sleep(self.TEARDOWN_DELAY)

        category = await self.league.category(guild)
        if not category:
            log.error(f"{self.league.name} category not configured. Can't tear down {self.league.label} {lobby_id}.")
            return

        for cat in self.categories(guild, category):
            for channel in cat.voice_channels:
                if is_lobby_channel(channel.name, lobby_id):
                    log.debug(f"Deleting {channel.name}")
                    # Already gone if another teardown of this match, or staff, got there first
                    with contextlib.suppress(discord.NotFound):
                        await channel.delete(reason=f"{_sentence(self.league.label)} {lobby_id} has finished.")

    async def open_lobbies(self, guild: discord.Guild) -> set[int]:
        """IDs of every lobby queued, with a card still live, or with a voice channel still up."""
        lobby_ids = {lobby_id for guild_id, lobby_id in self.active_lobbies if guild_id == guild.id}
        lobby_ids |= {int(k) for k in await self.league.store(guild).LobbyMessages() if k.isdigit()}
        category = await self.league.category(guild)
        if category:
            for cat in self.categories(guild, category):
                for channel in cat.voice_channels:
                    if parsed := parse_lobby_channel(channel.name):
                        lobby_ids.add(parsed[1])
        return lobby_ids

    async def end_now(self, guild: discord.Guild, lobby_ids: list[int]) -> list[int]:
        """Tear down each lobby without the grace period. Returns the IDs that failed."""
        failed = []
        # One failed lobby must not stop the rest from being ended
        for lobby_id in lobby_ids:
            try:
                await self.teardown(guild, lobby_id, delay=False)
            except discord.HTTPException as exc:
                log.exception(f"Error tearing down {self.league.label} {lobby_id}", exc_info=exc)
                failed.append(lobby_id)
        return failed
