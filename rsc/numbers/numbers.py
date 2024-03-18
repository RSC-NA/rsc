import logging
from datetime import datetime

import discord
from redbot.core import app_commands
from rscapi import ApiClient, NumbersApi
from rscapi.exceptions import ApiException
from rscapi.models.player_mmr import PlayerMMR

from rsc.abc import RSCMixIn
from rsc.embeds import YellowEmbed
from rsc.exceptions import RscException
from rsc.types import NumbersSettings

log = logging.getLogger("red.rsc.transactions")


defaults_guild = NumbersSettings(NumbersRoles=[])

NUMBERS_ROLES = "Numbers Committee"


class NumberMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing NumberMixIn")
        # Prepare configuration group
        self.config.init_custom("Numbers", 1)
        self.config.register_custom("Numbers", **defaults_guild)
        super().__init__()

    # Access Control
    async def has_numbers_perms(self, interaction: discord.Interaction):
        # THIS DOESNT WORK BECAUSE ASYNC
        if not (interaction.guild and isinstance(interaction.user, discord.Member)):
            return False

        if interaction.user.guild_permissions.manage_guild:
            log.debug("Member has manage guild permissions")
            return True

        roles = await self._get_numbers_roles(interaction.guild)
        for r in interaction.user.roles:
            if r in roles:
                log.debug("Member in numbers committee")
                return True
        return False

    # Top Level Group

    _numbers = app_commands.Group(
        name="numbers",
        description="Configuration and commands for Numbers Committee",
        guild_only=True,
    )

    # App Commands

    @_numbers.command(
        name="fetch", description="Display list of MMR pulls for a player"
    )
    @app_commands.describe(player="RSC Discord Member")
    @app_commands.checks.has_any_role(NUMBERS_ROLES)
    async def _numbers_fetch(
        self, interaction: discord.Interaction, player: discord.Member
    ):
        if not interaction.guild:
            return None

        pulls = await self.mmr_pulls(interaction.guild, player=player)
        pulls.sort(key=lambda x: x.date_pulled, reverse=True)
        embed = YellowEmbed(
            title="Player MMR Pulls",
            description=f"List of MMR pulls for {player.mention}. Peaks only.",
        )
        embed.add_field(
            name="Date",
            value="\n".join([str(x.date_pulled.date()) for x in pulls]),
            inline=True,
        )
        embed.add_field(
            name="3v3",
            value="\n".join(
                [f"{x.threes_season_peak} ({x.threes_games_played})" for x in pulls]
            ),
            inline=True,
        )
        embed.add_field(
            name="2v2",
            value="\n".join(
                [f"{x.twos_season_peak} ({x.twos_games_played})" for x in pulls]
            ),
            inline=True,
        )
        embed.add_field(
            name="1v1",
            value="\n".join(
                [f"{x.ones_season_peak} ({x.ones_games_played})" for x in pulls]
            ),
            inline=True,
        )
        await interaction.response.send_message(embed=embed)

    # API

    async def mmr_pulls(
        self,
        guild: discord.Guild,
        pulled: str | None = None,
        pulled_before: datetime | None = None,
        pulled_after: datetime | None = None,
        player: discord.Member | None = None,
        rscid: str | None = None,
    ) -> list[PlayerMMR]:
        """Get list of trackers ready to be updated"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = NumbersApi(client)
            try:
                return await api.numbers_mmr_list(
                    pulled=pulled,
                    pulled_before=pulled_before.isoformat() if pulled_before else None,
                    pulled_after=pulled_after.isoformat() if pulled_after else None,
                    discord_id=player.id if player else None,
                    rscid=rscid,
                )
            except ApiException as exc:
                raise RscException(repsonse=exc)

    # Config

    async def _get_numbers_roles(self, guild: discord.Guild) -> list[discord.Role]:
        role_ids = await self.config.custom("Numbers", str(guild.id)).NumbersRoles()
        roles = []
        for id in role_ids:
            r = guild.get_role(id)
            if not r:
                log.warning(f"Numbers roles contains invalid role id: {id}")
                continue
            roles.append(r)
        return roles

    async def _set_numbers_roles(self, guild: discord.Guild, roles: list[discord.Role]):
        await self.config.custom("Transactions", str(guild.id)).NumbersRoles.set(
            [r.id for r in roles]
        )
