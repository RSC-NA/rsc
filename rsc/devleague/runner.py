import asyncio
import json
import logging
from pprint import pformat
from typing import TYPE_CHECKING

import discord
import pydantic
from aiohttp import web

from rsc.abc import RSCMixIn
from rsc.combines.lobby import finish_lobby, lobby_card, lobby_messages, post_lobby
from rsc.combines.views import LobbyKind
from rsc.devleague import models
from rsc.devleague.api import DEVLEAGUE_API_URL
from rsc.devleague.tiers import channel_sort_key, lobby_channel_name, parse_lobby_channel
from rsc.exceptions import DevLeagueNotActive, NotInGuild
from rsc.utils import utils

if TYPE_CHECKING:
    from discord.types.guild import ChannelPositionUpdate

log = logging.getLogger("red.rsc.devleague.runner")

background_tasks = set()

# (guild ID, match ID) of lobbies being created or still up. New channels can
# take a moment to reach the guild cache, so a duplicate webhook could slip past
# the channel name check without this.
active_lobbies: set[tuple[int, int]] = set()

# Discord allows 50 channels per category. Leave headroom before overflowing.
CATEGORY_CHANNEL_LIMIT = 40
OVERFLOW_CATEGORIES = range(2, 5)


class DevLeagueRunnerMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing DevLeagueMixIn:Runner")
        super().__init__()

    async def devleague_event_handler(self, request: web.Request):
        log.debug("Received dev league event")

        try:
            data = await request.json()
            log.debug(f"body:\n\n{pformat(data)}\n\n")
            event = models.DevLeagueEvent(**data)
        except json.JSONDecodeError:
            log.warning("Received dev league event with no JSON data")
            return web.Response(status=400)  # 400 Bad Request
        except pydantic.ValidationError as exc:
            log.exception("Error deserializing dev league event", exc_info=exc)
            return web.Response(status=400)  # 400 Bad Request

        guild = self.bot.get_guild(event.guild_id)
        if not guild:
            log.error(f"Bot is not in the dev league guild ID: {event.guild_id}")
            return web.Response(status=503)  # 503 Service Unavailable

        match event.message_type:
            case models.DevLeagueEventType.Finished:
                if not event.match_id:
                    log.warning("Received finished dev league game but no match id.")
                    return web.Response(status=400)  # 400 Bad Request
                task = asyncio.create_task(self.teardown_devleague_lobby(guild, lobby_id=event.match_id))
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
                return web.Response(status=200)  # 200 OK
            case _:
                return web.Response(status=501)  # 501 Not Implemented

    async def start_devleague_game(self, request: web.Request):
        log.debug("Received request to create dev league game")

        try:
            data = await request.json()
        except json.JSONDecodeError:
            log.warning("Received dev league game webhook with no JSON data")
            return web.Response(status=400)  # 400 Bad Request

        if not isinstance(data, dict):
            log.warning("Received dev league game webhook that is not a JSON object")
            return web.Response(status=400)  # 400 Bad Request

        lobby_list: list[models.DevLeagueLobby] = []
        try:
            for v in data.values():
                log.debug(f"Dev League Raw Lobby: {v}")
                lobby_list.append(models.DevLeagueLobby(**v))
        except pydantic.ValidationError as exc:
            log.exception("Error deserializing dev league game lobby", exc_info=exc)
            return web.Response(status=400)  # 400 Bad Request

        if not lobby_list:
            log.warning("Received dev league game webhook with no lobbies")
            return web.Response(status=400)  # 400 Bad Request

        # Checked up front so the caller still gets a 503 when nothing can be created.
        for guild_id in {lobby.guild_id for lobby in lobby_list}:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                log.warning(f"Bot is not in the dev league guild ID: {guild_id}")
                return web.Response(status=503)  # 503 Service Unavailable
            if not await self._get_devleague_active(guild):
                log.warning(f"Dev League is not active in guild ID: {guild_id}")
                return web.Response(status=503)  # 503 Service Unavailable

        # Channel creation is rate limited by Discord and can outlast the caller's
        # HTTP timeout. Respond now so a timed out request is not retried into
        # duplicate lobbies.
        task = asyncio.create_task(self._create_devleague_lobbies(lobby_list))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        return web.Response(status=200)

    async def _create_devleague_lobbies(self, lobbies: list[models.DevLeagueLobby]):
        # One failed lobby must not stop the rest from being created.
        for lobby in lobbies:
            key = (lobby.guild_id, lobby.id)
            if key in active_lobbies:
                log.warning(f"Dev League match {lobby.id} is already active. Skipping duplicate.")
                continue

            active_lobbies.add(key)
            channels: list[discord.VoiceChannel] = []
            try:
                channels = await self.create_devleague_lobby_channels(lobby)
            except (NotInGuild, DevLeagueNotActive):
                log.warning(f"Dev League became unavailable before match {lobby.id} was created")
            except Exception as exc:
                log.exception(f"Error creating dev league match {lobby.id}", exc_info=exc)
            finally:
                # Nothing was created, so let a later request try again.
                if not channels:
                    active_lobbies.discard(key)

    async def create_devleague_lobby_channels(self, lobby: models.DevLeagueLobby) -> list[discord.VoiceChannel]:
        log.debug(f"Creating dev league lobby channels for match {lobby.id}")

        guild = self.bot.get_guild(lobby.guild_id)
        if not guild:
            log.warning(f"Bot is not in the dev league guild ID: {lobby.guild_id}")
            raise NotInGuild

        if not await self._get_devleague_active(guild):
            log.warning(f"Dev League is not active in guild ID: {lobby.guild_id}")
            raise DevLeagueNotActive

        category = await self._get_devleague_category(guild)
        if not category:
            log.error("Dev League category not configured. Can't create game.")
            return []

        home_name = lobby_channel_name(lobby.tier, lobby.id, "home")
        away_name = lobby_channel_name(lobby.tier, lobby.id, "away")
        for name in (home_name, away_name):
            exists = discord.utils.get(guild.channels, name=name)
            if exists:
                log.error(f"Dev League lobby already exists: {exists.name}")
                return []

        players = await self.combine_players_from_lobby(guild, lobby)
        if not players:
            log.error(f"Dev League match {lobby.id} has no players in the guild")
            return []

        try:
            league_role = await utils.get_league_role(guild)
        except ValueError:
            log.error(f"League role does not exist. Can't create dev league match {lobby.id}.")
            return []

        target = await self._devleague_target_category(guild, category)

        # Only league members can join. Everyone else can see the channel.
        overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
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
        }

        reason = f"Starting dev league match {lobby.id}"
        home_channel = await target.create_voice_channel(name=home_name, overwrites=overwrites, reason=reason, user_limit=5)
        away_channel = await target.create_voice_channel(name=away_name, overwrites=overwrites, reason=reason, user_limit=5)

        try:
            await self._sort_devleague_lobby(target, home_channel, away_channel)
        except discord.HTTPException as exc:
            log.warning(f"Unable to sort dev league lobby {lobby.id} by tier", exc_info=exc)

        announce_channel = await self._get_devleague_announce_channel(guild)
        if announce_channel:
            await self.announce_devleague_lobby(
                guild, lobby=lobby, channels=[home_channel, away_channel], announce_channel=announce_channel
            )
        else:
            log.debug("Dev League announcement channel not configured. Skipping announcement.")

        return [home_channel, away_channel]

    async def _devleague_target_category(self, guild: discord.Guild, category: discord.CategoryChannel) -> discord.CategoryChannel:
        """Return the configured category, or an overflow category if it is full."""
        if len(category.channels) <= CATEGORY_CHANNEL_LIMIT:
            return category

        log.debug("Dev League category is full, looking for next available category")
        for i in OVERFLOW_CATEGORIES:
            name = f"{category.name}-{i}"
            next_category = discord.utils.get(guild.channels, name=name)

            if not next_category:
                log.debug(f"Creating overflow dev league category: {name}")
                return await guild.create_category(
                    name=name,
                    position=category.position + 1,
                    reason="Dev League channels have maxed out.",
                )

            if not isinstance(next_category, discord.CategoryChannel):
                log.warning(f"Dev League overflow name is already in use and not a category: {next_category}")
                continue

            if len(next_category.channels) <= CATEGORY_CHANNEL_LIMIT:
                return next_category

        log.warning("All dev league overflow categories are full. Using the configured category.")
        return category

    def _devleague_categories(self, guild: discord.Guild, category: discord.CategoryChannel):
        """The configured category followed by any overflow categories that exist."""
        yield category
        for i in OVERFLOW_CATEGORIES:
            overflow = discord.utils.get(guild.categories, name=f"{category.name}-{i}")
            if overflow:
                yield overflow

    async def _sort_devleague_lobby(
        self,
        category: discord.CategoryChannel,
        home: discord.VoiceChannel,
        away: discord.VoiceChannel,
    ):
        """Place a new lobby's channels so game channels stay ordered S+ -> F.

        Sent as a single position update because two `channel.move()` calls
        build their payloads from the channel cache, which does not yet include
        the new channels' positions.
        """
        new_ids = {home.id, away.id}
        existing = sorted(
            (c for c in category.voice_channels if c.id not in new_ids),
            key=lambda c: (c.position, c.id),
        )

        home_key = channel_sort_key(home.name)
        index = len(existing)
        for i, channel in enumerate(existing):
            key = channel_sort_key(channel.name)
            if key is not None and home_key is not None and key > home_key:
                index = i
                break

        ordered = [*existing[:index], home, away, *existing[index:]]
        payload: list[ChannelPositionUpdate] = [{"id": c.id, "position": position} for position, c in enumerate(ordered)]
        await category.guild._state.http.bulk_channel_update(
            category.guild.id,
            payload,
            reason="Sorting dev league channels by tier",
        )

    async def announce_devleague_lobby(
        self,
        guild: discord.Guild,
        lobby: models.DevLeagueLobby,
        channels: list[discord.VoiceChannel],
        announce_channel: discord.TextChannel,
    ) -> discord.Message:
        if len(channels) != 2:
            raise ValueError("Must provide 2 voice channels to announce a dev league lobby.")

        card = lobby_card(
            guild,
            lobby,
            kind=LobbyKind.DEV_LEAGUE,
            channels=channels,
            match_url=f"{DEVLEAGUE_API_URL}/match/{lobby.id}",
            started_at=discord.utils.utcnow(),
        )
        return await post_lobby(self, guild, lobby, card, announce_channel, self.config.custom("DevLeague", str(guild.id)), active_lobbies)

    async def teardown_devleague_lobby(self, guild: discord.Guild, lobby_id: int):
        # Make teardown less abrupt for players
        await asyncio.sleep(30)

        log.debug(f"Tearing down dev league lobby: {lobby_id}")
        active_lobbies.discard((guild.id, lobby_id))

        # Dev League has no score endpoint, so the Final card shows no score
        store = self.config.custom("DevLeague", str(guild.id))
        entry = await lobby_messages(store, lobby_id)
        if entry:
            await finish_lobby(self, entry, store, score=None)

        category = await self._get_devleague_category(guild)
        if not category:
            log.error("Dev League category not configured. Can't tear down game.")
            return

        for cat in self._devleague_categories(guild, category):
            for channel in cat.voice_channels:
                parsed = parse_lobby_channel(channel.name)
                if parsed and parsed[1] == lobby_id:
                    log.debug(f"Deleting {channel.name}")
                    await channel.delete(reason="Dev League match has finished.")
