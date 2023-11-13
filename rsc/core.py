import discord
import logging

from redbot.core import Config, app_commands, commands, checks

from rscapi import Configuration

from rsc.abc import CompositeMetaClass
from rsc.ballchasing import BallchasingMixIn
from rsc.combines import CombineMixIn
from rsc.freeagents import FreeAgentMixIn
from rsc.franchises import FranchiseMixIn
from rsc.members import MemberMixIn
from rsc.leagues import LeagueMixIn
from rsc.teams import TeamMixIn
from rsc.tiers import TierMixIn
from rsc.transactions import TransactionMixIn
from rsc.utils import UtilsMixIn
from rsc.views import LeagueSelectView

from typing import Optional, Dict

log = logging.getLogger("red.rsc.core")

defaults_guild = {
    "ApiKey": None,
    "ApiUrl": None,
    "League": None,
}


class RSC(
    BallchasingMixIn,
    CombineMixIn,
    FranchiseMixIn,
    LeagueMixIn,
    FreeAgentMixIn,
    MemberMixIn,
    TeamMixIn,
    TierMixIn,
    TransactionMixIn,
    UtilsMixIn,
    commands.Cog,
    metaclass=CompositeMetaClass,
):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=6349109713, force_registration=True
        )

        self.config.register_guild(**defaults_guild)

        # Define state of API connection
        self._api_conf: Dict[discord.Guild, Configuration] = {}
        # Cache the league associated with each guild
        self._league: Dict[discord.Guild, int] = {}
        super().__init__()
        log.info("RSC Bot has been started.")

    # Setup

    async def cog_load(self):
        """Perform initial bot setup on Cog reload"""
        log.debug("In cog_load()")
        await self.setup()

    @commands.Cog.listener()
    async def on_ready(self):
        """
        Perform initial bot setup on ready. This event ensures we are connected to guilds first.

        Does NOT trigger on Cog reload.
        """
        log.debug("In on_ready()")
        await self.setup()

    async def setup(self):
        """Prepare the bot API and caches. Requires API configuration"""
        log.debug("In RSC setup()")
        for guild in self.bot.guilds:
            log.debug(f"[{guild}] Preparing API configuration")
            await self.prepare_api(guild)
            log.debug(f"[{guild}] Preparing league data")
            await self.prepare_league(guild)
            if self._api_conf.get(guild):
                log.debug(f"[{guild}] Preparing cache")
                await self.franchises(guild)
                await self.tiers(guild)
                await self._populate_combines_cache(guild)

    async def prepare_league(self, guild: discord.Guild):
        league = await self._get_league(guild)
        if league:
            self._league[guild] = league
        else:
            log.warning(f"[{guild}] RSC API league has not been configured!")

    async def prepare_api(self, guild: discord.Guild):
        url = await self._get_api_url(guild)
        key = await self._get_api_key(guild)
        if url and key:
            self._api_conf[guild] = Configuration(
                host=url,
                api_key=key,
            )
        else:
            log.warning(f"[{guild}]RSC API key or url has not been configured!")

    # Configuration

    rsc_settings = app_commands.Group(
        name="rsc", description="RSC API Configuration", guild_only=True
    )

    @rsc_settings.command(name="key", description="Configure the RSC API key.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def _rsc_set_key(self, interaction: discord.Interaction, key: str):
        await self._set_api_key(interaction.guild, key)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="RSC API Key",
                description="RSC API key has been successfully configured.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @rsc_settings.command(name="url", description="Configure the RSC API web address.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def _rsc_set_url(self, interaction: discord.Interaction, url: str):
        await self._set_api_url(interaction.guild, url)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="RSC API Url",
                description="RSC API url has been successfully configured.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @rsc_settings.command(
        name="settings", description="Display the current RSC API settings."
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def _rsc_settings(self, interaction: discord.Interaction):
        key = (
            "Configured"
            if await self._get_api_key(interaction.guild)
            else "Not Configured"
        )
        url = await self._get_api_url(interaction.guild) or "Not Configured"
        league_int = await self._get_league(interaction.guild)

        # Find league name if it is configured/exists
        league = None
        if self._league[interaction.guild]:
            league = await self.league_by_id(
                interaction.guild, self._league[interaction.guild]
            )

        league_str = "Not Configured"
        if league:
            league_str = league.name

        settings_embed = discord.Embed(
            title="RSC API Settings",
            description="Current RSCI API configuration.",
            color=discord.Color.blue(),
        )
        settings_embed.add_field(name="API Key", value=key, inline=False)
        settings_embed.add_field(name="API URL", value=url, inline=False)
        settings_embed.add_field(name="League", value=league_str, inline=False)
        await interaction.response.send_message(embed=settings_embed, ephemeral=True)

    @rsc_settings.command(
        name="league", description="Set the league this guild correlates to in the API"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def _rsc_league(self, interaction: discord.Interaction):
        leagues = await self.leagues(interaction.guild)
        log.debug(leagues)
        league_view = LeagueSelectView(interaction, leagues)
        await league_view.prompt()
        await league_view.wait()

        if league_view.result:
            await self._set_league(interaction.guild, league_view.result)

    async def _set_api_key(self, guild: discord.Guild, key: str):
        await self.config.guild(guild).ApiKey.set(key)
        if self._get_api_url(guild):
            await self.prepare_api(guild)

    async def _get_api_key(self, guild: discord.Guild) -> Optional[str]:
        return await self.config.guild(guild).ApiKey()

    async def _set_api_url(self, guild: discord.Guild, url: str):
        await self.config.guild(guild).ApiUrl.set(url)
        if self._get_api_key(guild):
            await self.prepare_api(guild)

    async def _get_api_url(self, guild: discord.Guild) -> Optional[str]:
        return await self.config.guild(guild).ApiUrl()

    async def _set_league(self, guild: discord.Guild, league: int):
        await self.config.guild(guild).League.set(league)
        self._league[guild] = league

    async def _get_league(self, guild: discord.Guild) -> Optional[int]:
        return await self.config.guild(guild).League()
