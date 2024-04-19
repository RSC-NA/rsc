import logging
from functools import wraps

import discord
from redbot.core import app_commands

from rsc.abc import RSCMixIn
from rsc.combines import api, models
from rsc.combines.manager import CombineManagerMixIn
from rsc.combines.runner import CombineRunnerMixIn
from rsc.embeds import BlueEmbed, ErrorEmbed, YellowEmbed
from rsc.exceptions import BadGateway
from rsc.tiers import TierMixIn
from rsc.types import CombineSettings

log = logging.getLogger("red.rsc.combines")


defaults_guild = CombineSettings(
    Active=False,
    CombinesApi=None,
    CombinesCategory=None,
)


def active_combines(f):
    """Combines decorator that verified Combines have started"""

    @wraps(f)
    async def combine_wrapper(
        cls: "CombineMixIn", interaction: discord.Interaction, *args, **kwargs
    ):
        if not interaction.guild:
            return

        active = await cls._get_combines_active(interaction.guild)
        if not active:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines are not currently active."),
                ephemeral=True,
            )

        api_url = await cls._get_combines_api(interaction.guild)
        if not api_url:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines API has not been configured."),
                ephemeral=True,
            )

        return await f(cls, interaction, *args, **kwargs)

    return combine_wrapper


class CombineMixIn(CombineRunnerMixIn, CombineManagerMixIn, RSCMixIn):
    def __init__(self):
        log.debug("Initializing CombineMixIn")
        super().__init__()

    # Group

    _combines = app_commands.Group(
        name="combines",
        description="Play in RSC Combines",
        guild_only=True,
    )

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
                embed=ErrorEmbed(
                    title="Combines Check Out", description=result.message
                ),
                ephemeral=True,
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
    async def _combines_lobby_info_cmd(
        self, interaction: discord.Interaction, lobby_id: int | None = None
    ):
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
            result = await api.combines_lobby(url, executor=player, lobby_id=lobby_id)
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
            description="Displaying lobby information for combine match.",
        )

        lobby_info = f"Name: **{result.lobby_user}**\nPassword: **{result.lobby_pass}**"

        team_fmt = None
        for hplayer, aplayer in zip(result.home, result.away):
            if hplayer.discord_id == interaction.user.id:
                team_fmt = "Home (Blue)"
                break
            if aplayer.discord_id == interaction.user.id:
                team_fmt = "Away (Orange)"
                break

        embed.add_field(name="Lobby Info", value=lobby_info, inline=True)

        if team_fmt:
            embed.add_field(name="Team", value=team_fmt, inline=True)

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_combines.command(  # type: ignore
        name="active", description="Display active combine games"
    )
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)  # type: ignore
    @app_commands.describe(
        player="Only show games with containing discord member (Optional)",
        tier="Only show games with average tier (Optional)",
    )
    async def _combines_active_cmd(
        self,
        interaction: discord.Interaction,
        player: discord.Member | None = None,
        tier: str | None = None,
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

        if isinstance(results, models.CombinesStatus):
            return await interaction.response.send_message(
                embed=ErrorEmbed(description=results.message), ephemeral=True
            )

        if not results:
            return await interaction.response.send_message(
                embed=YellowEmbed(
                    title="Active Combine Games",
                    description="There are no active games currently.",
                ),
                ephemeral=True,
            )

        filtered = await self.filter_combine_lobbies(
            guild, results, player=player, tier=tier
        )

        embed = BlueEmbed(
            title="Active Combine Games",
            description="Showing active combine games",
        )

        embed.add_field(name="ID", value="\n".join([str(i.id) for i in filtered]))
        embed.add_field(name="Tier", value="\n".join([i.tier for i in filtered]))

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # Functions

    async def filter_combine_lobbies(
        self,
        guild: discord.Guild,
        lobbies: list[models.CombinesLobby],
        tier: str | None = None,
        player: discord.Member | None = None,
    ) -> list[models.CombinesLobby]:
        final = []
        for lobby in lobbies:
            if lobby.completed or lobby.cancelled:
                continue

            if tier and lobby.tier != tier:
                continue

            if player:
                plist = await self.combine_players_from_lobby(guild, lobby)
                if player not in plist:
                    continue
            final.append(lobby)
        return final

    async def get_combine_room_list(
        self, guild: discord.Guild
    ) -> list[discord.CategoryChannel]:
        """Get a list of combine categories in the guild"""
        categories = []
        for x in guild.categories:
            if x.name.startswith("combine-"):
                categories.append(x)
        return categories

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
