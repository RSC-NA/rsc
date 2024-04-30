import logging
from pathlib import Path

import discord
from langchain_core.documents import Document
from redbot.core import app_commands, commands

from rsc.abc import RSCMixIn
from rsc.embeds import BlueEmbed, ErrorEmbed
from rsc.llm.create_db import (
    create_chroma_db,
    load_help_docs,
    load_rule_docs,
    markdown_to_documents,
)
from rsc.llm.query import llm_query
from rsc.logs import GuildLogAdapter
from rsc.types import LLMSettings

logger = logging.getLogger("red.rsc.llm")
log = GuildLogAdapter(logger)

defaults_guild = LLMSettings(
    LLMActive=False,
    OpenAIKey=None,
    OpenAIOrg=None,
    SimilarityCount=5,
    SimilarityThreshold=0.65,
)


class LLMMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing LLMMixIn")
        self.config.init_custom("LLM", 1)
        self.config.register_custom("LLM", **defaults_guild)
        super().__init__()

    # Listener

    @commands.Cog.listener("on_message")
    async def llm_replay_to_mention(self, message: discord.Message):
        guild = message.guild
        if not guild:
            return

        # Replay to mention only
        if not guild.me.mentioned_in(message):
            return

        # Check if LLM active
        if not await self._get_llm_status(guild):
            return

        # Settings
        count, threshold = await self.get_llm_default(guild)
        org, key = await self.get_llm_credentials(guild)
        if not (org and key):
            log.warning(
                "OpenAI Organization and or API key is not configured.", guild=guild
            )
            return

        # Remove bot mention
        cleaned_msg = message.content.replace(guild.me.mention, "")
        log.debug(f"Cleaned LLM Message: {cleaned_msg}")

        try:
            response, _sources = await llm_query(
                org_name=org,
                api_key=key,
                question=cleaned_msg,
                count=count,
                threshold=threshold,
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
        description="Display settings for LLM",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # Group commands

    # Settings
    @_llm_group.command(name="settings", description="Display LLM settings")  # type: ignore
    async def _llm_settings_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        active = await self._get_llm_status(guild)
        openai_key = await self._get_openai_key(guild)
        openai_org = await self._get_openai_org(guild)
        llm_threshold = await self._get_llm_threshold(guild)
        llm_count = await self._get_llm_similarity_count(guild)

        settings_embed = BlueEmbed(
            title="LLM Settings",
            description="Displaying configured settings for RSC LLM",
        )
        settings_embed.add_field(name="Enabled", value=str(active), inline=False)
        settings_embed.add_field(
            name="OpenAI Organization", value=openai_org, inline=False
        )
        settings_embed.add_field(
            name="OpenAI API Key",
            value="Configured" if openai_key else "Not Configured",
            inline=False,
        )
        settings_embed.add_field(
            name="Similarity Count", value=str(llm_count), inline=False
        )
        settings_embed.add_field(
            name="Similarity Threshold", value=str(llm_threshold), inline=False
        )

        await interaction.response.send_message(embed=settings_embed, ephemeral=True)

    @_llm_group.command(  # type: ignore
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

    @_llm_group.command(  # type: ignore
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

    @_llm_group.command(  # type: ignore
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

    @_llm_group.command(  # type: ignore
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

    @_llm_group.command(  # type: ignore
        name="threshold", description="Configure the LLM threshold"
    )
    @app_commands.describe(
        threshold="Float threshold for finding similarities (Default: 0.65)"
    )
    async def _llm_threshold_cmd(
        self, interaction: discord.Interaction, threshold: float
    ):
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

    @_llm_group.command(name="query", description="Query the RSC LLM")  # type: ignore
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
                embed=ErrorEmbed(
                    description="OpenAI organization and or API key has not been configured."
                ),
                ephemeral=True,
            )

        await interaction.response.defer()
        try:
            response, _sources = await llm_query(
                org_name=org,
                api_key=key,
                question=question,
                count=count,
                threshold=threshold,
            )
        except RuntimeError as exc:
            return await interaction.followup.send(content=str(exc), ephemeral=True)

        if not response:
            response_fmt = "I am unable to answer that question."
            # source_fmt = None
        else:
            response_fmt = str(response)
            # source_fmt = await self.format_llm_sources(sources)

        embed = BlueEmbed(title="RSC AI")
        embed.add_field(name="Question", value=question, inline=False)
        embed.add_field(name="Response", value=response_fmt, inline=False)
        # embed.add_field(name="Sources", value=source_fmt, inline=False)

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        await interaction.followup.send(embed=embed)

    @_llm_group.command(  # type: ignore
        name="createdb", description="Create the LLM Chroma DB"
    )
    async def _llm_createdb_cmd(self, interaction: discord.Interaction):
        """Query the RSC LLM with a question"""
        guild = interaction.guild
        if not guild:
            return

        # Settings
        org, key = await self.get_llm_credentials(guild)
        if not (org and key):
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="OpenAI organization and or API key has not been configured."
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        try:
            await self.create_chroma_db(guild)
        except ValueError as exc:
            return await interaction.followup.send(content=str(exc), ephemeral=True)

        await interaction.followup.send(
            embed=BlueEmbed(
                title="Chroma DB", description="Chroma DB has been successfully created"
            ),
            ephemeral=True,
        )

    # Helpers

    async def create_chroma_db(self, guild: discord.Guild):
        org, key = await self.get_llm_credentials(guild)
        if not (org and key):
            raise ValueError(
                "OpenAI organization and or API key has not been configured."
            )

        # Store
        docs: list[Document] = []

        # Read in Markdown documents
        ruledocs = await load_rule_docs()
        helpdocs = await load_help_docs()

        for d in ruledocs:
            print(f"Loaded Document: {d.metadata}")
        for d in helpdocs:
            print(f"Loaded Document: {d.metadata}")

        markdown_docs = await markdown_to_documents(ruledocs)
        docs.extend(markdown_docs)
        markdown_docs = await markdown_to_documents(helpdocs)
        docs.extend(markdown_docs)

        await create_chroma_db(org_name=org, api_key=key, docs=docs)
        log.info("Chroma database created")

    async def format_llm_sources(self, sources: list[str]) -> str:
        result = []
        for s in sources:
            n = Path(s).name
            if n not in result:
                result.append(n)
        return "\n".join([f"- {r}" for r in result])

    async def get_llm_credentials(
        self, guild: discord.Guild
    ) -> tuple[str | None, str | None]:
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
        await self.config.custom("LLM", str(guild.id)).SimilarityThreshold.set(
            threshold
        )
