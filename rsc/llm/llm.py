from __future__ import annotations

import base64
import asyncio
import logging
from datetime import time, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import discord
from discord.ext import tasks
from redbot.core import app_commands, commands

from rsc.abc import RSCMixIn
from rsc.embeds import BlueEmbed, ErrorEmbed, GreenEmbed, YellowEmbed
from rsc.llm.create_db import (
    delete_documents_by_source,
    get_db_stats,
    load_current_season_doc,
    load_franchise_docs,
    load_funny_docs,
    load_help_docs,
    load_player_docs,
    load_player_stats_docs,
    load_rule_glossary_docs,
    load_rule_style_docs,
    load_match_docs,
    load_standings_docs,
    load_team_docs,
    load_team_stats_docs,
    markdown_to_documents,
    reset_collection,
    save_documents,
    string_to_doc,
)
from rsc.llm.sources import DocumentSource, STATIC_DOCUMENT_SOURCES, set_document_source
from rsc.llm.query import (
    llm_query,
    summarize_ticket_messages,
    UserIdentity,
)
from rsc.logs import GuildLogAdapter
from rsc.types import LLMSettings
from rsc.utils import utils


if TYPE_CHECKING:
    from collections.abc import Awaitable

    from langchain_core.documents import Document
    from rscapi.models.franchise_list import FranchiseList
    from rscapi.models.league_player import LeaguePlayer
    from rscapi.models.player_season_stats import PlayerSeasonStats
    from rscapi.models.season import Season
    from rscapi.models.team import Team
    from rscapi.models.team_season_stats import TeamSeasonStats
    from rscapi.models.tier import Tier

logger = logging.getLogger("red.rsc.llm")
log = GuildLogAdapter(logger)

defaults_guild = LLMSettings(
    LLMActive=False,
    LLMBlacklist=None,
    OpenAIKey=None,
    OpenAIOrg=None,
    SimilarityCount=5,
    SimilarityThreshold=0.65,
)

LLM_DB_LOOP_TIME = time(hour=8)
LLM_SUMMARY_MAX_MESSAGES = 200
LLM_SUMMARY_HARD_CHANNEL_CAP = 300
LLM_SUMMARY_MAX_VIEWERS = 40
LLM_SUMMARY_MAX_TRANSCRIPT_CHARS = 20000
LLM_SUMMARY_MAX_IMAGES = 10
LLM_SUMMARY_MAX_IMAGE_BYTES = 20 * 1024 * 1024
LLM_STATS_FETCH_CONCURRENCY = 8


class LLMMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing LLMMixIn")
        self.config.init_custom("LLM", 1)
        self.config.register_custom("LLM", **defaults_guild)
        super().__init__()

        # Start DB loop
        if not self.weekly_llm_db_refresh.is_running():
            self.weekly_llm_db_refresh.start()

    # Tasks

    @tasks.loop(time=LLM_DB_LOOP_TIME)
    async def weekly_llm_db_refresh(self):
        """Weekly refresh of the LLM Chroma DB"""
        log.info("Starting weekly LLM Chroma DB refresh task.")
        for guild in self.bot.guilds:
            # Only run on Monday morning
            tz = await self.timezone(guild)
            now = datetime.now(tz)
            if now.weekday() != 0:
                log.info("Skipping LLM DB refresh, not Monday.", guild=guild)
                continue

            if not await self._get_llm_status(guild):
                log.debug("LLM is not active, skipping DB refresh.", guild=guild)
                continue

            log.info("Refreshing LLM Chroma DB.", guild=guild)
            try:
                chunks = await self.create_chroma_db(guild)
            except ValueError as exc:
                log.error(f"Failed to refresh LLM Chroma DB: {exc}", exc_info=exc, guild=guild)
                continue

            log.info(f"Refreshed LLM Chroma DB with {chunks} chunks.", guild=guild)

    @weekly_llm_db_refresh.before_loop
    async def before_refresh(self):
        await self.bot.wait_until_ready()

    # Listener

    @commands.Cog.listener("on_message")
    async def llm_reply_to_mention(self, message: discord.Message):
        guild = message.guild
        if not guild:
            return

        # Check if LLM active
        if not await self._get_llm_status(guild):
            return

        # Ignore @everyone
        if message.mention_everyone:
            return

        # Replay to mention only
        if not guild.me.mentioned_in(message):
            return

        # Ignore news channels
        if isinstance(message.channel, discord.TextChannel) and message.channel.is_news():
            return

        # Skip a message reply to bot mention
        if message.reference is not None and not message.is_system():
            return

        # Check if channel in blacklist
        if message.channel.id in await self._get_llm_channel_blacklist(guild):
            return

        log.debug("Received mention, generating LLM response.")

        # Settings
        count, threshold = await self.get_llm_default(guild)
        org, key = await self.get_llm_credentials(guild)
        if not (org and key):
            log.warning("OpenAI Organization and or API key is not configured.", guild=guild)
            return

        # Resolve user identity and clean the question
        author = message.author
        tz = await self.timezone(guild)
        msg_datetime = message.created_at.astimezone(tz)
        log.debug("Resolving user identity for LLM mention response.", guild=guild)
        if isinstance(author, discord.Member):
            user_identity = await self.resolve_user_identity(guild, author, current_datetime=msg_datetime)
        else:
            # Fallback for User (non-member)
            user_identity = UserIdentity(name=author.display_name, current_datetime=msg_datetime)
        question = await self.clean_question(message, user_identity)

        try:
            response, _sources = await llm_query(
                guild=guild,
                org_name=org,
                api_key=key,
                question=question,
                count=count,
                threshold=threshold,
                user_identity=user_identity,
            )
        except RuntimeError as exc:
            log.error(str(exc), exc_info=exc)
            return

        if not response:
            return await message.reply(content="I am unable to answer that question.")

        await message.reply(content=str(response))

    # Top Level Group

    _llm_group = app_commands.Group(
        name="llm",
        description="Configure the RSC LLM",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )
    _llm_blacklist_group = app_commands.Group(
        name="blacklist",
        description="Configure channel blacklist for LLM responses",
        parent=_llm_group,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # Group commands

    # Settings
    @_llm_group.command(name="settings", description="Display LLM settings")
    async def _llm_settings_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        active = await self._get_llm_status(guild)
        openai_key = await self._get_openai_key(guild)
        openai_org = await self._get_openai_org(guild)
        llm_threshold = await self._get_llm_threshold(guild)
        llm_count = await self._get_llm_similarity_count(guild)

        # Format blacklist
        blacklist = await self._get_llm_channel_blacklist(guild)
        blacklist_channels = []
        for b in blacklist:
            c = guild.get_channel(b)
            if c:
                blacklist_channels.append(c)

        if blacklist_channels:  # noqa: SIM108
            blacklist_fmt = "\n".join([c.mention for c in blacklist_channels])
        else:
            blacklist_fmt = "None"

        settings_embed = BlueEmbed(
            title="LLM Settings",
            description="Displaying configured settings for RSC LLM",
        )
        settings_embed.add_field(name="Enabled", value=str(active), inline=False)
        settings_embed.add_field(name="OpenAI Organization", value=openai_org, inline=False)
        settings_embed.add_field(
            name="OpenAI API Key",
            value="Configured" if openai_key else "Not Configured",
            inline=False,
        )
        settings_embed.add_field(name="Similarity Count", value=str(llm_count), inline=False)
        settings_embed.add_field(name="Similarity Threshold", value=str(llm_threshold), inline=False)
        settings_embed.add_field(name="LLM Channel Blacklist", value=blacklist_fmt, inline=False)

        await interaction.response.send_message(embed=settings_embed, ephemeral=True)

    @_llm_group.command(name="toggle", description="Toggle llm on or off")
    async def _llm_toggle_cmd(self, interaction: discord.Interaction):
        """Toggle LLM on or off"""
        guild = interaction.guild
        if not guild:
            return

        status = await self._get_llm_status(guild)
        log.debug(f"Current LLM Status: {status}", guild=guild)
        status ^= True  # Flip boolean with xor
        log.debug(f"New LLM Status: {status}", guild=guild)
        await self._set_llm_status(guild, status)
        result = "**enabled**" if status else "**disabled**"
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"RSC LLM is now {result}.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_llm_group.command(name="organization", description="Configure the OpenAI organization")
    @app_commands.describe(name="OpenAI Organization")
    async def _llm_openai_org_cmd(self, interaction: discord.Interaction, name: str):
        """Configure OpenAI Organization"""
        guild = interaction.guild
        if not guild:
            return

        await self._set_openai_org(guild, name.strip())
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"OpenAI organization has been updated to **{name}**",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_llm_group.command(name="apikey", description="Configure the OpenAI API key")
    @app_commands.describe(key="OpenAI API Key")
    async def _llm_openai_key_cmd(self, interaction: discord.Interaction, key: str):
        """Configure OpenAI API Key"""
        guild = interaction.guild
        if not guild:
            return

        await self._set_openai_key(guild, key.strip())
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description="OpenAI API Key has been configured.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_llm_group.command(name="count", description="Configure the LLM max similarity count")
    @app_commands.describe(count="Number of similarity matches to get from DB")
    async def _llm_count_cmd(self, interaction: discord.Interaction, count: int):
        """Configure LLM similarity count"""
        guild = interaction.guild
        if not guild:
            return

        await self._set_llm_similarity_count(guild, count)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"Similarity count has been updated to **{count}**",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_llm_group.command(name="threshold", description="Configure the LLM threshold")
    @app_commands.describe(threshold="Float threshold for finding similarities (Default: 0.65)")
    async def _llm_threshold_cmd(self, interaction: discord.Interaction, threshold: float):
        """Configure LLM threshold"""
        guild = interaction.guild
        if not guild:
            return

        await self._set_llm_threshold(guild, threshold)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"Threshold has been updated to **{threshold}**",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_llm_group.command(name="query", description="Query the RSC LLM")
    @app_commands.describe(question="Question to ask the RSC LLM")
    async def _llm_query_cmd(self, interaction: discord.Interaction, question: str):
        """Query the RSC LLM with a question"""
        guild = interaction.guild
        if not guild:
            return

        # Settings
        count, threshold = await self.get_llm_default(guild)
        org, key = await self.get_llm_credentials(guild)
        if not (org and key):
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="OpenAI organization and or API key has not been configured."),
                ephemeral=True,
            )

        await interaction.response.defer()

        # Resolve user identity and clean the question
        member = interaction.user
        if isinstance(member, discord.User):
            # Convert User to Member if possible
            member = guild.get_member(member.id) or member

        tz = await self.timezone(guild)
        interaction_datetime = interaction.created_at.astimezone(tz)
        user_identity = (
            await self.resolve_user_identity(guild, member, current_datetime=interaction_datetime)
            if isinstance(member, discord.Member)
            else None
        )

        log.debug(f"Original question: {question}", guild=guild)

        try:
            response, sources = await llm_query(
                guild=guild,
                org_name=org,
                api_key=key,
                question=question,
                count=count,
                threshold=threshold,
                user_identity=user_identity,
            )
        except RuntimeError as exc:
            return await interaction.followup.send(content=str(exc), ephemeral=True)

        if not response:
            response_fmt = "I am unable to answer that question."
            source_fmt = None
        else:
            response_fmt = str(response)
            source_fmt = await self.format_llm_sources(sources)

        embed = BlueEmbed(title="RSC AI")
        embed.add_field(name="Question", value=question, inline=False)
        embed.add_field(name="Response", value=response_fmt, inline=False)

        if source_fmt:
            embed.add_field(name="Sources", value=source_fmt, inline=False)

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        await interaction.followup.send(embed=embed)

    @_llm_group.command(name="summarize", description="Summarize a private ModMail ticket channel or thread")
    @app_commands.describe(
        channel="Ticket text channel or thread to summarize (defaults to current channel)",
        message_limit="Number of recent messages to summarize (max 200)",
    )
    async def _llm_summarize_cmd(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | discord.Thread | None = None,
        message_limit: app_commands.Range[int, 25, LLM_SUMMARY_MAX_MESSAGES] = 120,
    ):
        """Summarize a private ModMail ticket text channel/thread."""
        guild = interaction.guild
        if not guild:
            return

        # Only allow TextChannels or Threads
        target = channel or interaction.channel
        if not isinstance(target, (discord.TextChannel | discord.Thread)):
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="This command only supports text channels and threads."),
                ephemeral=True,
            )

        # Must be discord.Member to check permissions
        member = interaction.user
        if not isinstance(member, discord.Member):
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Unable to resolve your member permissions in this server."),
                ephemeral=True,
            )

        if not target.permissions_for(member).view_channel:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="You do not have permission to view that channel/thread."),
                ephemeral=True,
            )

        # Settings
        org, key = await self.get_llm_credentials(guild)
        if not (org and key):
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="OpenAI organization and or API key has not been configured."),
                ephemeral=True,
            )

        # Check that this is a private discord channel (Don't allow summary of public channels)
        privacy_ok, privacy_reason = self._is_private_ticket_channel(guild, target)
        if not privacy_ok:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description=privacy_reason),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        # Pull at most hard cap + 1 to reject large channels quickly.
        history = [m async for m in target.history(limit=LLM_SUMMARY_HARD_CHANNEL_CAP + 1)]
        if len(history) > LLM_SUMMARY_HARD_CHANNEL_CAP:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=(
                        "This channel has too many recent messages for safe summarization. "
                        f"Please use a smaller ticket thread or reduce recent activity (>{LLM_SUMMARY_HARD_CHANNEL_CAP} messages)."
                    )
                ),
                ephemeral=True,
            )

        if not history:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="No messages found in this channel/thread to summarize."),
                ephemeral=True,
            )

        # Only allow modmails
        # if not self._contains_modmail_messages(history):
        #     return await interaction.followup.send(
        #         embed=ErrorEmbed(
        #             description=(
        #                 "This does not look like a ModMail ticket thread. "
        #                 "Expected at least one message from a bot with 'modmail' in its name."
        #             )
        #         ),
        #         ephemeral=True,
        #     )

        summary_messages = list(reversed(history[:message_limit]))
        transcript = self._build_summary_transcript(summary_messages, max_chars=LLM_SUMMARY_MAX_TRANSCRIPT_CHARS)
        if not transcript:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Could not build transcript data from the selected messages."),
                ephemeral=True,
            )

        image_data_urls, image_error = await self._collect_summary_images(summary_messages)
        if image_error:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=image_error),
                ephemeral=True,
            )

        try:
            summary = await summarize_ticket_messages(
                guild=guild,
                org_name=org,
                api_key=key,
                transcript=transcript,
                image_data_urls=image_data_urls,
            )
        except RuntimeError as exc:
            return await interaction.followup.send(content=str(exc), ephemeral=True)

        if not summary:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="I could not summarize that ticket right now."),
                ephemeral=True,
            )

        embed = BlueEmbed(
            title="Ticket Summary",
            description=summary,
        )
        embed.add_field(name="Channel", value=target.mention, inline=True)
        embed.add_field(name="Messages", value=str(len(summary_messages)), inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @_llm_group.command(name="createdb", description="Create the LLM Chroma DB")
    async def _llm_createdb_cmd(self, interaction: discord.Interaction):
        """Create the LLM Chroma DB"""
        guild = interaction.guild
        if not guild:
            return

        # Settings
        org, key = await self.get_llm_credentials(guild)
        if not (org and key):
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="OpenAI organization and or API key has not been configured."),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        try:
            chunks = await self.create_chroma_db(guild, interaction=interaction)
        except ValueError as exc:
            return await interaction.followup.send(content=str(exc), ephemeral=True)

        await interaction.followup.send(
            embed=BlueEmbed(title="Chroma DB", description=f"Saved {chunks} chunks to Chroma DB."),
            ephemeral=True,
        )

    @_llm_group.command(name="refresh", description="Refresh a specific document source in the LLM Chroma DB")
    @app_commands.describe(source="Document source to refresh")
    @app_commands.choices(
        source=[
            app_commands.Choice(name="All Static Docs", value="static"),
            app_commands.Choice(name="Rulebook", value="rulebook"),
            app_commands.Choice(name="Glossary", value="glossary"),
            app_commands.Choice(name="Dates", value="dates"),
            app_commands.Choice(name="Help", value="help"),
            app_commands.Choice(name="Funny", value="funny"),
            app_commands.Choice(name="Franchises", value="franchises"),
            app_commands.Choice(name="Players", value="players"),
            app_commands.Choice(name="Player Stats", value="player_stats"),
            app_commands.Choice(name="Matches", value="matches"),
            app_commands.Choice(name="Teams", value="teams"),
            app_commands.Choice(name="Team Stats", value="team_stats"),
            app_commands.Choice(name="Standings", value="standings"),
            app_commands.Choice(name="Season", value="season"),
        ]
    )
    async def _llm_refresh_cmd(self, interaction: discord.Interaction, source: app_commands.Choice[str]):
        """Refresh a specific document source in the LLM Chroma DB"""
        guild = interaction.guild
        if not guild:
            return

        # Settings
        org, key = await self.get_llm_credentials(guild)
        if not (org and key):
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="OpenAI organization and or API key has not been configured."),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        try:
            if source.value == "static":
                count = await self.refresh_static_document_sources(guild, interaction=interaction)
            else:
                document_source = DocumentSource(source.value)
                count = await self.refresh_document_source(guild, document_source, interaction=interaction)
        except ValueError as exc:
            return await interaction.followup.send(content=str(exc), ephemeral=True)

        await interaction.followup.send(
            embed=GreenEmbed(
                title="Documents Refreshed",
                description=f"Refreshed **{source.name}** documents.\n\nSaved **{count}** chunks to Chroma DB.",
            ),
            ephemeral=True,
        )

    @_llm_group.command(name="resetdb", description="Reset the LLM Chroma DB (deletes all documents)")
    async def _llm_resetdb_cmd(self, interaction: discord.Interaction):
        """Reset the LLM Chroma DB by deleting all documents"""
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        await reset_collection(guild)

        await interaction.followup.send(
            embed=GreenEmbed(
                title="Database Reset",
                description=(
                    "The LLM Chroma DB has been reset. All documents have been deleted.\n\nRun `/llm createdb` to rebuild the database."
                ),
            ),
            ephemeral=True,
        )

    @_llm_group.command(name="dbstats", description="Show LLM database statistics")
    async def _llm_dbstats_cmd(self, interaction: discord.Interaction):
        """Show LLM database statistics"""
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        stats = await get_db_stats(guild)

        if not stats["exists"]:
            embed: discord.Embed = YellowEmbed(
                title="LLM Database Stats",
                description="No database found for this server. Run `/llm createdb` to create one.",
            )
        else:
            embed: discord.Embed = BlueEmbed(
                title="LLM Database Stats",
                description="ChromaDB statistics for this server",
            )
            embed.add_field(name="Collection Name", value=stats["collection_name"], inline=False)
            embed.add_field(name="Document Count", value=f"{stats['document_count']:,}", inline=False)
            embed.add_field(name="Database Path", value=stats["db_path"], inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @_llm_blacklist_group.command(name="show", description="Display the LLM channel blacklist")
    async def _llm_blacklist_show_cmd(self, interaction: discord.Interaction):
        """Display the LLM channel blacklist"""
        guild = interaction.guild
        if not guild:
            return

        blacklist = await self._get_llm_channel_blacklist(guild)

        channels = []
        for b in blacklist:
            c = guild.get_channel(b)
            if c:
                channels.append(c)

        if channels:  # noqa: SIM108
            blacklist_fmt = "\n".join([c.mention for c in channels])
        else:
            blacklist_fmt = "None"

        embed = BlueEmbed(
            title="LLM Channel Blacklist",
            description="The following channels are blacklisted from LLM responses.",
        )
        embed.add_field(name="Channels", value=blacklist_fmt, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_llm_blacklist_group.command(name="add", description="Add a channel to the LLM blacklist")
    @app_commands.describe(channel="Discord text channel to blacklist")
    async def _llm_blacklist_add_cmd(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Add a channel to the LLM blacklist"""
        guild = interaction.guild
        if not guild:
            return

        await self._add_llm_channel_blacklist(guild, channel)
        embed = GreenEmbed(
            title="LLM Channel Blacklisted",
            description=f"{channel.mention} has been added to the LLM channel blacklist.",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_llm_blacklist_group.command(name="rm", description="Remove a channel from the LLM blacklist")
    @app_commands.describe(channel="Discord text channel to remove")
    async def _llm_blacklist_rm_cmd(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Remove a channel from the LLM blacklist"""
        guild = interaction.guild
        if not guild:
            return

        await self._rm_llm_channel_blacklist(guild, channel)
        embed = GreenEmbed(
            title="LLM Blacklist Removed",
            description=f"{channel.mention} has been removed from the LLM channel blacklist.",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # Helpers

    async def create_chroma_db(self, guild: discord.Guild, interaction: discord.Interaction | None = None) -> int:
        org, key = await self.get_llm_credentials(guild)
        if not (org and key):
            raise ValueError("OpenAI organization and or API key has not been configured.")

        total_docs = 0

        if interaction:
            await interaction.edit_original_response(
                embed=YellowEmbed(
                    title="Creating Chroma DB",
                    description="Resetting database collection.",
                )
            )

        current_season = await self.current_season(guild)
        if not current_season:
            raise ValueError("Current season is not configured, cannot create LLM Chroma DB.")
        if not current_season.number:
            raise ValueError("Current season number is not set, cannot create LLM Chroma DB.")

        # Reset the collection before adding new documents
        await reset_collection(guild)

        if interaction:
            await interaction.edit_original_response(
                embed=YellowEmbed(
                    title="Creating Chroma DB",
                    description="Loading documents from rules, API data, and match history.",
                )
            )

        franchises_task = asyncio.create_task(self.franchises(guild))
        doc_groups = await asyncio.gather(
            self._build_rules_documents(guild),
            self._build_current_season_documents(guild, current_season),
            self._build_franchise_documents(guild, current_season.id, franchises=franchises_task),
            self._build_player_documents(guild),
            self._build_player_stats_documents(guild, current_season.number),
            self._build_match_documents(guild, current_season.number),
            self._build_team_documents(guild, franchises=franchises_task),
            self._build_team_stats_documents(guild, current_season, franchises=franchises_task),
            self._build_standings_documents(guild, current_season),
        )
        docs = [doc for group in doc_groups for doc in group]
        total_docs = len(docs)

        if interaction:
            await interaction.edit_original_response(
                embed=YellowEmbed(
                    title="Creating Chroma DB",
                    description=f"Saving {total_docs} documents to the database.",
                )
            )

        await save_documents(guild, org, key, docs)

        if interaction:
            await interaction.edit_original_response(
                embed=YellowEmbed(
                    title="Creating Chroma DB",
                    description="Database saved successfully.",
                )
            )

        log.info(f"Chroma Document Total: {total_docs}")
        log.info("Chroma database created")
        return total_docs

    async def _build_current_season_documents(self, guild: discord.Guild, current_season: Season | None = None) -> list[Document]:
        """Build current season documents without saving them."""
        season = current_season or await self.current_season(guild)
        if not season:
            log.warning("API returned no current season.", guild=guild)
            return []
        season_doc = await load_current_season_doc(season)
        set_document_source(season_doc, DocumentSource.SEASON)
        return [season_doc]

    async def _build_rules_documents(self, guild: discord.Guild) -> list[Document]:
        """Build rules, help, date, and funny documents without saving them."""
        log.info("Creating rules/help/funny documents.", guild=guild)
        doc_groups = await asyncio.gather(
            self._build_dates_documents(guild),
            self._build_rulebook_documents(guild),
            self._build_glossary_documents(guild),
            self._build_help_documents(guild),
            self._build_funny_documents(guild),
        )
        return [doc for group in doc_groups for doc in group]

    async def _build_dates_documents(self, guild: discord.Guild) -> list[Document]:
        """Build dates corpus documents without saving them."""
        dates = await self._get_dates(guild)
        if dates:
            date_doc = await string_to_doc(dates)
            date_doc.metadata["source"] = "Dates"
            set_document_source(date_doc, DocumentSource.DATES)
            return [date_doc]
        return []

    async def _build_rulebook_documents(self, guild: discord.Guild) -> list[Document]:
        """Build rulebook corpus documents without saving them."""
        log.debug("Creating rule documents.", guild=guild)
        rule_docs: list[Document] = []
        rulepath = Path(__file__).parent.parent / "resources" / "rules"
        rule_files = [rulepath / "RSC Rules.md"]
        rule_groups = await asyncio.gather(*(load_rule_style_docs(fd) for fd in rule_files))
        for rdocs in rule_groups:
            for doc in rdocs:
                set_document_source(doc, DocumentSource.RULEBOOK)
            rule_docs.extend(rdocs)
        return rule_docs

    async def _build_glossary_documents(self, guild: discord.Guild) -> list[Document]:
        """Build glossary corpus documents without saving them."""
        log.debug("Creating glossary documents.", guild=guild)
        rulepath = Path(__file__).parent.parent / "resources" / "rules" / "RSC Rules.md"
        glossary_docs = await load_rule_glossary_docs(rulepath)
        for doc in glossary_docs:
            set_document_source(doc, DocumentSource.GLOSSARY)
        return glossary_docs

    async def _build_help_documents(self, guild: discord.Guild) -> list[Document]:
        """Build help corpus documents without saving them."""
        log.debug("Creating help documents.", guild=guild)
        helpdocs = await load_help_docs()
        help_md_docs = await markdown_to_documents(helpdocs)
        for doc in help_md_docs:
            set_document_source(doc, DocumentSource.HELP)
        return help_md_docs

    async def _build_funny_documents(self, guild: discord.Guild) -> list[Document]:
        """Build funny corpus documents without saving them."""
        log.debug("Creating funny documents.", guild=guild)
        funnydocs = await load_funny_docs()
        funny_md_docs = await markdown_to_documents(funnydocs)
        for doc in funny_md_docs:
            set_document_source(doc, DocumentSource.FUNNY)
        return funny_md_docs

    async def _resolve_franchises(
        self,
        guild: discord.Guild,
        franchises: list[FranchiseList] | Awaitable[list[FranchiseList]] | None = None,
    ) -> list[FranchiseList]:
        if franchises is None:
            return await self.franchises(guild)
        if isinstance(franchises, list):
            return franchises
        return await franchises

    async def _build_franchise_documents(
        self,
        guild: discord.Guild,
        current_season: int | None = None,
        franchises: list[FranchiseList] | Awaitable[list[FranchiseList]] | None = None,
    ) -> list[Document]:
        """Build franchise documents without saving them."""
        log.info("Creating franchise documents.", guild=guild)
        franchises = await self._resolve_franchises(guild, franchises)
        if not franchises:
            log.debug("No franchises found.", guild=guild)
            return []

        standings = None
        if current_season:
            standings = await self.franchise_standings(guild, season_id=current_season)

        log.debug(f"Franchise Count: {len(franchises)}", guild=guild)
        franchise_docs = await load_franchise_docs(franchises, standings=standings)
        for doc in franchise_docs:
            set_document_source(doc, DocumentSource.FRANCHISES)
        return franchise_docs

    async def _build_player_documents(self, guild: discord.Guild) -> list[Document]:
        """Build player documents without saving them."""
        log.info("Creating player documents.", guild=guild)
        players = await utils.async_iter_gather(self.paged_players(guild))
        log.debug(f"Total Players: {len(players)}", guild=guild)
        player_docs = await load_player_docs(players)
        for doc in player_docs:
            set_document_source(doc, DocumentSource.PLAYERS)
        return player_docs

    async def _build_player_stats_documents(self, guild: discord.Guild, season_number: int) -> list[Document]:
        """Build current-season player stats documents without saving them."""
        log.info("Creating player stats documents.", guild=guild)
        players = await utils.async_iter_gather(self.paged_players(guild))
        semaphore = asyncio.Semaphore(LLM_STATS_FETCH_CONCURRENCY)

        async def fetch_player_stats(player: LeaguePlayer) -> PlayerSeasonStats | None:
            if not (player.player and player.player.discord_id):
                return None
            async with semaphore:
                member = cast("discord.Member", guild.get_member(player.player.discord_id) or discord.Object(id=player.player.discord_id))
                try:
                    return await self.player_stats(guild, member, season=season_number)
                except Exception as exc:
                    log.debug(f"Unable to fetch player stats for {player.player.name}: {exc}", guild=guild)
                    return None

        stats_results = await asyncio.gather(*(fetch_player_stats(player) for player in players))
        stats = [stats for stats in stats_results if stats]
        log.debug(f"Player Stats Count: {len(stats)}", guild=guild)
        player_stats_docs = await load_player_stats_docs(stats)
        for doc in player_stats_docs:
            set_document_source(doc, DocumentSource.PLAYER_STATS)
        return player_stats_docs

    async def _build_match_documents(self, guild: discord.Guild, season_number: int) -> list[Document]:
        """Build match documents without saving them."""
        log.info("Creating match documents.", guild=guild)

        # Create a match fetcher that captures the guild
        async def fetch_match(match_id: int):
            log.debug(f"Fetching match results for ID: {match_id}", guild=guild)
            return await self.match_results(guild, match_id)

        matches = await utils.async_iter_gather(self.paged_matches(guild, season_number=season_number))
        log.debug(f"Total Matches: {len(matches)}", guild=guild)
        match_docs = await load_match_docs(matches, match_fetcher=fetch_match)
        for doc in match_docs:
            set_document_source(doc, DocumentSource.MATCHES)
        return match_docs

    async def _collect_franchise_teams(
        self,
        guild: discord.Guild,
        franchises: list[FranchiseList] | Awaitable[list[FranchiseList]] | None = None,
    ) -> list[Team]:
        franchises = await self._resolve_franchises(guild, franchises)
        teams: list[Team] = []

        async def fetch_franchise_teams(f: FranchiseList) -> list[Team]:
            if not (f.id and f.teams):
                return []

            fdata = await self.franchise_by_id(guild, id=f.id)
            if not (fdata and fdata.teams):
                return []

            return list(fdata.teams)

        franchise_team_groups = await asyncio.gather(*(fetch_franchise_teams(f) for f in franchises))
        for group in franchise_team_groups:
            teams.extend(group)

        return teams

    async def _build_team_documents(
        self,
        guild: discord.Guild,
        franchises: list[FranchiseList] | Awaitable[list[FranchiseList]] | None = None,
    ) -> list[Document]:
        """Build team documents without saving them."""
        log.info("Creating team documents.", guild=guild)
        teams = await self._collect_franchise_teams(guild, franchises=franchises)

        if not teams:
            log.debug("No teams found.", guild=guild)
            return []

        log.debug(f"Team Count: {len(teams)}", guild=guild)
        team_docs = await load_team_docs(teams)
        for doc in team_docs:
            set_document_source(doc, DocumentSource.TEAMS)
        return team_docs

    async def _build_team_stats_documents(
        self,
        guild: discord.Guild,
        current_season: Season,
        franchises: list[FranchiseList] | Awaitable[list[FranchiseList]] | None = None,
    ) -> list[Document]:
        """Build current-season team stats documents without saving them."""
        log.info("Creating team stats documents.", guild=guild)
        teams = await self._collect_franchise_teams(guild, franchises=franchises)
        semaphore = asyncio.Semaphore(LLM_STATS_FETCH_CONCURRENCY)

        async def fetch_team_stats(team: Team) -> TeamSeasonStats | None:
            if not team.id:
                return None
            async with semaphore:
                try:
                    return await self.team_stats(guild, team_id=team.id, season=current_season.id)
                except Exception as exc:
                    log.debug(f"Unable to fetch team stats for {team.name}: {exc}", guild=guild)
                    return None

        stats_results = await asyncio.gather(*(fetch_team_stats(team) for team in teams))
        stats = [stats for stats in stats_results if stats]
        log.debug(f"Team Stats Count: {len(stats)}", guild=guild)
        team_stats_docs = await load_team_stats_docs(stats, season_number=current_season.number)
        for doc in team_stats_docs:
            set_document_source(doc, DocumentSource.TEAM_STATS)
        return team_stats_docs

    async def _build_standings_documents(self, guild: discord.Guild, current_season: Season) -> list[Document]:
        """Build current-season franchise and tier standings documents without saving them."""
        log.info("Creating standings documents.", guild=guild)
        franchise_standings = []
        if current_season.id:
            franchise_standings = await self.franchise_standings(guild, season_id=current_season.id)

        tiers = await self.tiers(guild)
        semaphore = asyncio.Semaphore(LLM_STATS_FETCH_CONCURRENCY)

        async def fetch_tier_standings(tier: Tier):
            if not (tier.id and current_season.number):
                return []
            async with semaphore:
                try:
                    return await self.tier_standings(guild, tier_id=tier.id, season=current_season.number)
                except Exception as exc:
                    log.debug(f"Unable to fetch standings for tier {tier.name}: {exc}", guild=guild)
                    return []

        team_standings_groups = await asyncio.gather(*(fetch_tier_standings(tier) for tier in tiers))
        team_standings = [standing for group in team_standings_groups for standing in group]
        log.debug(
            f"Standings Count: {len(franchise_standings)} franchise, {len(team_standings)} team",
            guild=guild,
        )
        standings_docs = await load_standings_docs(
            franchise_standings=franchise_standings,
            team_standings=team_standings,
            season_number=current_season.number,
        )
        for doc in standings_docs:
            set_document_source(doc, DocumentSource.STANDINGS)
        return standings_docs

    async def refresh_document_source(
        self,
        guild: discord.Guild,
        source: DocumentSource,
        interaction: discord.Interaction | None = None,
    ) -> int:
        """
        Refresh only a specific document source in the ChromaDB.

        Args:
            guild: Discord guild
            source: Source of documents to refresh
            interaction: Optional interaction for progress updates

        Returns:
            Number of documents added
        """
        org, key = await self.get_llm_credentials(guild)
        if not (org and key):
            raise ValueError("OpenAI organization and or API key has not been configured.")

        async def require_current_season() -> Season:
            current_season = await self.current_season(guild)
            if not current_season or not current_season.number:
                raise ValueError("Current season is not configured.")
            return current_season

        if interaction:
            await interaction.edit_original_response(
                embed=YellowEmbed(
                    title="Refreshing Documents",
                    description=f"Deleting existing {source.value} documents...",
                )
            )
        deleted = await delete_documents_by_source(guild, source)
        log.info(f"Deleted {deleted} existing {source.value} documents.", guild=guild)

        if interaction:
            await interaction.edit_original_response(
                embed=YellowEmbed(
                    title="Refreshing Documents",
                    description=f"Loading new {source.value} documents...",
                )
            )

        match source:
            case DocumentSource.RULEBOOK:
                docs = await self._build_rulebook_documents(guild)
            case DocumentSource.GLOSSARY:
                docs = await self._build_glossary_documents(guild)
            case DocumentSource.DATES:
                docs = await self._build_dates_documents(guild)
            case DocumentSource.HELP:
                docs = await self._build_help_documents(guild)
            case DocumentSource.FUNNY:
                docs = await self._build_funny_documents(guild)
            case DocumentSource.FRANCHISES:
                current_season = await require_current_season()
                docs = await self._build_franchise_documents(guild, current_season.id)
            case DocumentSource.PLAYERS:
                docs = await self._build_player_documents(guild)
            case DocumentSource.PLAYER_STATS:
                current_season = await require_current_season()
                docs = await self._build_player_stats_documents(guild, current_season.number)
            case DocumentSource.MATCHES:
                current_season = await require_current_season()
                docs = await self._build_match_documents(guild, current_season.number)
            case DocumentSource.TEAMS:
                docs = await self._build_team_documents(guild)
            case DocumentSource.TEAM_STATS:
                current_season = await require_current_season()
                docs = await self._build_team_stats_documents(guild, current_season)
            case DocumentSource.STANDINGS:
                current_season = await require_current_season()
                docs = await self._build_standings_documents(guild, current_season)
            case DocumentSource.SEASON:
                current_season = await require_current_season()
                docs = await self._build_current_season_documents(guild, current_season)

        await save_documents(guild, org, key, docs)
        log.info(f"Saved {len(docs)} {source.value} documents.", guild=guild)
        return len(docs)

    async def refresh_static_document_sources(
        self,
        guild: discord.Guild,
        interaction: discord.Interaction | None = None,
    ) -> int:
        """Refresh all static document sources and save them in one Chroma write."""
        org, key = await self.get_llm_credentials(guild)
        if not (org and key):
            raise ValueError("OpenAI organization and or API key has not been configured.")

        for source in STATIC_DOCUMENT_SOURCES:
            if interaction:
                await interaction.edit_original_response(
                    embed=YellowEmbed(
                        title="Refreshing Documents",
                        description=f"Deleting existing {source.value} documents...",
                    )
                )
            deleted = await delete_documents_by_source(guild, source)
            log.info(f"Deleted {deleted} existing {source.value} documents.", guild=guild)

        if interaction:
            await interaction.edit_original_response(
                embed=YellowEmbed(
                    title="Refreshing Documents",
                    description="Loading new static documents...",
                )
            )

        docs = await self._build_rules_documents(guild)
        await save_documents(guild, org, key, docs)
        log.info(f"Saved {len(docs)} static documents.", guild=guild)
        return len(docs)

    async def resolve_user_identity(
        self,
        guild: discord.Guild,
        member: discord.Member,
        current_datetime: datetime | None = None,
    ) -> UserIdentity | None:
        """
        Resolve user identity from Discord member to league player data.

        Args:
            guild: Discord guild
            member: Discord member to look up
            current_datetime: Current datetime for time-aware queries

        Returns:
            UserIdentity with player data, or None if not found
        """
        try:
            players = await self.players(guild, discord_id=member.id, limit=1)
            if not players:
                # Fall back to display name without prefix
                no_prefix = await utils.remove_prefix(member)
                return UserIdentity(name=no_prefix, current_datetime=current_datetime)

            player = players[0]
            return UserIdentity(
                name=player.player.name if player.player else await utils.remove_prefix(member),
                team=player.team.name if player.team else None,
                franchise=player.team.franchise.name if player.team and player.team.franchise else None,
                tier=player.tier.name if player.tier else None,
                status=player.status,
                current_datetime=current_datetime,
            )
        except Exception as exc:
            log.warning(f"Failed to resolve user identity: {exc}", guild=guild)
            no_prefix = await utils.remove_prefix(member)
            return UserIdentity(name=no_prefix, current_datetime=current_datetime)

    async def clean_question(
        self,
        message: discord.Message,
        user_identity: UserIdentity | None = None,
    ) -> str:
        if not message.guild:
            return message.clean_content

        # Remove bot mention
        cleaned_msg = message.clean_content.replace(f"@{message.guild.me.display_name}", "").strip()
        log.debug(f"Original Question: {cleaned_msg}")

        log.debug(f"Question without bot mention: {cleaned_msg}")

        return cleaned_msg

    async def format_llm_sources(self, sources: list[dict[str, str | int | None]]) -> str:
        """Format source metadata for display.

        Args:
            sources: List of metadata dicts with 'source', 'id', 'chunk_index' keys

        Returns:
            Formatted string of unique sources
        """
        results: list[str] = []
        seen: set[str] = set()
        for meta in sources:
            source = meta.get("source")
            doc_id = meta.get("id")
            if source and source not in seen:
                seen.add(source)
                if doc_id:
                    results.append(f"- {source} (ID: {doc_id})")
                else:
                    results.append(f"- {source}")
        return "\n".join(results)

    def _is_private_ticket_channel(self, guild: discord.Guild, channel: discord.TextChannel | discord.Thread) -> tuple[bool, str]:
        """Validate channel privacy and audience size for ticket summarization."""
        everyone_can_view = channel.permissions_for(guild.default_role).view_channel
        if everyone_can_view:
            return (
                False,
                "This command is restricted to private ticket channels/threads.",
            )

        if isinstance(channel, discord.Thread):
            if hasattr(channel, "is_private") and callable(channel.is_private) and channel.is_private():
                return (True, "")

            parent = channel.parent
            if isinstance(parent, discord.TextChannel):
                private_parent = not parent.permissions_for(guild.default_role).view_channel
                if private_parent:
                    return (True, "")
        # Keep this feature limited to smaller private channels used for tickets.
        elif len(channel.members) > LLM_SUMMARY_MAX_VIEWERS:
            return (
                False,
                f"This channel appears to be broadly visible ({len(channel.members)} viewers). "
                f"Ticket summaries are limited to <= {LLM_SUMMARY_MAX_VIEWERS} viewers.",
            )

        return (True, "")

    def _contains_modmail_messages(self, messages: list[discord.Message]) -> bool:
        """Detect whether message history appears to come from ModMail bot activity."""
        for msg in messages:
            author_name = msg.author.name.lower()
            display_name = msg.author.display_name.lower()
            if msg.author.bot and ("modmail" in author_name or "modmail" in display_name):
                return True
        return False

    def _build_summary_transcript(self, messages: list[discord.Message], max_chars: int = 20000) -> str:
        """Build a compact transcript for LLM summarization."""
        rows: list[str] = []
        total = 0
        image_index = 0
        for msg in messages:
            content = msg.clean_content.strip()
            image_markers: list[str] = []
            for attachment in msg.attachments:
                if self._is_image_attachment(attachment):
                    image_index += 1
                    image_markers.append(f"image-{image_index}")

            if image_markers:
                marker_text = " ".join(f"[{marker}]" for marker in image_markers)
                content = f"{content} {marker_text}".strip() if content else marker_text

            if not content and msg.attachments:
                content = f"[{len(msg.attachments)} attachment(s)]"
            elif not content:
                continue

            content = " ".join(content.split())
            line = f"[{msg.created_at.isoformat()}] {msg.author.display_name}: {content}"

            line_len = len(line) + 1
            if total + line_len > max_chars:
                break

            rows.append(line)
            total += line_len

        return "\n".join(rows)

    async def _collect_summary_images(self, messages: list[discord.Message]) -> tuple[list[str], str | None]:
        """Collect full image attachments as data URLs for multimodal moderation summary."""
        data_urls: list[str] = []
        total_bytes = 0

        for msg in messages:
            for attachment in msg.attachments:
                if not self._is_image_attachment(attachment):
                    continue

                if len(data_urls) >= LLM_SUMMARY_MAX_IMAGES:
                    return (
                        [],
                        f"Too many images to summarize safely. Limit is {LLM_SUMMARY_MAX_IMAGES} images; reduce message_limit.",
                    )

                raw = await attachment.read(use_cached=True)
                total_bytes += len(raw)
                if total_bytes > LLM_SUMMARY_MAX_IMAGE_BYTES:
                    max_mb = LLM_SUMMARY_MAX_IMAGE_BYTES // (1024 * 1024)
                    return (
                        [],
                        f"Image payload is too large to summarize safely (>{max_mb}MB total). Reduce message_limit.",
                    )

                mime = self._attachment_mime(attachment)
                b64 = base64.b64encode(raw).decode("ascii")
                data_urls.append(f"data:{mime};base64,{b64}")

        return (data_urls, None)

    def _is_image_attachment(self, attachment: discord.Attachment) -> bool:
        content_type = (attachment.content_type or "").lower()
        if content_type.startswith("image/"):
            return True

        filename = (attachment.filename or "").lower()
        return filename.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"))

    def _attachment_mime(self, attachment: discord.Attachment) -> str:
        content_type = (attachment.content_type or "").lower()
        if content_type.startswith("image/"):
            return content_type

        filename = (attachment.filename or "").lower()
        if filename.endswith(".png"):
            return "image/png"
        if filename.endswith((".jpg", ".jpeg")):
            return "image/jpeg"
        if filename.endswith(".webp"):
            return "image/webp"
        if filename.endswith(".gif"):
            return "image/gif"
        if filename.endswith(".bmp"):
            return "image/bmp"
        return "application/octet-stream"

    async def get_llm_credentials(self, guild: discord.Guild) -> tuple[str | None, str | None]:
        org = await self._get_openai_org(guild)
        key = await self._get_openai_key(guild)
        return (org, key)

    async def get_llm_default(self, guild: discord.Guild) -> tuple[int, float]:
        count = await self._get_llm_similarity_count(guild)
        threshold = await self._get_llm_threshold(guild)
        return (count, threshold)

    # Config

    async def _get_llm_status(self, guild: discord.Guild) -> bool:
        """Get LLM active status"""
        return await self.config.custom("LLM", str(guild.id)).LLMActive()

    async def _set_llm_status(self, guild: discord.Guild, status: bool):
        """Enable or disable LLM"""
        await self.config.custom("LLM", str(guild.id)).LLMActive.set(status)

    async def _get_openai_key(self, guild: discord.Guild) -> str | None:
        """Get OpenAI API Key"""
        return await self.config.custom("LLM", str(guild.id)).OpenAIKey()

    async def _set_openai_key(self, guild: discord.Guild, key: str | None):
        """Set OpenAI API Key"""
        await self.config.custom("LLM", str(guild.id)).OpenAIKey.set(key)

    async def _get_openai_org(self, guild: discord.Guild) -> str | None:
        """Get OpenAI organization name"""
        return await self.config.custom("LLM", str(guild.id)).OpenAIOrg()

    async def _set_openai_org(self, guild: discord.Guild, org: str | None):
        """Set OpenAI organization name"""
        await self.config.custom("LLM", str(guild.id)).OpenAIOrg.set(org)

    async def _get_llm_similarity_count(self, guild: discord.Guild) -> int:
        """Get similarity count for LLM queries"""
        return await self.config.custom("LLM", str(guild.id)).SimilarityCount()

    async def _set_llm_similarity_count(self, guild: discord.Guild, count: int):
        """Set similarity count for LLM queries"""
        await self.config.custom("LLM", str(guild.id)).SimilarityCount.set(count)

    async def _get_llm_threshold(self, guild: discord.Guild) -> float:
        """Get similarity threshold for LLM queries"""
        return await self.config.custom("LLM", str(guild.id)).SimilarityThreshold()

    async def _set_llm_threshold(self, guild: discord.Guild, threshold: float):
        """Set similarity threshold for LLM queries"""
        await self.config.custom("LLM", str(guild.id)).SimilarityThreshold.set(threshold)

    async def _get_llm_channel_blacklist(self, guild: discord.Guild) -> list[int]:
        """Get channel blacklist for LLM responses"""
        blacklist = await self.config.custom("LLM", str(guild.id)).LLMBlacklist()
        if blacklist is None:
            return []
        return blacklist

    async def _set_llm_channel_blacklist(self, guild: discord.Guild, channels: list[discord.TextChannel]):
        """Set channel blacklist for LLM responses"""
        await self.config.custom("LLM", str(guild.id)).LLMBlacklist.set([c.id for c in channels])

    async def _add_llm_channel_blacklist(self, guild: discord.Guild, channel: discord.TextChannel):
        """Set channel blacklist for LLM responses"""
        blacklist: list[int] = await self._get_llm_channel_blacklist(guild)
        blacklist.append(channel.id)
        await self.config.custom("LLM", str(guild.id)).LLMBlacklist.set(blacklist)

    async def _rm_llm_channel_blacklist(self, guild: discord.Guild, channel: discord.TextChannel):
        """Set channel blacklist for LLM responses"""
        blacklist: list[int] = await self._get_llm_channel_blacklist(guild)
        blacklist.remove(channel.id)
        await self.config.custom("LLM", str(guild.id)).LLMBlacklist.set(blacklist)
