import asyncio
import json
import logging

import aiohttp
import discord
import pydantic
from redbot.core import app_commands

from rsc.abc import RSCMixIn
from rsc.combines import api, models
from rsc.const import COMBINES_HELP_1, COMBINES_HELP_2, COMBINES_HELP_3, MUTED_ROLE
from rsc.decorator import active_combines
from rsc.embeds import BlueEmbed, ErrorEmbed, GreenEmbed, YellowEmbed
from rsc.exceptions import BadGateway
from rsc.types import CombineSettings
from rsc.utils import utils

log = logging.getLogger("red.rsc.combines")


defaults_guild = CombineSettings(
    Active=False,
    CombinesApi=None,
    CombinesCategory=None,
)

COMBINE_GAME_CATEGORY = "Combine Lobbies"


class CombineMixIn(RSCMixIn):
    COMBINE_PLAYER_RATIO = 0.5

    def __init__(self):
        log.debug("Initializing CombineMixIn")

        self._combine_cache: dict[discord.Guild, list[int]] = {}

        self.config.init_custom("Combines", 1)
        self.config.register_custom("Combines", **defaults_guild)
        super().__init__()

    # Runners

    async def start_combines_runner(self):
        log.debug("Starting combines runner")

        self._combines_app = aiohttp.web.Application()
        self._combines_app.router.add_post("/combines_match", self.start_combines_game)
        self._combines_app.router.add_post(
            "/combines_event", self.combines_event_handler
        )
        self._combines_runner = aiohttp.web.AppRunner(self._combines_app)
        await self._combines_runner.setup()
        self._combines_site = aiohttp.web.TCPSite(
            self._combines_runner, "localhost", 8008
        )

        self.combines_loop_task = self.bot.loop.create_task(self._combines_site.start())

    # Settings

    _combines = app_commands.Group(
        name="combines",
        description="Combine commands and configuration",
        guild_only=True,
    )

    # Privileged Commands

    @_combines.command(name="settings", description="Display combine settings")  # type: ignore
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _combines_settings_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        active = await self._get_combines_active(guild)
        api_url = await self._get_combines_api(guild)
        category = await self._get_combines_category(guild)

        embed = discord.Embed(
            title="Combine Settings",
            description="Current configuration for Combines Cog",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Combines Active", value=active, inline=False)
        embed.add_field(name="Combines API", value=api_url, inline=False)
        embed.add_field(
            name="Combines Category",
            value=category.mention if category else "None",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_combines.command(name="category", description="Configure the combines category channel")  # type: ignore
    @app_commands.describe(category="Combines Category Channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _combines_category_cmd(
        self, interaction: discord.Interaction, category: discord.CategoryChannel
    ):
        guild = interaction.guild
        if not guild:
            return

        await self._set_combines_category(guild, category)
        await interaction.response.send_message(
            embed=GreenEmbed(
                title="Combines Category",
                description=f"Combines category has been configured: {category.mention}",
            ),
            ephemeral=True,
        )

    @_combines.command(name="api", description="Configure the API url for combines")  # type: ignore
    @app_commands.describe(
        url="Combines API location (Ex: https://devleague.rscna.com/c-api/)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _combines_api_cmd(self, interaction: discord.Interaction, url: str):
        guild = interaction.guild
        if not guild:
            return

        await self._set_combines_api(guild, url)
        await interaction.response.send_message(
            embed=GreenEmbed(
                title="Combines API",
                description=f"Combines API location has been configured: {url}",
            ),
            ephemeral=True,
        )

    @_combines.command(  # type: ignore
        name="start", description="Begin RSC combines and create channels"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _combines_start(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        status = await self._get_combines_active(guild)
        if status:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines are already active!")
            )

        api = await self._get_combines_api(guild)
        category = await self._get_combines_category(guild)

        if not api:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines API has not been configured!")
            )
        if not category:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Combines category channel has not been configured!"
                )
            )

        await interaction.response.defer(ephemeral=True)

        # Get required role references
        league_role = await utils.get_league_role(guild)
        muted_role = discord.utils.get(guild.roles, name=MUTED_ROLE)
        admin_role = discord.utils.get(guild.roles, name="Admin")
        log.debug(f"[{guild}] Default Role: {guild.default_role}")

        if not league_role:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="League role does not exist.")
            )

        if not admin_role:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Admin role does not exist.")
            )

        # Admin only overwrites
        admin_overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                connect=False,
                speak=False,
                send_messages=False,
                add_reactions=False,
            ),
            league_role: discord.PermissionOverwrite(
                view_channel=True,
                read_messages=True,
                connect=False,
                speak=False,
                send_messages=False,
                add_reactions=False,
            ),
        }

        combines_announce = discord.utils.get(
            category.channels, name="combines-announcements"
        )
        if not combines_announce:
            combines_announce = await guild.create_text_channel(
                name="combines-announcements",
                category=category,
                overwrites=admin_overwrites,
                reason="Starting combines",
            )

        # Configure permissions
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

        combines_help = discord.utils.get(category.channels, name="combines-help")
        if not combines_help:
            combines_help = await guild.create_text_channel(
                name="combines-help",
                category=category,
                overwrites=player_overwrites,
                reason="Starting combines",
            )

        # Send help message
        await self.send_combines_help_msg(combines_help)

        # Make default channels
        combines_chat = discord.utils.get(category.channels, name="combines-general")
        if not combines_chat:
            combines_chat = await guild.create_text_channel(
                name="combines-general",
                category=category,
                overwrites=player_overwrites,
                reason="Starting combines",
            )

        combines_waiting = discord.utils.get(
            category.channels, name="combines-waiting-room"
        )
        if not combines_waiting:
            combines_waiting = await guild.create_voice_channel(
                name="combines-waiting-room",
                category=category,
                overwrites=player_overwrites,
                reason="Starting combines",
            )

        await self._set_combines_active(guild, active=True)

        await interaction.followup.send(
            embed=GreenEmbed(
                title="Combines Started",
                description="Combines have been started and the required channels created.",
            )
        )

    @_combines.command(name="stop", description="End RSC combines and delete channels")  # type: ignore
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _combines_stop(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        status = await self._get_combines_active(guild)
        if not status:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines are not currently active.")
            )

        category = await self._get_combines_category(guild)

        if not category:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Combines category channel has not been configured!"
                )
            )

        await interaction.response.defer(ephemeral=True)

        # tear down combine category
        await self.delete_combine_game_rooms(category)

        await self._set_combines_active(guild, active=False)
        await interaction.followup.send(
            embed=GreenEmbed(
                title="Combines Stopped",
                description="Combines have been ended and channels deleted.",
            )
        )

    @_combines.command(  # type: ignore
        name="active", description="Display active combine games"
    )
    @app_commands.describe(player="Only show games with containing discord member")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _combines_active_cmd(
        self, interaction: discord.Interaction, player: discord.Member | None = None
    ):
        guild = interaction.guild
        if not guild:
            return

        if not isinstance(interaction.user, discord.Member):
            return

        if not player:
            player = interaction.user

        url = await self._get_combines_api(guild)
        if not url:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines API has not been configured."),
                ephemeral=True,
            )

        try:
            results = await api.combines_active(url, player)
        except BadGateway:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines API returned 502 Bad Gateway."),
                ephemeral=True,
            )

        if not results:
            return await interaction.response.send_message(
                embed=YellowEmbed(
                    title="Active Combine Games",
                    description="There are no active games currently.",
                ),
                ephemeral=True,
            )

        embed = BlueEmbed(
            title="Active Combine Games",
            description="Showing active combine games",
        )

        embed.add_field(name="ID", value="\n".join([str(i.id) for i in results]))
        embed.add_field(
            name="Home", value="\n".join([str(i.home_wins) for i in results])
        )
        embed.add_field(
            name="Away", value="\n".join([str(i.away_wins) for i in results])
        )
        embed.add_field(
            name="Complete", value="\n".join([str(i.completed) for i in results])
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # Commands

    @_combines.command(  # type: ignore
        name="checkin", description="Check in for an RSC combines match"
    )
    @active_combines
    async def _combines_check_in_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        player = interaction.user
        if not isinstance(player, discord.Member):
            return

        url = await self._get_combines_api(guild)
        if not url:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines API has not been configured."),
                ephemeral=True,
            )

        try:
            result = await api.combines_check_in(url, player)
        except BadGateway:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines API returned 502 Bad Gateway."),
                ephemeral=True,
            )

        if result.status == "error":
            return await interaction.response.send_message(
                embed=ErrorEmbed(description=result.message), ephemeral=True
            )

        await interaction.response.send_message(
            embed=BlueEmbed(
                title="Checked In",
                description="You have **checked in** for a combines match. Please be patient until your match is ready.",
            ),
            ephemeral=True,
        )

    @_combines.command(  # type: ignore
        name="checkout", description="Check out of RSC combines"
    )
    @active_combines
    async def _combines_check_out_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        player = interaction.user
        if not isinstance(player, discord.Member):
            return

        url = await self._get_combines_api(guild)
        if not url:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines API has not been configured."),
                ephemeral=True,
            )

        try:
            result = await api.combines_check_out(url, player)
        except BadGateway:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines API returned 502 Bad Gateway."),
                ephemeral=True,
            )

        if isinstance(result, models.CombinesStatus):
            return await interaction.response.send_message(
                embed=ErrorEmbed(description=result.message), ephemeral=True
            )

        await interaction.response.send_message(
            embed=BlueEmbed(
                title="Checked Out",
                description="You have **checked out** of combines. Please check in if this was a mistake.",
            ),
            ephemeral=True,
        )

    @_combines.command(  # type: ignore
        name="lobbyinfo", description="Get your active combines game lobby info"
    )
    @active_combines
    async def _combines_lobby_info_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        player = interaction.user
        if not isinstance(player, discord.Member):
            return

        url = await self._get_combines_api(guild)
        if not url:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines API has not been configured."),
                ephemeral=True,
            )

        try:
            result = await api.combines_lobby(url, player)
        except BadGateway:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines API returned 502 Bad Gateway."),
                ephemeral=True,
            )

        if isinstance(result, models.CombinesStatus):
            return await interaction.response.send_message(
                embed=ErrorEmbed(description=result.message), ephemeral=True
            )

        embed = BlueEmbed(
            title=f"Combine Match {result.id}",
            description="Displaying lobby information for combines match.",
        )

        lobby_info = (
            f"Name: **{result.lobby_user}**\n" f"Password: **{result.lobby_pass}**"
        )
        if result.team.lower() == "home":
            team_fmt = "Home (Blue)"
        else:
            team_fmt = "Away (Orange)"

        embed.add_field(name="Lobby Info", value=lobby_info, inline=True)
        embed.add_field(name="Team", value=team_fmt, inline=True)

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # Functions

    async def get_combine_room_list(
        self, guild: discord.Guild
    ) -> list[discord.CategoryChannel]:
        """Get a list of combine categories in the guild"""
        categories = []
        for x in guild.categories:
            if x.name.startswith("combine-"):
                categories.append(x)
        return categories

    async def delete_combine_category(self, category: discord.CategoryChannel):
        """Delete a combine category and it's associated channels"""
        log.debug(f"[{category.guild}] Deleting combine category: {category.name}")
        channels = category.channels
        for c in channels:
            await c.delete(reason="Combines have ended.")
        await category.delete(reason="Combines have ended.")

    async def delete_combine_game_rooms(self, category: discord.CategoryChannel):
        """Delete a combine category and it's associated channels"""
        log.debug(f"[{category.guild}] Deleting combine category: {category.name}")
        vclist = category.channels
        for vc in vclist:
            if not isinstance(vc, discord.VoiceChannel):
                continue
            if vc.name.startswith("combine-"):
                await vc.delete(reason="Combines have ended.")

    async def total_players_in_combine_category(
        self, category: discord.CategoryChannel
    ) -> int:
        total = 0
        for channel in category.voice_channels:
            total += len(channel.members)
        return total

    async def combine_players_from_lobby(
        self, guild: discord.Guild, lobby: models.CombinesLobby
    ) -> list[discord.Member]:
        players = []
        for p in lobby.home:
            m = guild.get_member(p.discord_id)
            if not m:
                log.warning(f"Unable to find combine player in guild: {p.discord_id}")
                continue
            players.append(m)

        for p in lobby.away:
            m = guild.get_member(p.discord_id)
            if not m:
                log.warning(f"Unable to find combine player in guild: {p.discord_id}")
                continue
            players.append(m)

        return players

    async def create_combine_lobby_channel(
        self,
        guild: discord.Guild,
        lobby: models.CombinesLobby,
    ) -> list[discord.VoiceChannel]:
        log.debug("Creating combine lobby channels.")
        combine_category = await self._get_combines_category(guild)
        if not combine_category:
            log.error("Combine category not configured. Can't create game.")
            return []

        exists = discord.utils.get(guild.channels, name=f"combine-{lobby.id}-home")
        if exists:
            log.error(f"Combine lobby already exists: {exists.name}")
            return []

        exists = discord.utils.get(guild.channels, name=f"combine-{lobby.id}-away")
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
            name=f"combine-{lobby.id}-home",
            overwrites=player_overwrites,
            reason=f"Starting combine lobby {lobby.id}",
            user_limit=5,
        )
        away_channel = await combine_category.create_voice_channel(
            name=f"combine-{lobby.id}-away",
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

        msg = await announce_channel.send(content=players_fmt, embed=embed)

        return msg

    async def teardown_combine_lobby(self, guild: discord.Guild, lobby_id: int):
        waiting_room = discord.utils.get(guild.channels, name="combines-waiting-room")
        home_lobby = discord.utils.get(guild.channels, name=f"combine-{lobby_id}-home")
        away_lobby = discord.utils.get(guild.channels, name=f"combine-{lobby_id}-away")

        if not isinstance(home_lobby, discord.VoiceChannel):
            raise RuntimeError(f"Combine lobby is not a voice channel: {home_lobby}")
        if not isinstance(away_lobby, discord.VoiceChannel):
            raise RuntimeError(f"Combine lobby is not a voice channel: {away_lobby}")

        # Move players to waiting room if it exists
        if isinstance(waiting_room, discord.VoiceChannel):
            log.debug("Moving combine lobby players to waiting room")
            if isinstance(home_lobby, discord.VoiceChannel):
                for m in home_lobby.members:
                    await m.move_to(waiting_room, reason="Combine lobby has ended.")
            if isinstance(away_lobby, discord.VoiceChannel):
                for m in away_lobby.members:
                    await m.move_to(waiting_room, reason="Combine lobby has ended.")

        log.debug(f"Tearing down combine lobby: {lobby_id}")
        await home_lobby.delete(reason="Combine lobby has finished.")
        await away_lobby.delete(reason="Combine lobby has finished.")

    async def send_combines_help_msg(self, channel: discord.TextChannel):
        await channel.send(content=COMBINES_HELP_1)
        await channel.send(content=COMBINES_HELP_2)
        await channel.send(content=COMBINES_HELP_3)

    # Runner

    async def combines_event_handler(self, request):
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

    async def start_combines_game(self, request):
        log.debug("Received request to create combine game")

        try:
            data = await request.json()
        except json.JSONDecodeError:
            log.warning("Received combines webhook with no JSON data")
            return aiohttp.web.Response(status=400)  # 400 Bad Request

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

        # Check if active
        active = await self._get_combines_active(guild)
        if not active:
            log.warning("Received combine match but combines are not active.")
            return aiohttp.web.Response(status=503)  # 503 Service Unavailable

        category = await self._get_combines_category(guild)
        if not category:
            log.error(
                "Received request to create combine game but combine category does not exist."
            )
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
            await self.create_combine_lobby_channel(guild, lobby)

        # Send HTTP 200 OK
        log.debug("Sending HTTP response.")
        return aiohttp.web.Response(status=200)

    async def combines_runner_cleanup(self):
        await self._combines_runner.cleanup()

    # Config

    async def _set_combines_category(
        self, guild: discord.Guild, category: discord.CategoryChannel
    ):
        await self.config.custom("Combines", str(guild.id)).CombinesCategory.set(
            category.id
        )

    async def _get_combines_category(
        self, guild: discord.Guild
    ) -> discord.CategoryChannel | None:
        cat_id = await self.config.custom("Combines", str(guild.id)).CombinesCategory()
        if not cat_id:
            return None
        category = guild.get_channel(cat_id)
        if not isinstance(category, discord.CategoryChannel):
            return None
        return category

    async def _get_combines_api(self, guild: discord.Guild) -> str | None:
        return await self.config.custom("Combines", str(guild.id)).CombinesApi()

    async def _set_combines_api(self, guild: discord.Guild, url: str):
        await self.config.custom("Combines", str(guild.id)).CombinesApi.set(url)

    async def _get_combines_active(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Combines", str(guild.id)).Active()

    async def _set_combines_active(self, guild: discord.Guild, active: bool):
        await self.config.custom("Combines", str(guild.id)).Active.set(active)
