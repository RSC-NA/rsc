import logging
from datetime import time, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import discord
from discord.ext import tasks
from redbot.core import app_commands, commands

from rsc.abc import RSCMixIn
from rsc.embeds import BlueEmbed, ErrorEmbed, GreenEmbed, YellowEmbed
from rsc.llm.create_db import (
    delete_documents_by_type,
    get_db_stats,
    load_current_season_doc,
    load_franchise_docs,
    load_funny_docs,
    load_help_docs,
    load_player_docs,
    load_rule_style_docs,
    load_match_docs,
    load_team_docs,
    markdown_to_documents,
    reset_collection,
    save_documents,
    string_to_doc,
)
from rsc.llm.query import llm_query, UserIdentity, clean_question as clean_question_impl
from rsc.logs import GuildLogAdapter
from rsc.types import LLMSettings
from rsc.utils import utils


class DocumentType(Enum):
    """Enum for LLM document types"""

    RULES = "rules"
    FRANCHISES = "franchises"
    PLAYERS = "players"
    MATCHES = "matches"
    TEAMS = "teams"
    SEASON = "season"


if TYPE_CHECKING:
    from langchain_core.documents import Document
    from rscapi.models.franchise_list import FranchiseList
    from rscapi.models.team import Team

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
        cleaned_msg = await self.clean_question(message, user_identity)

        try:
            response, _sources = await llm_query(
                guild=guild,
                org_name=org,
                api_key=key,
                question=cleaned_msg,
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
    @_llm_group.command(name="settings", description="Display LLM settings")  # type: ignore[type-var]
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

    @_llm_group.command(  # type: ignore[type-var]
        name="toggle", description="Toggle llm on or off"
    )
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

    @_llm_group.command(  # type: ignore[type-var]
        name="organization", description="Configure the OpenAI organization"
    )
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

    @_llm_group.command(  # type: ignore[type-var]
        name="apikey", description="Configure the OpenAI API key"
    )
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

    @_llm_group.command(  # type: ignore[type-var]
        name="count", description="Configure the LLM max similarity count"
    )
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

    @_llm_group.command(  # type: ignore[type-var]
        name="threshold", description="Configure the LLM threshold"
    )
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

    @_llm_group.command(name="query", description="Query the RSC LLM")  # type: ignore[type-var]
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

        # Clean pronouns from the question
        if user_identity:
            cleaned_question = clean_question_impl(question, user_identity.name, guild.me.display_name)
        else:
            # Fall back to display name if not a member
            display_name = getattr(member, "display_name", str(member))
            cleaned_question = clean_question_impl(question, display_name, guild.me.display_name)

        log.debug(f"Original question: {question}", guild=guild)
        log.debug(f"Cleaned question: {cleaned_question}", guild=guild)

        try:
            response, sources = await llm_query(
                guild=guild,
                org_name=org,
                api_key=key,
                question=cleaned_question,
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

    @_llm_group.command(  # type: ignore[type-var]
        name="createdb", description="Create the LLM Chroma DB"
    )
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

    @_llm_group.command(  # type: ignore[type-var]
        name="refresh", description="Refresh a specific document type in the LLM Chroma DB"
    )
    @app_commands.describe(doc_type="Type of documents to refresh")
    @app_commands.choices(
        doc_type=[
            app_commands.Choice(name="Rules/Help/Funny", value="rules"),
            app_commands.Choice(name="Franchises", value="franchises"),
            app_commands.Choice(name="Players", value="players"),
            app_commands.Choice(name="Matches", value="matches"),
            app_commands.Choice(name="Teams", value="teams"),
            app_commands.Choice(name="Season", value="season"),
        ]
    )
    async def _llm_refresh_cmd(self, interaction: discord.Interaction, doc_type: app_commands.Choice[str]):
        """Refresh a specific document type in the LLM Chroma DB"""
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
            document_type = DocumentType(doc_type.value)
            count = await self.refresh_document_type(guild, document_type, interaction=interaction)
        except ValueError as exc:
            return await interaction.followup.send(content=str(exc), ephemeral=True)

        await interaction.followup.send(
            embed=GreenEmbed(
                title="Documents Refreshed",
                description=f"Refreshed **{doc_type.name}** documents.\n\nSaved **{count}** chunks to Chroma DB.",
            ),
            ephemeral=True,
        )

    @_llm_group.command(  # type: ignore[type-var]
        name="resetdb", description="Reset the LLM Chroma DB (deletes all documents)"
    )
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

    @_llm_group.command(  # type: ignore[type-var]
        name="dbstats", description="Show LLM database statistics"
    )
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

    @_llm_blacklist_group.command(  # type: ignore[type-var]
        name="show", description="Display the LLM channel blacklist"
    )
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

    @_llm_blacklist_group.command(  # type: ignore[type-var]
        name="add", description="Add a channel to the LLM blacklist"
    )
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

    @_llm_blacklist_group.command(  # type: ignore[type-var]
        name="rm", description="Remove a channel from the LLM blacklist"
    )
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

        # ===== RULES & STATIC DOCUMENTS =====
        if interaction:
            await interaction.edit_original_response(
                embed=YellowEmbed(
                    title="Creating Chroma DB",
                    description="Loading markdown documents.",
                )
            )
        total_docs += await self._process_rules_documents(guild, org, key)

        # ===== CURRENT SEASON DOCUMENT =====
        if interaction:
            await interaction.edit_original_response(
                embed=YellowEmbed(
                    title="Creating Chroma DB",
                    description="Loading current season document.",
                )
            )
        total_docs += await self._process_current_season_document(guild, org, key)

        # ===== FRANCHISE DOCUMENTS =====
        if interaction:
            await interaction.edit_original_response(
                embed=YellowEmbed(
                    title="Creating Chroma DB",
                    description="Loading franchise documents.",
                )
            )
        total_docs += await self._process_franchise_documents(guild, org, key)

        # ===== PLAYER DOCUMENTS =====
        if interaction:
            await interaction.edit_original_response(
                embed=YellowEmbed(
                    title="Creating Chroma DB",
                    description="Loading player documents.",
                )
            )
        total_docs += await self._process_player_documents(guild, org, key)

        # ===== MATCH DOCUMENTS =====
        if interaction:
            await interaction.edit_original_response(
                embed=YellowEmbed(
                    title="Creating Chroma DB",
                    description="Loading match documents.",
                )
            )
        total_docs += await self._process_match_documents(guild, org, key, current_season.number)

        # ===== TEAM DOCUMENTS =====
        if interaction:
            await interaction.edit_original_response(
                embed=YellowEmbed(
                    title="Creating Chroma DB",
                    description="Loading team documents.",
                )
            )
        total_docs += await self._process_team_documents(guild, org, key)

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

    async def _process_current_season_document(self, guild: discord.Guild, org: str, key: str) -> int:
        """Process and save current season document."""
        log.info("Creating current season document.", guild=guild)
        season = await self.current_season(guild)
        season_doc = await load_current_season_doc(season)

        await save_documents(guild, org, key, [season_doc])
        log.info("Saved current season document.", guild=guild)
        return 1

    async def _process_rules_documents(self, guild: discord.Guild, org: str, key: str) -> int:
        """Process and save rules, help, and funny documents."""
        log.info("Creating rules/help/funny documents.", guild=guild)
        rule_docs: list[Document] = []

        # Dates document
        log.debug("Create dates document.", guild=guild)
        dates = await self._get_dates(guild)
        if dates:
            date_doc = await string_to_doc(dates)
            date_doc.metadata["type"] = DocumentType.RULES.value
            rule_docs.append(date_doc)

        # Rule documents
        log.debug("Creating rule documents.", guild=guild)
        rulepath = Path(__file__).parent.parent / "resources" / "rules"
        for fd in rulepath.glob("*.md"):
            log.debug(f"Rule Doc: {fd}", guild=guild)
            rdocs = await load_rule_style_docs(fd)
            for doc in rdocs:
                doc.metadata["type"] = DocumentType.RULES.value
            rule_docs.extend(rdocs)

        # Help documents
        log.debug("Creating help documents.", guild=guild)
        helpdocs = await load_help_docs()
        help_md_docs = await markdown_to_documents(helpdocs)
        for doc in help_md_docs:
            doc.metadata["type"] = DocumentType.RULES.value
        rule_docs.extend(help_md_docs)

        # Funny documents
        log.debug("Creating funny documents.", guild=guild)
        funnydocs = await load_funny_docs()
        funny_md_docs = await markdown_to_documents(funnydocs)
        for doc in funny_md_docs:
            doc.metadata["type"] = DocumentType.RULES.value
        rule_docs.extend(funny_md_docs)

        # Save rules/help/funny docs
        await save_documents(guild, org, key, rule_docs)
        log.info(f"Saved {len(rule_docs)} rules/help/funny documents.", guild=guild)
        return len(rule_docs)

    async def _process_franchise_documents(self, guild: discord.Guild, org: str, key: str, current_season: int | None = None) -> int:
        """Process and save franchise documents."""
        log.info("Creating franchise documents.", guild=guild)
        franchises: list[FranchiseList] = await self.franchises(guild)
        if not franchises:
            log.debug("No franchises found.", guild=guild)
            return 0

        standings = None
        if current_season:
            standings = await self.franchise_standings(guild, season_id=current_season)

        log.debug(f"Franchise Count: {len(franchises)}", guild=guild)
        franchise_docs = await load_franchise_docs(franchises, standings=standings)
        for doc in franchise_docs:
            doc.metadata["type"] = DocumentType.FRANCHISES.value
        await save_documents(guild, org, key, franchise_docs)
        log.info(f"Saved {len(franchise_docs)} franchise documents.", guild=guild)
        return len(franchise_docs)

    async def _process_player_documents(self, guild: discord.Guild, org: str, key: str) -> int:
        """Process and save player documents."""
        log.info("Creating player documents.", guild=guild)
        player_docs: list[Document] = []
        pcount = await self.total_players(guild)
        log.debug(f"Total Players: {pcount}", guild=guild)
        player_index = 0
        async for player in self.paged_players(guild):
            pdocs = await load_player_docs([player], chunk_index=player_index)
            for doc in pdocs:
                doc.metadata["type"] = DocumentType.PLAYERS.value
            player_docs.extend(pdocs)
            player_index += 1

        await save_documents(guild, org, key, player_docs)
        log.info(f"Saved {len(player_docs)} player documents.", guild=guild)
        return len(player_docs)

    async def _process_match_documents(self, guild: discord.Guild, org: str, key: str, season_number: int) -> int:
        """Process and save match documents."""
        log.info("Creating match documents.", guild=guild)
        match_docs: list[Document] = []
        match_index = 0

        # Create a match fetcher that captures the guild
        async def fetch_match(match_id: int):
            return await self.match_results(guild, match_id)

        async for match in self.paged_matches(guild, season_number=season_number):
            mdocs = await load_match_docs([match], chunk_index=match_index, match_fetcher=fetch_match)
            for doc in mdocs:
                doc.metadata["type"] = DocumentType.MATCHES.value
            match_docs.extend(mdocs)
            match_index += 1

        await save_documents(guild, org, key, match_docs)
        log.info(f"Saved {len(match_docs)} match documents.", guild=guild)
        return len(match_docs)

    async def _process_team_documents(self, guild: discord.Guild, org: str, key: str) -> int:
        """Process and save team documents."""
        log.info("Creating team documents.", guild=guild)
        franchises: list[FranchiseList] = await self.franchises(guild)
        teams: list[Team] = []
        for f in franchises:
            if not (f.id and f.teams):
                continue

            fdata = await self.franchise_by_id(guild, id=f.id)
            if not (fdata and fdata.teams):
                continue

            for t in fdata.teams:
                teams.append(t)  # noqa: PERF402

        if not teams:
            log.debug("No teams found.", guild=guild)
            return 0

        log.debug(f"Team Count: {len(teams)}", guild=guild)
        team_docs = await load_team_docs(teams)
        for doc in team_docs:
            doc.metadata["type"] = DocumentType.TEAMS.value
        await save_documents(guild, org, key, team_docs)
        log.info(f"Saved {len(team_docs)} team documents.", guild=guild)
        return len(team_docs)

    async def refresh_document_type(
        self,
        guild: discord.Guild,
        doc_type: DocumentType,
        interaction: discord.Interaction | None = None,
    ) -> int:
        """
        Refresh only a specific document type in the ChromaDB.

        Args:
            guild: Discord guild
            doc_type: Type of documents to refresh
            interaction: Optional interaction for progress updates

        Returns:
            Number of documents added
        """
        org, key = await self.get_llm_credentials(guild)
        if not (org and key):
            raise ValueError("OpenAI organization and or API key has not been configured.")

        current_season = await self.current_season(guild)
        if not current_season or not current_season.number:
            raise ValueError("Current season is not configured.")

        # Delete existing documents of this type
        if interaction:
            await interaction.edit_original_response(
                embed=YellowEmbed(
                    title="Refreshing Documents",
                    description=f"Deleting existing {doc_type.value} documents...",
                )
            )
        deleted = await delete_documents_by_type(guild, doc_type.value)
        log.info(f"Deleted {deleted} existing {doc_type.value} documents.", guild=guild)

        # Process and save new documents
        if interaction:
            await interaction.edit_original_response(
                embed=YellowEmbed(
                    title="Refreshing Documents",
                    description=f"Loading new {doc_type.value} documents...",
                )
            )

        match doc_type:
            case DocumentType.RULES:
                count = await self._process_rules_documents(guild, org, key)
            case DocumentType.FRANCHISES:
                count = await self._process_franchise_documents(guild, org, key, current_season.id)
            case DocumentType.PLAYERS:
                count = await self._process_player_documents(guild, org, key)
            case DocumentType.MATCHES:
                count = await self._process_match_documents(guild, org, key, current_season.number)
            case DocumentType.TEAMS:
                count = await self._process_team_documents(guild, org, key)
            case DocumentType.SEASON:
                count = await self._process_current_season_document(guild, org, key)

        return count

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

        # Get user name from identity or fall back to display name
        if user_identity:
            user_name = user_identity.name
        elif isinstance(message.author, discord.Member):
            user_name = await utils.remove_prefix(message.author)
        else:
            user_name = message.author.display_name

        bot_name = message.guild.me.display_name

        # Use the regex-based pronoun replacement
        cleaned_msg = clean_question_impl(cleaned_msg, user_name, bot_name)

        log.debug(f"Cleaned Question: {cleaned_msg}")

        return cleaned_msg

    async def format_llm_sources(self, sources: list[dict[str, str | None]]) -> str:
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
