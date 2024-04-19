import logging
from typing import cast

import discord
from redbot.core import app_commands
from rscapi import ApiClient, TeamsApi
from rscapi.exceptions import ApiException
from rscapi.models.high_level_match import HighLevelMatch
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.match import Match
from rscapi.models.player import Player
from rscapi.models.team import Team
from rscapi.models.team_list import TeamList
from rscapi.models.team_season_stats import TeamSeasonStats

from rsc.abc import RSCMixIn
from rsc.embeds import BlueEmbed, ErrorEmbed
from rsc.enums import Status, SubStatus
from rsc.exceptions import RscException
from rsc.franchises import FranchiseMixIn
from rsc.tiers import TierMixIn
from rsc.utils import utils

log = logging.getLogger("red.rsc.teams")


class TeamMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing TeamMixIn")
        self._team_cache: dict[int, list[str]] = {}
        super().__init__()

    # Autocomplete

    async def teams_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return []

        # Return nothing if cache does not exist.
        if not self._team_cache.get(interaction.guild_id):
            return []

        if not current:
            return [
                app_commands.Choice(name=t, value=t)
                for t in self._team_cache[interaction.guild_id][:25]
            ]

        choices = []
        for t in self._team_cache[interaction.guild_id]:
            if current.lower() in t.lower():
                choices.append(app_commands.Choice(name=t, value=t))
            if len(choices) == 25:
                return choices
        return choices

    # Group Commands

    _teams = app_commands.Group(
        name="teams", description="Get a list of teams in RSC", guild_only=True
    )

    # Commands

    @_teams.command(  # type: ignore
        name="franchise", description="Get a list of teams for a franchise"
    )
    @app_commands.autocomplete(franchise=FranchiseMixIn.franchise_autocomplete)
    @app_commands.describe(franchise="Teams in a franchise")
    @app_commands.guild_only
    async def _teams_franchise_cmd(
        self,
        interaction: discord.Interaction,
        franchise: str,
    ):
        """Get a list of teams for a franchise"""
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer()
        log.debug(f"Fetching teams for {franchise}")
        teams = await self.teams(guild, franchise=franchise)

        if not teams:
            await interaction.followup.send(content="No results found.", ephemeral=True)
            return

        # Validate API data
        for t in teams:
            if not t.name:
                return await interaction.followup.send(
                    embed=ErrorEmbed(
                        description=f"`Team {t.id}` has no name. Please open a modmail ticket."
                    )
                )
            if not t.tier:
                return await interaction.followup.send(
                    embed=ErrorEmbed(
                        description=f"`Team {t.id}` has no tier. Please open a modmail ticket."
                    )
                )
            if not t.tier.name:
                return await interaction.followup.send(
                    embed=ErrorEmbed(
                        description=f"`Team {t.id}` has no tier name. Please open a modmail ticket."
                    )
                )
            if not t.tier.position:
                return await interaction.followup.send(
                    embed=ErrorEmbed(
                        description=f"`Team {t.id}` has no tier position. Please open a modmail ticket."
                    )
                )

        teams.sort(key=lambda t: cast(str, t.tier.position), reverse=True)  # type: ignore

        embed = BlueEmbed()
        embed.title = f"{franchise} Teams"
        embed.add_field(
            name="Team",
            value="\n".join([t.name or "Error" for t in teams]),
            inline=True,
        )
        embed.add_field(
            name="Tier",
            value="\n".join([str(t.tier.name) if t.tier else "Error" for t in teams]),
            inline=True,
        )

        flogo = None
        if teams[0].franchise.id:
            flogo = await self.franchise_logo(guild, teams[0].franchise.id)

        if flogo:
            embed.set_thumbnail(url=flogo)
        elif guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        await interaction.followup.send(embed=embed)

    @_teams.command(  # type: ignore
        name="tier", description="Get a list of teams in a tier"
    )
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)  # type: ignore
    @app_commands.describe(tier="Teams in a league tier")
    @app_commands.guild_only
    async def _teams_tier_cmd(
        self,
        interaction: discord.Interaction,
        tier: str,
    ):
        """Get a list of teams for a franchise"""
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer()
        log.debug(f"Fetching teams for {tier}")
        teams = await self.teams(guild, tier=tier)

        if not teams:
            await interaction.followup.send(content="No results found.", ephemeral=True)
            return

        # Validate API data
        for t in teams:
            if not t.name:
                return await interaction.followup.send(
                    embed=ErrorEmbed(
                        description=f"`Team {t.id}` has no name. Please open a modmail ticket."
                    )
                )
            if not t.tier:
                return await interaction.followup.send(
                    embed=ErrorEmbed(
                        description=f"`Team {t.id}` has no tier. Please open a modmail ticket."
                    )
                )
            if not t.tier.name:
                return await interaction.followup.send(
                    embed=ErrorEmbed(
                        description=f"`Team {t.id}` has no tier name. Please open a modmail ticket."
                    )
                )

        # Sort by Team Name
        teams.sort(key=lambda x: cast(str, x.name))

        embed = BlueEmbed()
        embed.title = f"{tier} Teams"
        embed.add_field(
            name="Team",
            value="\n".join([t.name or "Error" for t in teams]),
            inline=True,
        )
        embed.add_field(
            name="Franchise",
            value="\n".join([t.franchise.name for t in teams]),
            inline=True,
        )

        # Get Tier Color
        tier_color = await utils.tier_color_by_name(guild, name=tier)
        embed.colour = tier_color

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="roster", description="Get roster for a team")  # type: ignore
    @app_commands.describe(team="Team name to search")
    @app_commands.autocomplete(team=teams_autocomplete)  # type: ignore
    @app_commands.guild_only
    async def _roster(
        self,
        interaction: discord.Interaction,
        team: str,
    ):
        """Get a roster for a team"""
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer()
        players = await self.players(guild, team_name=team)

        # Verify team exists and get data
        if not players:
            await interaction.followup.send(
                content=f"No results found for **{team}**.", ephemeral=True
            )
            return

        # Check if we got results for other teams
        for p in players:
            if not (p.team and p.team.name):
                raise ValueError("Malformed roster data received from API")
            if p.team.name != team:
                teams_found: set[str] = {
                    str(p.team.name) if p.team else "Error" for p in players
                }
                names = ", ".join(list(teams_found))
                await interaction.followup.send(
                    content=f"Found multiple results for team name.\n\n **{names}**",
                    ephemeral=True,
                )
                return

        if not (players[0].team and players[0].team.franchise):
            raise ValueError("Malformed roster data received from API")

        gm_id = players[0].team.franchise.gm.discord_id
        gm_name = players[0].team.franchise.gm.rsc_name
        franchise = players[0].team.franchise.name

        roster = []
        subbed = []
        ir = []
        insertTop = False
        for p in players:
            m = None
            if p.player.discord_id:
                m = guild.get_member(p.player.discord_id)
            name = m.display_name if m else p.player.name

            # Check GM/Capatain
            if p.captain and p.player.discord_id == gm_id:
                name = f"{name} (GM|C)"
                insertTop = True
            elif p.player.discord_id == gm_id:
                name = f"{name} (GM)"
                insertTop = True
            elif p.captain:
                name = f"{name} (C)"
                insertTop = True
            else:
                insertTop = False

            # Sub status
            match p.sub_status:
                case SubStatus.OUT:
                    subbed.append(name)
                    continue
                case SubStatus.IN:
                    roster.append(f"{name} (Sub)")
                    continue

            match p.status:
                case Status.IR:
                    ir.append(f"{name} (IR)")
                case Status.AGMIR:
                    ir.append(f"{name} (AGM IR)")
                case Status.ROSTERED:
                    if insertTop:
                        roster.insert(0, name)
                    else:
                        roster.append(name)
                case _:
                    roster.append(name)

        # Validate API data
        if not (players[0].tier and players[0].tier.name):
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="Player has no tier or tier name. Please open a modmail ticket."
                )
            )

        roster_str = "\n".join(roster)
        tier_color = await utils.tier_color_by_name(guild, players[0].tier.name)

        header = f"{team} - {franchise} ({gm_name}) - {players[0].tier.name}"
        # desc = f"**{header}**\n```\n{roster_str}\n```"
        # desc = f"\n```\n{roster_str}\n```"
        desc = f"```\n{roster_str}\n```"

        embed = discord.Embed(
            # title=f"{team} - {franchise} ({gm_name}) - {players[0].tier.name}",
            description=desc,
            color=tier_color,
        )

        embed.set_author(name=header)

        if subbed:
            sub_str = "\n".join(subbed)
            embed.add_field(
                name="Subbed Out", value=f"```\n{sub_str}\n```", inline=True
            )

        if ir:
            ir_str = "\n".join(ir)
            embed.add_field(
                name="Inactive Reserve", value=f"```\n{ir_str}\n```", inline=True
            )

        # Get Logo
        flogo = None
        if players[0].team.franchise.id:
            flogo = await self.franchise_logo(guild, players[0].team.franchise.id)
        if flogo:
            embed.set_thumbnail(url=flogo)
        elif guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        await interaction.followup.send(embed=embed)

    # Captains Group

    _captains = app_commands.Group(
        name="captains", description="Get information on team captains", guild_only=True
    )

    @_captains.command(name="team", description="Team to query")  # type: ignore
    @app_commands.autocomplete(team=teams_autocomplete)  # type: ignore
    async def _captains_team(
        self,
        interaction: discord.Interaction,
        team: str,
    ):
        """Get a list of captains by search criteria"""
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer()
        captain = await self.team_captain(guild, team)
        if not captain:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"**{team}** does not exist or a captain has not been elected."
                ),
                ephemeral=True,
            )
            return

        if not (
            captain.team
            and captain.team.franchise
            and captain.team.franchise.name
            and captain.tier
            and captain.tier.name
            and captain.player.discord_id
        ):
            raise ValueError("Malformed player data received from API")

        tier_color = await utils.tier_color_by_name(guild, captain.tier.name)

        # fetch discord.Member from id
        m = guild.get_member(captain.player.discord_id)
        cpt_fmt = m.mention if m else captain.player.name

        # fetch franchise role
        frole = await utils.franchise_role_from_name(guild, captain.team.franchise.name)
        franchise_fmt = frole.mention if frole else captain.team.franchise.name

        desc = f"**Captain:** {cpt_fmt}\n" f"**Franchise:** {franchise_fmt}"

        embed = discord.Embed(
            title=f"{team} Team Captain", description=desc, color=tier_color
        )
        await interaction.followup.send(embed=embed)

    @_captains.command(  # type: ignore
        name="tier", description="Display captains of all teams in a tier"
    )
    @app_commands.describe(tier="Tier to query")
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)  # type: ignore
    async def _captains_tier(self, interaction: discord.Interaction, tier: str):
        """Get a list of captains by search criteria"""
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer()
        captains = await self.tier_captains(guild, tier)

        fteams = await self.teams(guild, tier=tier)
        fteams.sort(key=lambda x: cast(str, x.name))

        if not fteams:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"**{tier}** is not a valid tier or no exist in it."
                ),
                ephemeral=True,
            )
            return

        cpt_fmt: list[tuple[str, str, str]] = []
        for t in fteams:
            if not (t.name and t.franchise and t.franchise.name):
                return await interaction.followup.send(
                    embed=ErrorEmbed(
                        description=f"Team {t.id} has no name or franchise data. Please open a modmail ticket."
                    )
                )
            # Match captain to team
            captain = next(
                (c for c in captains if c.team and c.team.name == t.name), None
            )
            pname = "None"
            if captain:
                # Fetch discord.Member
                if not (captain.player and captain.player.discord_id):
                    return await interaction.followup.send(
                        embed=ErrorEmbed(
                            description=f"{captain.id} has no discord ID attached. Please open a modmail ticket."
                        )
                    )
                m = guild.get_member(captain.player.discord_id)
                pname = m.mention if m else captain.player.name

            cpt_fmt.append((pname, t.name, t.franchise.name))

        tier_color = await utils.tier_color_by_name(guild, tier)

        embed = discord.Embed(title=f"{tier} Captains", color=tier_color)
        embed.add_field(
            name="Captain", value="\n".join([x[0] for x in cpt_fmt]), inline=True
        )
        embed.add_field(
            name="Team", value="\n".join([c[1] for c in cpt_fmt]), inline=True
        )
        embed.add_field(
            name="Franchise",
            value="\n".join([c[2] for c in cpt_fmt]),
            inline=True,
        )
        await interaction.followup.send(embed=embed)

    @_captains.command(  # type: ignore
        name="franchise", description="Display captains of all teams in a franchise"
    )
    @app_commands.describe(franchise="Franchise name")
    @app_commands.autocomplete(franchise=FranchiseMixIn.franchise_autocomplete)  # type: ignore
    async def _captains_franchise(
        self,
        interaction: discord.Interaction,
        franchise: str,
    ):
        """Get a list of captains by search criteria"""
        guild = interaction.guild
        if not guild:
            return
        await interaction.response.defer()

        captains = await self.franchise_captains(guild, franchise)
        if not captains:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"**{franchise}** is not a valid franchise or no captains have been elected."
                ),
                ephemeral=True,
            )

        if not (
            captains[0].team
            and captains[0].team.franchise
            and captains[0].team.franchise.name
        ):
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"Captain **{captains[0].id}** is missing team or franchise data. Please open a modmail ticket."
                ),
                ephemeral=True,
            )

        # Get Franchise Team names
        fteams = await self.teams(guild, franchise=captains[0].team.franchise.name)

        cpt_fmt: list[tuple[str, str, str]] = []
        for t in fteams:
            if not (t.name and t.tier and t.tier.name):
                return await interaction.followup.send(
                    embed=ErrorEmbed(
                        description=f"Team {t.id} has no name or tier data. Please open a modmail ticket."
                    )
                )
            # Match captain to team
            captain = next(
                (c for c in captains if c.tier and c.tier.id == t.tier.id), None
            )
            pname = "None"
            if captain:
                if not (captain.player and captain.player.discord_id):
                    return await interaction.followup.send(
                        embed=ErrorEmbed(
                            description=f"{captain.id} has no discord ID attached. Please open a modmail ticket."
                        )
                    )
                # Fetch discord.Member
                m = guild.get_member(captain.player.discord_id)
                pname = m.mention if m else captain.player.name

            cpt_fmt.append((pname, t.name, t.tier.name))

        frole = await utils.franchise_role_from_name(
            guild, captains[0].team.franchise.name
        )

        gm = guild.get_member(captains[0].team.franchise.gm.discord_id)

        embed = BlueEmbed(title=f"{franchise} Captains")

        if gm and frole:
            embed.description = (
                f"General Manager: {gm.mention}\nFranchise: {frole.mention}"
            )

        embed.add_field(
            name="Captain", value="\n".join([x[0] for x in cpt_fmt]), inline=True
        )
        embed.add_field(
            name="Team", value="\n".join([x[1] for x in cpt_fmt]), inline=True
        )
        embed.add_field(
            name="Tier", value="\n".join([x[2] for x in cpt_fmt]), inline=True
        )
        await interaction.followup.send(embed=embed)

    # Functions

    async def team_id_by_name(self, guild: discord.Guild, name: str) -> int:
        """Return a teams ID in the API by name. (Zero indicates not found)"""
        teams = await self.teams(guild, name=name)
        if not teams:
            return 0
        if len(teams) > 1:
            raise ValueError(f"More than one result for team: {name}")
        if not teams[0].id:
            return 0
        return teams[0].id

    async def team_captain(
        self, guild: discord.Guild, team_name: str
    ) -> LeaguePlayer | None:
        """Return captain of a team by name"""
        players = await self.players(guild, status=Status.ROSTERED, team_name=team_name)
        if not players:
            return None
        return next((x for x in players if x.captain), None)

    async def tier_captains(
        self, guild: discord.Guild, tier_name: str
    ) -> list[LeaguePlayer]:
        """Return all captains in a tier"""
        players = await self.players(
            guild, status=Status.ROSTERED, tier_name=tier_name, limit=1000
        )
        if not players:
            return []

        captains = [x for x in players if x.captain if x.tier and x.tier.position]
        for c in captains:
            if not (c.team and c.team.name):
                raise AttributeError(
                    f"LeaguePlayer {c.id} captain is missing tier data."
                )

        captains.sort(key=lambda c: cast(str, c.team.name))
        return captains

    async def franchise_captains(
        self, guild: discord.Guild, franchise_name: str
    ) -> list[LeaguePlayer]:
        """Return all captains in a franchise"""
        players = await self.players(
            guild, status=Status.ROSTERED, franchise=franchise_name
        )
        if not players:
            return []

        captains = [x for x in players if x.captain if x.tier and x.tier.position]
        for c in captains:
            if not (c.tier and c.tier.position):
                raise AttributeError(
                    f"LeaguePlayer {c.id} captain is missing tier data."
                )

        captains.sort(key=lambda c: cast(int, c.tier.position), reverse=True)
        return captains

    # API

    async def teams(
        self,
        guild: discord.Guild,
        seasons: str | None = None,
        franchise: str | None = None,
        name: str | None = None,
        tier: str | None = None,
    ) -> list[TeamList]:
        """Fetch teams from API"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TeamsApi(client)
            teams = await api.teams_list(
                seasons=seasons,
                franchise=franchise,
                name=name,
                tier=tier,
                league=self._league[guild.id],
            )
            # Populate cache
            if teams:
                if not all(t.name for t in teams):
                    raise AttributeError("API returned a franchise with no name.")

                if self._team_cache.get(guild.id):
                    log.debug(f"[{guild.name}] Adding new teams to cache")
                    cached = set(self._team_cache[guild.id])
                    different = {t.name for t in teams if t.name} - cached
                    if different:
                        log.debug(
                            f"[{guild.name}] Teams being added to cache: {different}"
                        )
                        self._team_cache[guild.id] += list(different)
                else:
                    log.debug(f"[{guild.name}] Starting fresh teams cache")
                    self._team_cache[guild.id] = [t.name for t in teams if t.name]
                self._team_cache[guild.id].sort()
            return teams

    async def team_by_id(
        self,
        guild: discord.Guild,
        id: int,
    ) -> Team:
        """Fetch team data by id"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TeamsApi(client)
            return await api.teams_read(id)

    async def team_players(
        self,
        guild: discord.Guild,
        id: int,
    ) -> list[Player]:
        """Fetch team data by id"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TeamsApi(client)
            return await api.teams_players(id)

    async def next_match(
        self,
        guild: discord.Guild,
        id: int,
    ) -> Match | None:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TeamsApi(client)
            return await api.teams_next_match(id)

    async def season_matches(
        self,
        guild: discord.Guild,
        id: int,
        season: int | None = None,
        preseason: bool = False,
    ) -> list[HighLevelMatch]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TeamsApi(client)
            matches = await api.teams_season_matches(
                id, preseason=preseason, season=season
            )
            matches.sort(key=lambda x: cast(int, x.day))
            return matches

    async def team_stats(
        self,
        guild: discord.Guild,
        team_id: int,
        season: int | None = None,
    ) -> TeamSeasonStats:
        try:
            async with ApiClient(self._api_conf[guild.id]) as client:
                api = TeamsApi(client)
                stats = await api.teams_stats(team_id, season=season)
                return stats
        except ApiException as exc:
            raise RscException(exc)
