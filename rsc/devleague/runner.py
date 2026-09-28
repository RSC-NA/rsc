import asyncio
import json
import logging
from pprint import pformat
from typing import TYPE_CHECKING

import discord
import pydantic
from aiohttp import web

from rsc.abc import RSCMixIn
from rsc.devleague import models
from rsc.devleague.api import DEVLEAGUE_API_URL
from rsc.devleague.tiers import channel_sort_key, lobby_channel_name, parse_lobby_channel
from rsc.embeds import BlueEmbed
from rsc.exceptions import DevLeagueNotActive, NotInGuild
from rsc.views import LinkButton

if TYPE_CHECKING:
    from discord.types.guild import ChannelPositionUpdate

log = logging.getLogger("red.rsc.devleague.runner")

background_tasks = set()

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

        for lobby in lobby_list:
            try:
                await self.create_devleague_lobby_channels(lobby)
            except (NotInGuild, DevLeagueNotActive):
                return web.Response(status=503)  # 503 Service Unavailable

        return web.Response(status=200)

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

        target = await self._devleague_target_category(guild, category)

        # Only the lobby's players can join. Everyone else can see the channel.
        overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                connect=False,
                speak=False,
                send_messages=False,
                add_reactions=False,
            ),
        }
        for player in players:
            overwrites[player] = discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                speak=True,
                stream=True,
                send_messages=True,
                add_reactions=True,
            )

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

        def fmt_team(team: list) -> list[str]:
            fmt = []
            for player in team:
                m = guild.get_member(player.discord_id)
                fmt.append(m.mention if m else player.name)
            return fmt

        home_fmt = fmt_team(lobby.home)
        away_fmt = fmt_team(lobby.away)

        # Define who creates lobby
        if home_fmt:
            home_fmt[0] += " (Makes Lobby)"

        players = await self.combine_players_from_lobby(guild, lobby)
        players_fmt = " ".join([m.mention for m in players])

        game_info_fmt = f"Name: **{lobby.lobby_user}**\nPassword: **{lobby.lobby_pass}**"
        channel_fmt = f"Home: {channels[0].mention}\nAway: {channels[1].mention}"

        embed = BlueEmbed(title=f"Dev League {lobby.tier} Match {lobby.id} Ready!")
        embed.add_field(name="Tier", value=lobby.tier, inline=False)
        embed.add_field(name="Lobby Info", value=game_info_fmt, inline=False)
        embed.add_field(name="Voice Channels", value=channel_fmt, inline=False)
        embed.add_field(name="Home Team", value="\n".join(home_fmt) or "None", inline=True)
        embed.add_field(name="Away Team", value="\n".join(away_fmt) or "None", inline=True)

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        match_link = LinkButton(label="Match Link", url=f"{DEVLEAGUE_API_URL}/match/{lobby.id}")
        link_view = discord.ui.View()
        link_view.add_item(match_link)

        return await announce_channel.send(content=players_fmt, embed=embed, view=link_view)

    async def teardown_devleague_lobby(self, guild: discord.Guild, lobby_id: int):
        # Make teardown less abrupt for players
        await asyncio.sleep(30)

        log.debug(f"Tearing down dev league lobby: {lobby_id}")

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
