import logging

import discord
from redbot.core import app_commands

from rsc.admin import AdminMixIn
from rsc.embeds import ApiExceptionErrorEmbed, BlueEmbed, ErrorEmbed, YellowEmbed
from rsc.enums import Status
from rsc.exceptions import LeagueNotConfigured, RscException
from rsc.logs import GuildLogAdapter

logger = logging.getLogger("red.rsc.admin.stats")
log = GuildLogAdapter(logger)


class AdminStatsMixIn(AdminMixIn):
    def __init__(self):
        log.debug("Initializing AdminMixIn:Stats")

        super().__init__()

    _stats = app_commands.Group(
        name="stats",
        description="RSC League Stats",
        parent=AdminMixIn._admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @_stats.command(name="intents", description="Intent to Play statistics")  # type: ignore[type-var]
    async def _intent_stats_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return
        if not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)

        try:
            next_season = await self.next_season(guild)
        except LeagueNotConfigured:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Not Configured",
                    description="League ID has not been configured for this guild.",
                )
            )
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc))

        if not next_season:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Intent To Play Statistics",
                    description="The next season of RSC has not started yet.",
                )
            )

        if not next_season.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="API returned a Season without an ID. Please open a modmail ticket.")
            )

        log.debug(f"Next Season ID: {next_season.id}")
        intents = await self.player_intents(guild, season_id=next_season.id)

        log.debug(f"Intent Count: {len(intents)}")
        if not intents:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Intent Statistics",
                    description="There are no intents declared for next season.",
                )
            )

        intent_dict = {
            "Returning": 0,
            "Not Returning": 0,
            "Missing": 0,
        }
        for i in intents:
            if i.returning:
                intent_dict["Returning"] += 1
            elif not i.returning and not i.missing:
                intent_dict["Not Returning"] += 1
            elif i.missing:
                intent_dict["Missing"] += 1
            else:
                log.warning(f"Unknown value in intent data. Player: {i.player.player.discord_id}")

        embed = BlueEmbed(
            title="Intent to Play Statistics",
            description="Next season intent to play statistics",
        )
        embed.add_field(name="Status", value="\n".join(intent_dict.keys()), inline=True)
        embed.add_field(
            name="Count",
            value="\n".join([str(v) for v in intent_dict.values()]),
            inline=True,
        )

        await interaction.followup.send(embed=embed)

    @_stats.command(name="intentbyfranchise", description="Intent to Play statistics by Franchise")  # type: ignore[type-var]
    async def _intent_stats_franchise_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return
        if not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)

        try:
            next_season = await self.next_season(guild)
        except LeagueNotConfigured:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Not Configured",
                    description="League ID has not been configured for this guild.",
                )
            )
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc))

        if not next_season:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Intent To Play Statistics",
                    description="The next season of RSC has not started yet.",
                )
            )

        if not next_season.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="API returned a Season without an ID. Please open a modmail ticket.")
            )

        log.debug(f"Next Season ID: {next_season.id}")
        intents = await self.player_intents(guild, season_id=next_season.id)

        log.debug(f"Intent Count: {len(intents)}")
        if not intents:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Intent Statistics",
                    description="There are no intents declared for next season.",
                )
            )

        franchise_intents: dict[str, dict[str, int]] = {}

        log.debug(f"Intents[0]: {intents[0] if intents else 'No intents'}")

        for i in intents:
            if not i.player:
                log.warning(f"Intent without player: {i}")
                continue

            if not i.player.franchise:
                continue

            franchise_intents.setdefault(i.player.franchise, {"Completed": 0, "Missing": 0, "Total": 0})

            if i.missing:
                franchise_intents[i.player.franchise]["Missing"] += 1
            else:
                franchise_intents[i.player.franchise]["Completed"] += 1

            franchise_intents[i.player.franchise]["Total"] += 1

        sorted_intents = dict(sorted(franchise_intents.items(), key=lambda x: x[1]["Missing"], reverse=True))

        embed = BlueEmbed(
            title="Intent to Play Franchise Statistics",
            description=f"Intent to Play statistics by franchise for S{next_season.number}",
        )

        embed.add_field(name="Franchise", value="\n".join(sorted_intents.keys()), inline=True)
        embed.add_field(name="Completed", value="\n".join([str(f["Completed"]) for f in sorted_intents.values()]), inline=True)
        embed.add_field(name="Missing", value="\n".join([str(f["Missing"]) for f in sorted_intents.values()]), inline=True)

        await interaction.followup.send(embed=embed)

    @_stats.command(name="current", description="Current season statistics")  # type: ignore[type-var]
    async def _current_season_stats_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return
        if not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)

        try:
            season = await self.current_season(guild)
        except LeagueNotConfigured:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Not Configured",
                    description="League ID has not been configured for this guild.",
                )
            )
        except RscException as exc:
            return await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc),
            )

        if not season:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Current Season Stats",
                    description="A season has not been started in this guild.",
                )
            )

        if not season:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="API returned a Season without an ID. Please open a modmail ticket.")
            )

        lplayers = await self.players(guild, season=season.id, limit=10000)

        total_des = len(lplayers)
        log.debug(f"DE Player Length: {total_des}")
        if not lplayers:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Current Season Stats",
                    description=f"No league players found for season {season.number}",
                )
            )

        status_dict = {}
        for s in Status:
            status_dict[s.full_name] = sum(1 for p in lplayers if p.status == s)

        from pprint import pformat

        log.debug(f"Final Results:\n\n{pformat(status_dict)}")

        embed = BlueEmbed(
            title="Current Season Stats",
            description="RSC stats for next season sign-ups",
        )
        embed.add_field(name="Status", value="\n".join(status_dict.keys()), inline=True)
        embed.add_field(
            name="Count",
            value="\n".join([str(v) for v in status_dict.values()]),
            inline=True,
        )

        await interaction.followup.send(embed=embed)

    @_stats.command(name="signups", description="RSC sign-up statistics")  # type: ignore[type-var]
    async def _signups_stats_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return
        if not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)

        try:
            next_season = await self.next_season(guild)
        except LeagueNotConfigured:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Not Configured",
                    description="League ID has not been configured for this guild.",
                )
            )
        except RscException as exc:
            return await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc),
            )

        if not next_season:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Sign-up Stats",
                    description="The next season of RSC has not started yet.",
                )
            )

        if not next_season.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="API returned a Season without an ID. Please open a modmail ticket.")
            )

        lplayers = await self.players(guild, season=next_season.id)

        total_des = len(lplayers)
        log.debug(f"DE Player Length: {total_des}")
        if not lplayers:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="RSC Sign-up Stats",
                    description=f"No league players found for season {next_season.number}",
                )
            )

        status_dict = {}
        for s in Status:
            status_dict[s.full_name] = sum(1 for p in lplayers if p.status == s)

        from pprint import pformat

        log.debug(f"Final Results:\n\n{pformat(status_dict)}")

        embed = BlueEmbed(title="Sign-up Stats", description="RSC stats for next season sign-ups")
        embed.add_field(name="Status", value="\n".join(status_dict.keys()), inline=True)
        embed.add_field(
            name="Count",
            value="\n".join([str(v) for v in status_dict.values()]),
            inline=True,
        )

        await interaction.followup.send(embed=embed)
