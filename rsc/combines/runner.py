import asyncio
import json
import logging
from pprint import pformat

import aiohttp
from aiohttp import web
import discord
import pydantic

from rsc import const
from rsc.abc import RSCMixIn
from rsc.combines import api, models
from rsc.combines.lobby import LobbyMessages, finish_lobby, lobby_card, lobby_messages, post_lobby
from rsc.combines.views import LobbyKind, LobbyScore
from rsc.exceptions import BadGateway, CombinesNotActive, NotInGuild
from rsc.utils import utils

log = logging.getLogger("red.rsc.combines.runner")

background_tasks = set()

# (guild ID, lobby ID) of lobbies being created or still up. New channels can
# take a moment to reach the guild cache, so a duplicate webhook could slip past
# the channel name check without this.
active_lobbies: set[tuple[int, int]] = set()


class CombineRunnerMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing CombineMixIn:Runner")
        super().__init__()

    async def combines_event_handler(self, request: web.Request):
        log.debug("Received combines event")

        try:
            data = await request.json()
            log.debug(f"body:\n\n{pformat(data)}\n\n")
            event = models.CombineEvent(**data)
        except json.JSONDecodeError:
            log.warning("Received combines webhook with no JSON data")
            return web.Response(status=400)  # 400 Bad Request
        except pydantic.ValidationError as exc:
            log.exception("Error deserializing combine game lobby", exc_info=exc)
            return web.Response(status=400)  # 400 Bad Request

        # Only support RSC NA 3v3 right now
        log.debug(f"Looking for Guild ID: {event.guild_id}")
        guild: discord.Guild | None = None
        for g in self.bot.guilds:
            if g.id == event.guild_id:  # nickmdev
                guild = g
                break

        if not guild:
            log.error("Bot is not in the configured combines guild")
            return web.Response(status=503)  # 503 Service Unavailable

        match event.message_type:
            case models.CombineEventType.Finished:
                if not event.match_id:
                    log.warning("Received finished combine lobby but no lobby id.")
                    return web.Response(status=400)  # 400 Bad Request
                else:
                    task = asyncio.create_task(self.teardown_combine_lobby(guild, lobby_id=event.match_id))
                    background_tasks.add(task)
                    task.add_done_callback(background_tasks.discard)
                    return web.Response(status=200)  # 200 OK
            case _:
                return web.Response(status=501)  # 400 Not Implemented

    async def start_combines_game(self, request: web.Request):
        log.debug("Received request to create combine game")

        try:
            data = await request.json()
        except json.JSONDecodeError:
            log.warning("Received combines webhook with no JSON data")
            return web.Response(status=400)  # 400 Bad Request

        if not isinstance(data, dict):
            log.warning("Received combines webhook that is not a JSON object")
            return web.Response(status=400)  # 400 Bad Request

        log.debug("Processing combine lobbies")
        lobby_list: list[models.CombinesLobby] = []
        try:
            for v in data.values():
                log.debug(f"Combine Raw Lobby: {v}")
                lobby_list.append(models.CombinesLobby(**v))
        except pydantic.ValidationError as exc:
            log.exception("Error deserializing combine game lobby", exc_info=exc)
            return web.Response(status=400)  # 400 Bad Request

        if not lobby_list:
            log.warning("Received combines HTTP request with no data")
            return web.Response(status=400)  # 400 Bad Request

        # Checked up front so the caller still gets a 503 when nothing can be created.
        for guild_id in {lobby.guild_id for lobby in lobby_list}:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                log.warning(f"Bot is not in the specified combine guild ID: {guild_id}")
                return web.Response(status=503)  # 503 Service Unavailable
            if not await self._get_combines_active(guild):
                log.warning(f"Combines are not active in guild ID: {guild_id}")
                return web.Response(status=503)  # 503 Service Unavailable

        # Channel creation is rate limited by Discord and can outlast the caller's
        # HTTP timeout. Respond now so a timed out request is not retried into
        # duplicate lobbies.
        log.debug("Sending combine lobbies to creation")
        task = asyncio.create_task(self._create_combine_lobbies(lobby_list))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        return web.Response(status=200)

    async def _create_combine_lobbies(self, lobbies: list[models.CombinesLobby]):
        # One failed lobby must not stop the rest from being created.
        for lobby in lobbies:
            key = (lobby.guild_id, lobby.id)
            if key in active_lobbies:
                log.warning(f"Combine lobby {lobby.id} is already active. Skipping duplicate.")
                continue

            active_lobbies.add(key)
            channels: list[discord.VoiceChannel] = []
            try:
                channels = await self.create_combine_lobby_channel(lobby)
            except (NotInGuild, CombinesNotActive):
                log.warning(f"Combines became unavailable before lobby {lobby.id} was created")
            except Exception as exc:
                log.exception(f"Error creating combine lobby {lobby.id}", exc_info=exc)
            finally:
                # Nothing was created, so let a later request try again.
                if not channels:
                    active_lobbies.discard(key)

    async def create_combine_lobby_channel(
        self,
        lobby: models.CombinesLobby,
    ) -> list[discord.VoiceChannel]:
        log.debug("Creating combine lobby channels.")

        guild: discord.Guild | None = None
        for g in self.bot.guilds:
            if g.id == lobby.guild_id:
                guild = g
                break

        if not guild:
            log.warning(f"Bot is not in the specified combine guild ID: {lobby.guild_id}")
            raise NotInGuild

        # Check if active
        active = await self._get_combines_active(guild)
        if not active:
            log.warning(f"Combines are not active in guild ID: {lobby.guild_id}")
            raise CombinesNotActive

        combine_category = await self._get_combines_category(guild)
        if not combine_category:
            log.error("Combine category not configured. Can't create game.")
            return []
        log.debug(f"Combine category: {combine_category.name} {combine_category.id}")

        exists = discord.utils.get(guild.channels, name=f"{lobby.tier}-{lobby.id}-home")
        if exists:
            log.error(f"Combine lobby already exists: {exists.name}")
            return []

        exists = discord.utils.get(guild.channels, name=f"{lobby.tier}-{lobby.id}-away")
        if exists:
            log.error(f"Combine lobby already exists: {exists.name}")
            return []

        players = await self.combine_players_from_lobby(guild, lobby)
        log.debug(f"Players: {players}")

        if not players:
            log.error(f"Combine {lobby.id} has no players associated with it")
            return []

        # Check if category is full (Max: 50)
        log.debug("Finding valid combine category")
        log.debug(f"Combine category has {len(combine_category.channels)} channels")
        if len(combine_category.channels) > 40:
            log.debug("Combine category is full, looking for next available category")
            for i in range(2, 5):
                next_category = discord.utils.get(guild.channels, name=f"{combine_category.name}-{i}")
                log.debug(f"Checking next combine category: {combine_category.name}-{i}")

                if not next_category:
                    log.debug(f"Next combine category does not exist, creating: {combine_category.name}-{i}")
                    next_category = await guild.create_category(
                        name=f"{combine_category.name}-{i}",
                        reason="Combines channels have maxed out.",
                    )
                    combine_category = next_category
                    break

                if not isinstance(next_category, discord.CategoryChannel):
                    log.warning(f"Combine category is already in use and not a category: {next_category}")
                    continue

                if len(next_category.channels) <= 40:
                    log.debug(f"Found next available combine category: {combine_category.name}-{i}")
                    combine_category = next_category
                    break
        log.debug(f"Combine Category: {combine_category.name}")

        # Set up channel permissions
        # The Muted role is optional. Without it the lobby just has no muted overwrite.
        muted_role = discord.utils.get(guild.roles, name=const.MUTED_ROLE)
        try:
            league_role = await utils.get_league_role(guild)
        except ValueError:
            log.error(f"League role does not exist. Can't create combine lobby {lobby.id}.")
            return []

        player_overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
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
                send_messages=True,
                read_messages=True,
                add_reactions=True,
                stream=True,
            ),
        }
        if muted_role:
            player_overwrites[muted_role] = discord.PermissionOverwrite(view_channel=True, connect=False, speak=False)

        # Create Lobby
        log.debug("Creating combine lobby voice channels")
        home_channel = await combine_category.create_voice_channel(
            name=f"{lobby.tier}-{lobby.id}-home",
            overwrites=player_overwrites,
            reason=f"Starting combine lobby {lobby.id}",
            user_limit=5,
        )
        away_channel = await combine_category.create_voice_channel(
            name=f"{lobby.tier}-{lobby.id}-away",
            overwrites=player_overwrites,
            reason=f"Starting combine lobby {lobby.id}",
            user_limit=5,
        )

        # Announce
        log.debug("Announcing combine lobby!")
        await self.announce_combines_lobby(guild, lobby=lobby, channels=[home_channel, away_channel])

        return [home_channel, away_channel]

    async def announce_combines_lobby(
        self,
        guild: discord.Guild,
        lobby: models.CombinesLobby,
        channels: list[discord.VoiceChannel],
    ) -> discord.Message:
        if len(channels) != 2:
            raise ValueError("Must provide 2 voice channels to announce a combine lobby.")

        announce_channel = discord.utils.get(guild.channels, name="combines-announcements")
        if not announce_channel:
            raise RuntimeError("Combine lobby announcement channel doesn't exit.")

        if not isinstance(announce_channel, discord.TextChannel):
            raise RuntimeError("Combine lobbies announcement channel is not of type `disord.TextChannel`")

        card = lobby_card(
            guild,
            lobby,
            kind=LobbyKind.COMBINE,
            channels=channels,
            match_url=f"https://devleague.rscna.com/combine/{lobby.id}",
            started_at=discord.utils.utcnow(),
        )
        return await post_lobby(self, guild, lobby, card, announce_channel, self.config.custom("Combines", str(guild.id)), active_lobbies)

    async def teardown_combine_lobby(self, guild: discord.Guild, lobby_id: int):
        # Make teardown less abrupt for players
        await asyncio.sleep(30)

        log.debug(f"Tearing down combine lobby: {lobby_id}")
        active_lobbies.discard((guild.id, lobby_id))

        # The voice channels and lobby details are done with, so the card turns Final
        store = self.config.custom("Combines", str(guild.id))
        entry = await lobby_messages(store, lobby_id)
        if entry:
            await finish_lobby(self, entry, store, await self._combine_final_score(guild, entry))

        # Loop guild since we don't know the lobby tier
        gchannels = guild.channels
        for channel in gchannels:
            if not channel.category:
                continue

            if not channel.category.name.lower().startswith("combines"):
                continue

            # Names are "<tier>-<id>-home". The leading dash keeps lobby 1 from matching lobby 101.
            if channel.name.endswith(f"-{lobby_id}-home"):
                log.debug(f"Deleting {channel.name}")
                await channel.delete(reason="Combine lobby has finished.")
                continue

            if channel.name.endswith(f"-{lobby_id}-away"):
                log.debug(f"Deleting {channel.name}")
                await channel.delete(reason="Combine lobby has finished.")

    async def _combine_final_score(self, guild: discord.Guild, entry: LobbyMessages) -> LobbyScore | None:
        """The series score from the combines API, or None when it can't be read."""
        url = await self._get_combines_api(guild)
        executor = guild.get_member(entry.executor_id) if entry.executor_id else None
        if not (url and executor):
            return None
        try:
            result = await api.combines_lobby(url, executor=executor, lobby_id=entry.card.lobby_id)
        except (aiohttp.ClientError, BadGateway, ValueError, pydantic.ValidationError) as exc:
            log.warning(f"Unable to fetch the final score for combine {entry.card.lobby_id}: {exc}")
            return None
        if not isinstance(result, models.CombinesLobby) or result.cancelled:
            return None
        return LobbyScore(home_wins=result.home_wins, away_wins=result.away_wins)
