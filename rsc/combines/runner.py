import asyncio
import json
import logging

import aiohttp
import discord
import pydantic

from rsc.abc import RSCMixIn
from rsc.combines import models
from rsc.embeds import BlueEmbed
from rsc.exceptions import CombinesNotActive, NotInGuild
from rsc.utils import utils
from rsc.views import LinkButton

log = logging.getLogger("red.rsc.combines.runner")


class CombineRunnerMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing CombineMixIn:Runner")
        super().__init__()

    async def combines_event_handler(self, request: aiohttp.web.Request):
        log.debug("Received combines event")

        try:
            data = await request.json()
            from pprint import pformat

            log.debug(f"body:\n\n{pformat(data)}\n\n")
            event = models.CombineEvent(**data)
        except json.JSONDecodeError:
            log.warning("Received combines webhook with no JSON data")
            return aiohttp.web.Response(status=400)  # 400 Bad Request
        except pydantic.ValidationError as exc:
            log.exception("Error deserializing combine game lobby", exc_info=exc)
            return aiohttp.web.Response(status=400)  # 400 Bad Request

        # Only support RSC NA 3v3 right now
        guild: discord.Guild | None = None
        for g in self.bot.guilds:
            if g.id == 991044575567179856:  # nickmdev
                guild = g
                break
            if g.id == 395806681994493964:  # RSC 3v3
                guild = g
                break

        if not guild:
            log.error("Bot is not in the configured combines guild")
            return aiohttp.web.Response(status=503)  # 503 Service Unavailable

        match event.message_type:
            case models.CombineEventType.Finished:
                if not event.match_id:
                    log.warning("Received finished combine lobby but no lobby id.")
                    return aiohttp.web.Response(status=400)  # 400 Bad Request
                else:
                    asyncio.create_task(
                        self.teardown_combine_lobby(guild, lobby_id=event.match_id)
                    )
                    return aiohttp.web.Response(status=200)  # 200 OK
            case _:
                return aiohttp.web.Response(status=501)  # 400 Not Implemented

    async def start_combines_game(self, request: aiohttp.web.Request):
        log.debug("Received request to create combine game")

        try:
            data = await request.json()
        except json.JSONDecodeError:
            log.warning("Received combines webhook with no JSON data")
            return aiohttp.web.Response(status=400)  # 400 Bad Request

        log.debug("Processing combine lobbies")
        lobby_list: list[models.CombinesLobby] = []
        try:
            for v in data.values():
                lobby_list.append(models.CombinesLobby(**v))
        except pydantic.ValidationError as exc:
            log.exception("Error deserializing combine game lobby", exc_info=exc)
            return aiohttp.web.Response(status=400)  # 400 Bad Request

        if not lobby_list:
            log.warning("Received combines HTTP request with no data")
            return aiohttp.web.Response(status=400)  # 400 Bad Request

        log.debug("Sending combine lobbies to creation")
        for lobby in lobby_list:
            try:
                await self.create_combine_lobby_channel(lobby)
            except (NotInGuild, CombinesNotActive):
                return aiohttp.web.Response(status=503)  # 503 Service Unavailable

        # Send HTTP 200 OK
        log.debug("Sending HTTP response.")
        return aiohttp.web.Response(status=200)

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
            log.warning(
                f"Bot is not in the specified combine guild ID: {lobby.guild_id}"
            )
            raise NotInGuild()

        # Check if active
        active = await self._get_combines_active(guild)
        if not active:
            log.warning(f"Combines are not active in guild ID: {lobby.guild_id}")
            raise CombinesNotActive()

        combine_category = await self._get_combines_category(guild)
        if not combine_category:
            log.error("Combine category not configured. Can't create game.")
            return []

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
        if len(combine_category.channels) > 48:
            for i in range(2, 5):
                next_category = discord.utils.get(
                    guild.channels, name=f"{combine_category.name}-2"
                )

                if not next_category:
                    next_category = await guild.create_category(
                        name=f"{combine_category.name}-{i}",
                        reason="Combines channels have maxed out.",
                    )
                    combine_category = next_category
                    break

                if not isinstance(next_category, discord.CategoryChannel):
                    log.warning(
                        f"Combine category is already in use and not a category: {next_category}"
                    )
                    continue

                if len(next_category.channels) <= 48:
                    combine_category = next_category
                    break
        log.debug(f"Combine Category: {combine_category.name}")

        # Set up channel permissions
        muted_role = await utils.get_muted_role(guild)
        league_role = await utils.get_league_role(guild)
        if not league_role:
            log.error("League role does not exist in guild.")
            return []

        player_overwrites = {
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
            player_overwrites[muted_role] = discord.PermissionOverwrite(
                view_channel=True, connect=False, speak=False
            )

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
        await self.announce_combines_lobby(
            guild, lobby=lobby, channels=[home_channel, away_channel]
        )

        return [home_channel, away_channel]

    async def announce_combines_lobby(
        self,
        guild: discord.Guild,
        lobby: models.CombinesLobby,
        channels: list[discord.VoiceChannel],
    ) -> discord.Message:
        if len(channels) != 2:
            raise ValueError(
                "Must provide 2 voice channels to announce a combine lobby."
            )

        announce_channel = discord.utils.get(
            guild.channels, name="combines-announcements"
        )
        if not announce_channel:
            raise RuntimeError("Combine lobby announcement channel doesn't exit.")

        if not isinstance(announce_channel, discord.TextChannel):
            raise RuntimeError(
                "Combine lobbies announcement channel is not of type `disord.TextChannel`"
            )

        home_fmt = []
        for player in lobby.home:
            m = guild.get_member(player.discord_id)
            if not m:
                home_fmt.append(player.name)
            else:
                home_fmt.append(m.mention)

        # Define who creates lobby
        home_fmt[0] += " (Makes Lobby)"

        away_fmt = []
        for player in lobby.away:
            m = guild.get_member(player.discord_id)
            if not m:
                away_fmt.append(player.name)
            else:
                away_fmt.append(m.mention)

        players = await self.combine_players_from_lobby(guild, lobby)
        players_fmt = " ".join([m.mention for m in players])

        game_info_fmt = (
            f"Name: **{lobby.lobby_user}**\n" f"Password: **{lobby.lobby_pass}**"
        )

        channel_fmt = f"Home: {channels[0].mention}\n" f"Away: {channels[1].mention}"

        embed = BlueEmbed(title=f"Combine {lobby.id} Ready!")

        embed.add_field(name="Lobby Info", value=game_info_fmt, inline=False)
        embed.add_field(name="Voice Channels", value=channel_fmt, inline=False)

        embed.add_field(name="Home Team", value="\n".join(home_fmt), inline=True)
        embed.add_field(name="Away Team", value="\n".join(away_fmt), inline=True)

        embed.set_footer(
            text="You can check your active game info with `/combines lobbyinfo`"
        )

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        match_link = LinkButton(
            label="Match Link", url=f"https://devleague.rscna.com/combine/{lobby.id}"
        )
        link_view = discord.ui.View()
        link_view.add_item(match_link)

        msg = await announce_channel.send(
            content=players_fmt, embed=embed, view=link_view
        )

        return msg

    async def teardown_combine_lobby(self, guild: discord.Guild, lobby_id: int):
        # Make teardown less abrupt for players
        await asyncio.sleep(30)

        log.debug(f"Tearing down combine lobby: {lobby_id}")

        # Loop guild since we don't know the lobby tier
        gchannels = guild.channels
        for channel in gchannels:
            if not channel.category:
                continue

            if not channel.category.name.lower().startswith("combines"):
                continue

            if channel.name.endswith(f"{lobby_id}-home"):
                log.debug(f"Deleting {channel.name}")
                await channel.delete(reason="Combine lobby has finished.")
                continue

            if channel.name.endswith(f"{lobby_id}-away"):
                log.debug(f"Deleting {channel.name}")
                await channel.delete(reason="Combine lobby has finished.")
