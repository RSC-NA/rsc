import logging
from datetime import datetime
from typing import cast

import discord
from redbot.core import app_commands
from rscapi import ApiClient, NumbersApi
from rscapi.exceptions import ApiException
from rscapi.models.player_mmr import PlayerMMR

from rsc.abc import RSCMixIn
from rsc.embeds import ApiExceptionErrorEmbed, BlueEmbed, GreenEmbed, YellowEmbed
from rsc.exceptions import RscException
from rsc.types import NumbersSettings

log = logging.getLogger("red.rsc.transactions")


defaults_guild = NumbersSettings(NumbersRole=None)


class NumberMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing NumberMixIn")
        # Prepare configuration group
        self.config.init_custom("Numbers", 1)
        self.config.register_custom("Numbers", **defaults_guild)
        super().__init__()

    # Access Control
    async def has_numbers_perms(self, interaction: discord.Interaction):
        if not (interaction.guild and isinstance(interaction.user, discord.Member)):
            return False

        if interaction.user.guild_permissions.manage_guild:
            log.debug("Member has manage guild permissions")
            return True

        role = await self._get_numbers_role(interaction.guild)
        if role in interaction.user.roles:
            log.debug("Member in numbers committee")
            return True
        log.debug("Member NOT in numbers committee")
        return False

    # Top Level Group

    _numbers = app_commands.Group(
        name="numbers",
        description="Configuration and commands for Numbers Committee",
        guild_only=True,
    )

    # App Commands

    @_numbers.command(  # type: ignore[type-var]
        name="settings", description="Configure numbers module settings"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _numbers_settings_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        numbers_role = await self._get_numbers_role(guild)

        embed = BlueEmbed(
            title="Numbers Settings",
            description="Displaying current settings for Numbers module.",
        )

        embed.add_field(
            name="Numbers Committee Role",
            value=numbers_role.mention if numbers_role else "None",
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_numbers.command(  # type: ignore[type-var]
        name="role", description="Configure the Number Committee role"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _set_numbers_role_cmd(self, interaction: discord.Interaction, role: discord.Role):
        guild = interaction.guild
        if not guild:
            return

        await self._set_numbers_role(guild, role)

        embed = GreenEmbed(
            title="Numbers Role Configured",
            description=f"Numbers Committee role has been configured to {role.mention}",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_numbers.command(  # type: ignore[type-var]
        name="peaks", description="Display player MMR peaks for a psyonix season"
    )
    @app_commands.describe(player="RSC Discord Member", psyonix_season="Pysonix season to display")
    async def _numbers_peaks_cmd(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        psyonix_season: int | None = None,
    ):
        if not interaction.guild:
            return None

        if not await self.has_numbers_perms(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        try:
            pulls = await self.mmr_pulls(
                interaction.guild,
                player=player,
                psyonix_season=psyonix_season or None,
            )
        except RscException as exc:
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        log.debug(f"Total MMR pulls: {len(pulls)}")

        peaks = await self.calculate_mmr_peaks(pulls)

        embed = YellowEmbed(
            title="Player MMR Peaks",
        )

        if psyonix_season:
            embed.description = f"MMR peaks for {player.mention} in season **{psyonix_season}**"
        else:
            embed.description = f"MMR peaks for {player.mention} all seasons"

        embed.add_field(
            name="3v3",
            value=str(peaks[0]),
            inline=True,
        )
        embed.add_field(
            name="2v2",
            value=str(peaks[1]),
            inline=True,
        )
        embed.add_field(
            name="1v1",
            value=str(peaks[2]),
            inline=True,
        )
        await interaction.followup.send(embed=embed)

    @_numbers.command(  # type: ignore[type-var]
        name="gamesplayed",
        description="Display tracker games played for a pysonix season",
    )
    @app_commands.describe(player="RSC Discord Member", psyonix_season="Pysonix season to display")
    async def _numbers_gamesplayed_cmd(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        psyonix_season: int,
    ):
        if not interaction.guild:
            return None

        if not await self.has_numbers_perms(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        try:
            pulls = await self.mmr_pulls(interaction.guild, player=player, psyonix_season=psyonix_season)
        except RscException as exc:
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        log.debug(f"Total MMR pulls: {len(pulls)}")

        pulls_fmt = await self.filter_no_games_played_mmr_pulls(pulls)
        log.debug(f"Total Filtered MMR pulls: {len(pulls)}")
        pulls_fmt.sort(key=lambda x: cast(int, x.threes_games_played), reverse=True)

        embed = YellowEmbed(
            title="Player Games Played",
            description=f"Games played for {player.mention} in season **{psyonix_season}**",
        )

        embed.add_field(
            name="3v3",
            value="\n".join([str(x.threes_games_played) for x in pulls_fmt]),
            inline=True,
        )
        embed.add_field(
            name="2v2",
            value="\n".join([str(x.twos_games_played) for x in pulls_fmt]),
            inline=True,
        )
        embed.add_field(
            name="1v1",
            value="\n".join([str(x.ones_games_played) for x in pulls_fmt]),
            inline=True,
        )
        await interaction.followup.send(embed=embed)

    # Functions

    async def filter_no_games_played_mmr_pulls(self, pulls: list[PlayerMMR]) -> list[PlayerMMR]:
        log.debug(f"Filter pulls len: {len(pulls)}")
        pulls_filtered: list[PlayerMMR] = []
        for p in pulls:
            log.debug(p)
            # Remove pulls with no games played in any playlist
            if not (p.threes_games_played or p.twos_games_played or p.ones_games_played):
                log.debug("Removing above pull.")
                continue

            # Make sure it's not a duplicate
            dupe = False
            for pf in pulls_filtered:
                if (
                    pf.threes_games_played == p.threes_games_played
                    and pf.twos_games_played == p.twos_games_played
                    and pf.ones_games_played == p.ones_games_played
                ):
                    log.debug("Duplicate")
                    dupe = True
                    break

            if not dupe:
                pulls_filtered.append(p)

        return pulls_filtered

    async def calculate_mmr_peaks(self, pulls: list[PlayerMMR]) -> tuple[int, int, int]:
        threes = 0
        twos = 0
        ones = 0
        for p in pulls:
            if p.threes_season_peak and p.threes_season_peak > threes:
                threes = p.threes_season_peak
            if p.twos_season_peak and p.twos_season_peak > twos:
                twos = p.twos_season_peak
            if p.ones_season_peak and p.ones_season_peak > ones:
                ones = p.ones_season_peak
        return (threes, twos, ones)

    # API

    async def mmr_pulls(
        self,
        guild: discord.Guild,
        pulled: datetime | None = None,
        pulled_before: datetime | None = None,
        pulled_after: datetime | None = None,
        player: discord.Member | None = None,
        rscid: str | None = None,
        rscid_begin: str | None = None,
        rscid_end: str | None = None,
        psyonix_season: int | None = None,
    ) -> list[PlayerMMR]:
        """Get list of trackers ready to be updated"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = NumbersApi(client)
            try:
                data = await api.numbers_mmr_list(
                    pulled=pulled.isoformat() if pulled else None,
                    pulled_before=pulled_before.isoformat() if pulled_before else None,
                    pulled_after=pulled_after.isoformat() if pulled_after else None,
                    discord_id=player.id if player else None,
                    rscid=rscid,
                    rscid_begin=rscid_begin,
                    rscid_end=rscid_end,
                    psyonix_season=psyonix_season,
                    limit=1000,
                )
                return data.results
            except ApiException as exc:
                raise RscException(response=exc)

    # Config

    async def _get_numbers_role(self, guild: discord.Guild) -> discord.Role | None:
        role_id = await self.config.custom("Numbers", str(guild.id)).NumbersRole()
        r = guild.get_role(role_id)
        if not r:
            return None
        return r

    async def _set_numbers_role(self, guild: discord.Guild, role: discord.Role):
        await self.config.custom("Numbers", str(guild.id)).NumbersRole.set(role.id)
