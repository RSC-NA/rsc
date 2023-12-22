import logging

import discord
from redbot.core import app_commands

from rsc.abc import RSCMixIn
from rsc.const import SEASON_TITLE_REGEX
from rsc.embeds import (
    BlueEmbed,
    OrangeEmbed,
    RapidQuotaEmbed,
    RapidTimeOutEmbed,
    WarningEmbed,
)
from rsc.enums import AnsiColor, RankedPlaylist, RLStatType
from rsc.exceptions import RapidApiTimeOut, RapidQuotaExceeded

log = logging.getLogger("red.rsc.ranks")


class RankMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing RankMixIn")
        super().__init__()

    _rl = app_commands.Group(
        name="rl",
        description="Display Rocket League related information",
        guild_only=True,
    )

    # RL Group Commands

    @_rl.command(name="ranks", description="Display rocket league rank (Epic Only)")
    @app_commands.describe(player="RSC Discord Member")
    @app_commands.checks.cooldown(1, 60.0, key=lambda i: (i.guild_id, i.user.id))
    async def _rl_ranks(self, interaction: discord.Interaction, player: discord.Member):
        guild = interaction.guild
        if not guild:
            return

        api = await self.rapid_connector(guild)
        if not api:
            await interaction.response.send_message(
                embed=WarningEmbed(description="RapidAPI is not currently configured."),
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        trackers = await self.trackers(guild, player=player)

        embed = BlueEmbed(
            title=f"{player.display_name} Ranks",
            description="Rocket League rank by playlist. Only displays known **Epic** accounts.",
        )

        try:
            for t in trackers:
                log.debug(f"Tracker: {t}")
                if t.platform != "EPIC":
                    continue
                data = await api.ranks(t.name)
                if not data:
                    continue

                embed.add_field(name="Epic", value=t.name, inline=False)
                for r in data.ranks:
                    match r.playlist:
                        case RankedPlaylist.DUEL:
                            embed.add_field(name="Duel", value=r.mmr, inline=True)
                        case RankedPlaylist.DOUBLES:
                            embed.add_field(name="Doubles", value=r.mmr, inline=True)
                        case RankedPlaylist.STANDARD:
                            embed.add_field(name="Standard", value=r.mmr, inline=True)
        except RapidQuotaExceeded:
            await interaction.followup.send(embed=RapidQuotaEmbed(), ephemeral=True)
            return
        except RapidApiTimeOut:
            await interaction.followup.send(embed=RapidTimeOutEmbed(), ephemeral=True)
            return

        await interaction.followup.send(embed=embed)

    @_rl.command(
        name="stats", description="Display rocket league stats for Epic accounts"
    )
    @app_commands.describe(stat="Stat type to query", player="RSC Discord Member")
    @app_commands.checks.cooldown(1, 60.0, key=lambda i: (i.guild_id, i.user.id))
    async def _rl_stats(
        self, interaction: discord.Interaction, stat: RLStatType, player: discord.Member
    ):
        guild = interaction.guild
        if not guild:
            return

        api = await self.rapid_connector(guild)
        if not api:
            await interaction.response.send_message(
                embed=WarningEmbed(description="RapidAPI is not currently configured."),
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        members = await self.members(guild, discord_id=player.id, limit=1)
        if not members:
            await interaction.followup.send(
                embed=OrangeEmbed(
                    title="Player Ranks",
                    description=f"{player.mention} is not an RSC member.",
                ),
                ephemeral=True,
            )
            return

        trackers = await self.trackers(guild, name=members[0].rsc_name)

        embed = BlueEmbed(
            title=f"{members[0].rsc_name.title()} RL {stat}",
            description=f"Displaying {stat.name.lower()} statistics. Only displays known **Epic** accounts.",
        )

        stats = {}
        try:
            for t in trackers:
                if t.platform != "EPIC":
                    continue
                data = await api.stat(stat, t.name)
                if data:
                    stats[t.name] = data.value
        except RapidQuotaExceeded:
            await interaction.followup.send(embed=RapidQuotaEmbed(), ephemeral=True)
            return
        except RapidApiTimeOut:
            await interaction.followup.send(embed=RapidTimeOutEmbed(), ephemeral=True)
            return

        embed.add_field(name="Account", value="\n".join(stats.keys()), inline=True)
        embed.add_field(
            name="Stat Count",
            value="\n".join([str(v) for v in stats.values()]),
            inline=True,
        )

        await interaction.followup.send(embed=embed)

    @_rl.command(
        name="status", description="Display rocket league status for Epic accounts"
    )
    @app_commands.describe(player="RSC Discord Member")
    @app_commands.checks.cooldown(1, 60.0, key=lambda i: (i.guild_id, i.user.id))
    async def _rl_status(
        self, interaction: discord.Interaction, player: discord.Member
    ):
        api = await self.rapid_connector(interaction.guild)
        if not api:
            await interaction.response.send_message(
                embed=WarningEmbed(description="RapidAPI is not currently configured."),
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        members = await self.members(interaction.guild, discord_id=player.id, limit=1)
        if not members:
            await interaction.followup.send(
                embed=OrangeEmbed(
                    title="Player RL Status",
                    description=f"{player.mention} is not an RSC member.",
                ),
                ephemeral=True,
            )
            return

        trackers = await self.trackers(interaction.guild, name=members[0].rsc_name)

        embed = BlueEmbed(
            title=f"{members[0].rsc_name} RL Status".title(),
            description="Displaying Rocket League status for player. Only displays known **Epic** accounts.",
        )

        profiles = []
        try:
            for t in trackers:
                if t.platform != "EPIC":
                    continue
                data = await api.profile(t.name)
                if data:
                    profiles.append(data)
        except RapidQuotaExceeded:
            await interaction.followup.send(embed=RapidQuotaEmbed(), ephemeral=True)
            return
        except RapidApiTimeOut:
            await interaction.followup.send(embed=RapidTimeOutEmbed(), ephemeral=True)
            return

        embed.add_field(
            name="Account", value="\n".join([p.name for p in profiles]), inline=True
        )
        embed.add_field(
            name="Status", value="\n".join([p.presence for p in profiles]), inline=True
        )

        await interaction.followup.send(embed=embed)

    @_rl.command(
        name="titles", description="Display rocket league titles for Epic account"
    )
    @app_commands.describe(player="Rocket League Epic Account name or Epic ID")
    @app_commands.checks.cooldown(1, 60.0, key=lambda i: (i.guild_id, i.user.id))
    async def _rl_titles(self, interaction: discord.Interaction, player: str):
        api = await self.rapid_connector(interaction.guild)
        if not api:
            await interaction.response.send_message(
                embed=WarningEmbed(description="RapidAPI is not currently configured."),
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        try:
            titles = await api.titles(player)
        except RapidQuotaExceeded:
            await interaction.followup.send(embed=RapidQuotaEmbed(), ephemeral=True)
            return
        except RapidApiTimeOut:
            await interaction.followup.send(embed=RapidTimeOutEmbed(), ephemeral=True)
            return

        if not titles:
            await interaction.followup.send(
                embed=OrangeEmbed(
                    title=f"{player} RL Titles",
                    description=f"No data found for **{player}**",
                ),
                ephemeral=True,
            )
            return

        desc = "Displaying Rocket League titles for Epic account.\n\n```ansi\n"

        for t in titles:
            # Only display season titles (List would be too large otherwise)
            if SEASON_TITLE_REGEX.match(t.name):
                # Actual conversion isn't working in discord
                # c = AnsiColor.RED.from_rgb_hex(t.color, bold=True)
                # log.debug(f"Ansi Repr: {repr(c)}")
                # desc += f" - {c}{t.name}\u001b[0m\n"
                if t.color == "#ff2800":
                    desc += f" - {AnsiColor.RED.bold_colored_text(t.name)}\n"
                else:
                    desc += f" - **{t.name}**\n"
        desc += "```"

        embed = BlueEmbed(
            title=f"{player.title()} RL Titles",
            description=desc,
        )

        await interaction.followup.send(embed=embed)
