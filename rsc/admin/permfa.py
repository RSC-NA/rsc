# import logging
# import tempfile
# from typing import cast

# import discord
# from redbot.core import app_commands
# from rscapi.models.franchise import Franchise
# from rscapi.models.rebrand_a_franchise import RebrandAFranchise
# from rscapi.models.team_details import TeamDetails
# from rscapi.models.league_player import LeaguePlayer

# from rsc import const
# from rsc.admin import AdminMixIn
# from rsc.admin.modals import FranchiseRebrandModal
# from rsc.admin.views import (
#     CreateFranchiseView,
#     DeleteFranchiseView,
#     RebrandFranchiseView,
#     TransferFranchiseView,
#     PermFAConsentView,
# )
# from rsc.embeds import (
#     ApiExceptionErrorEmbed,
#     ErrorEmbed,
#     GreenEmbed,
#     LoadingEmbed,
#     SuccessEmbed,
#     YellowEmbed,
#     BlueEmbed,
# )
# from rsc.enums import Status
# from rsc.exceptions import RscException
# from rsc.franchises import FranchiseMixIn
# from rsc.logs import GuildLogAdapter
# from rsc.teams import TeamMixIn
# from rsc.tiers import TierMixIn
# from rsc.types import RebrandTeamDict
# from rsc.utils import utils
# from rsc.views import LinkButton

# logger = logging.getLogger("red.rsc.admin.franchise")
# log = GuildLogAdapter(logger)


# class AdminPermFAMixIn(AdminMixIn):
#     def __init__(self):
#         log.debug("Initializing AdminMixIn:PermFA")

#         super().__init__()

#     # Top level group

#     _permfa = app_commands.Group(
#         name="permfa",
#         description="Available commands for handling Permanent FAs",
#         parent=AdminMixIn._admin,
#         guild_only=True,
#         default_permissions=discord.Permissions(manage_guild=True),
#     )

#     # Commands

#     @_permfa.command(name="convert", description="Convert PermFAs in the API and discord")  # type: ignore
#     async def _admin_convert_permfa_cmd(self, interaction: discord.Interaction):
#         guild = interaction.guild
#         if not (guild and isinstance(interaction.user, discord.Member)):
#             return
#         await interaction.response.defer()

#         applicants = await self.get_permfa_applicants(guild)

#         log.debug(f"Found {len(applicants)} PermFAs that are ready to convert.")

#         # Send agreement to applicants
#         for app in applicants:
#             await self.send_permfa_agreement(guild, app)

#         embed = SuccessEmbed(
#             title="PermFA Conversion",
#             description="Applicable PermFA's have been messaged to begin conversion.",
#         )
#         await interaction.followup.send(embed=embed)

#     # Functions

#     async def get_permfa_applicants(self, guild: discord.Guild) -> list[LeaguePlayer]:
#         log.debug("Checking for PermFAs ready to convert")
#         applicants: list[LeaguePlayer] = []
#         async for player in self.paged_players(guild=guild, status=Status.PERMFA_W):
#             if not player.player.discord_id:
#                 log.warning(f"{player.player.name} has no discord ID attached in the API.")
#                 continue
#             if not (player.tier and player.tier.name and player.tier.id):
#                 log.debug(
#                     f"{player.player.name} ({player.player.discord_id}) has not been assigned a tier.",
#                     guild=guild,
#                 )
#                 continue
#             if player.current_mmr == 600 or player.base_mmr == 600:
#                 log.debug(
#                     f"{player.player.name} ({player.player.discord_id}) has not been assigned an MMR value.",
#                     guild=guild,
#                 )
#                 continue

#             applicants.append(player)
#         return applicants

#     async def send_permfa_agreement(self, guild: discord.Guild, league_player: LeaguePlayer):
#         if not league_player.player.discord_id:
#             log.warning(
#                 f"{league_player.player.name} has no discord ID in the API.",
#                 guild=guild,
#             )
#             raise AttributeError(f"{league_player.player.name} has no discord ID in the API.")

#         # Get member object
#         m = guild.get_member(league_player.player.discord_id)
#         if not m:
#             log.warning(
#                 f"{league_player.player.name} ({league_player.player.discord_id}) does not exist in guild.",
#                 guild=guild,
#             )
#             # Should retire them here
#             return

#         # Create Embed
#         embed = BlueEmbed(title="RSC Permanent FA Agreement")
#         embed.description = f"""
#         Hello, **{league_player.player.name}**.

#         Congratulations, your application to become a permanent free agent within RSC has been accepted!

#         In order to get your set up, all you have to do is press **Agree** at the bottom of this message.

#         If this was a mistake or you no longer wish to become a PermFA, you can select **Decline** and your application will be revoked.
#         """

#         embed.add_field(
#             name="What is a Permanent Free Agent?",
#             value="""
#             If you missed the draft or just don't have time to be a full player in RSC this season, this is a great way to still be involved, but with no commitment!

#             Permanent Free Agents (PermFAs) can **check in on match nights** like all other Free Agents, and **substitute in for a missing player as needed**. However, they **may not be rostered** by a team full-time.

#             As the season goes on, if the free agent pool in a tier runs low, we will select PermFAs to convert to **full time free agency on a first come**, first serve basis, as long as the player wants to convert.
#             """,
#             inline=False,
#         )

#         embed.add_field(
#             name="How do I check in?",
#             value="""
#             Matches are played at **10PM EST** and scrims begin at **9PM EST** on **Mondays and Wednesdays**, excluding holidays.

#             In order to check in and mark yourself available as a sub, all you need to do is head over to <#436741172560527361> and use the **bot command on an valid match day**:

#             `/freeagent checkin`

#             If at any point you decide you no longer wish to sub in that night, you can check out using the command:

#             `/freeagent checkout`
#             """,
#             inline=False,
#         )

#         if guild.icon:
#             embed.set_thumbnail(url=guild.icon.url)

#         # Create View
#         pfa_consent_view = PermFAConsentView(guild=guild, member=m, league_player=league_player)

#         await m.send(embed=embed, view=pfa_consent_view)

#     async def convert_permfa(self):
#         pass
