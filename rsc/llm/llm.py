from __future__ import annotations

import base64
import logging
from datetime import datetime

import discord
from redbot.core import app_commands, commands

from rsc.abc import RSCMixIn
from rsc.embeds import BetterEmbed, BlueEmbed, EmbedLimits, ErrorEmbed, GreenEmbed, SuccessEmbed, YellowEmbed
from rsc.llm.agent import AgentError, CooldownTracker, ToolCache, run_agent
from rsc.llm.agent.service import (
    build_agent_context,
    check_budget,
    record_usage,
    usage_today,
)
from rsc.llm.summarize import summarize_ticket_messages
from rsc.logs import GuildLogAdapter
from rsc.types import LLMSettings, LLMUsageRecord
from rsc.utils.pagify import Pagify

logger = logging.getLogger("red.rsc.llm")
log = GuildLogAdapter(logger)

defaults_guild = LLMSettings(
    LLMActive=False,
    LLMBlacklist=None,
    OpenAIKey=None,
    OpenAIOrg=None,
    LLMUserCooldown=20,
    LLMUserDailyCap=15,
    LLMGuildDailyCap=400,
    LLMPublicAsk=True,
)

defaults_usage = LLMUsageRecord(day=None, count=0, tokens=0)

LLM_SUMMARY_MAX_MESSAGES = 200
LLM_SUMMARY_HARD_CHANNEL_CAP = 300
LLM_SUMMARY_MAX_VIEWERS = 40
LLM_SUMMARY_MAX_TRANSCRIPT_CHARS = 20000
LLM_SUMMARY_MAX_IMAGES = 10
LLM_SUMMARY_MAX_IMAGE_BYTES = 20 * 1024 * 1024
LLM_QUERY_MAX_CONTINUATIONS = 5
LLM_MAX_MESSAGE_LENGTH = 2000


class LLMMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing LLMMixIn")
        self.config.init_custom("LLM", 1)
        self.config.register_custom("LLM", **defaults_guild)
        # Two identifiers: guild id, then user id (0 for the guild-wide total).
        self.config.init_custom("LLMUsage", 2)
        self.config.register_custom("LLMUsage", **defaults_usage)

        # Cooldowns live for seconds, so memory is the right store; the daily
        # caps in Config are what must survive a reload.
        self._llm_cooldown = CooldownTracker(seconds=defaults_guild["LLMUserCooldown"])
        self._llm_tool_cache = ToolCache()
        super().__init__()

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

        question = await self.clean_question(message)
        if not question:
            return

        try:
            # The agent makes several round trips, so this takes seconds rather
            # than returning instantly. Without the indicator it reads as
            # ignored. discord.py refreshes it past the 10s window.
            async with message.channel.typing():
                answer, _sources = await self.answer_with_agent(
                    guild,
                    message.author,
                    question,
                    surface="mention",
                )
        except PermissionError as exc:
            # A quiet signal. Replying invites a follow-up, which is exactly
            # what a rate limit is trying to avoid.
            await self._react_rate_limited(message, str(exc))
            return
        except AgentError as exc:
            log.warning(f"Agent could not answer: {exc}", guild=guild)
            await message.reply(content=str(exc))
            return

        # Response may exceed the discord message length limit
        pages = list(Pagify(text=str(answer), page_length=LLM_MAX_MESSAGE_LENGTH))
        if not pages:
            return

        await message.reply(content=pages[0])
        for page in pages[1:]:
            await message.channel.send(content=page)

    @staticmethod
    async def _react_rate_limited(message: discord.Message, reason: str) -> None:
        emoji = "\N{HOURGLASS WITH FLOWING SAND}" if reason == "cooldown" else "\N{NO ENTRY SIGN}"
        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            # Reacting is a courtesy; losing it is not worth logging loudly.
            log.debug("Could not add rate limit reaction.", guild=message.guild)

    # Public command

    @app_commands.command(name="ask", description="Ask a question about RSC rules, players, teams or schedules")
    @app_commands.describe(question="What do you want to know?")
    @app_commands.guild_only
    async def _llm_ask_cmd(self, interaction: discord.Interaction, question: str):
        """Open to everyone. Spend is controlled by cooldown and daily caps, not permissions."""
        guild = interaction.guild
        if not guild:
            return

        if not await self._get_llm_status(guild):
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="The RSC AI is not currently enabled."),
                ephemeral=True,
            )
        if not await self._get_llm_public_ask(guild):
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="`/ask` is disabled on this server."),
                ephemeral=True,
            )
        if interaction.channel_id in await self._get_llm_channel_blacklist(guild):
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="The RSC AI is not available in this channel."),
                ephemeral=True,
            )

        await interaction.response.defer()

        try:
            answer, sources = await self.answer_with_agent(guild, interaction.user, question, surface="slash")
        except PermissionError as exc:
            return await interaction.followup.send(embed=self._budget_embed(str(exc)), ephemeral=True)
        except AgentError as exc:
            return await interaction.followup.send(embed=ErrorEmbed(description=str(exc)), ephemeral=True)

        embeds = self._build_llm_query_embeds(
            question=question,
            response=answer,
            sources=sources,
            icon_url=guild.icon.url if guild.icon else None,
        )
        await interaction.followup.send(embed=embeds[0])
        for extra in embeds[1:]:
            await interaction.followup.send(embed=extra)

    def _budget_embed(self, reason: str) -> discord.Embed:
        """Explain a declined request without shaming the asker."""
        if reason == "cooldown":
            return YellowEmbed(
                title="Slow down",
                description="You have asked very recently. Give it a few seconds and try again.",
            )
        if reason == "user_cap":
            return YellowEmbed(
                title="Daily limit reached",
                description="You have used all of your AI questions for today. It resets tomorrow.",
            )
        return YellowEmbed(
            title="Daily limit reached",
            description="The server has used all of its AI questions for today. It resets tomorrow.",
        )

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
        cooldown = await self._get_llm_cooldown(guild)
        user_cap = await self._get_llm_user_daily_cap(guild)
        guild_cap = await self._get_llm_guild_daily_cap(guild)
        public_ask = await self._get_llm_public_ask(guild)

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
        settings_embed.add_field(name="/ask enabled", value=str(public_ask), inline=False)
        settings_embed.add_field(name="User Cooldown", value=f"{cooldown}s", inline=True)
        settings_embed.add_field(name="Daily Cap (user)", value=str(user_cap or "unlimited"), inline=True)
        settings_embed.add_field(name="Daily Cap (server)", value=str(guild_cap or "unlimited"), inline=True)
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

    @_llm_group.command(name="cooldown", description="Seconds a user must wait between AI questions")
    @app_commands.describe(seconds="Cooldown in seconds (0 disables)")
    async def _llm_cooldown_cmd(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 3600]):
        guild = interaction.guild
        if not guild:
            return

        await self._set_llm_cooldown(guild, seconds)
        self._llm_cooldown.seconds = seconds
        await interaction.response.send_message(
            embed=SuccessEmbed(description=f"AI cooldown set to **{seconds}** seconds."),
            ephemeral=True,
        )

    @_llm_group.command(name="dailycap", description="Daily AI question limits")
    @app_commands.describe(
        per_user="Questions per user per day (0 disables)",
        per_guild="Questions across the server per day (0 disables)",
    )
    async def _llm_dailycap_cmd(
        self,
        interaction: discord.Interaction,
        per_user: app_commands.Range[int, 0, 1000] | None = None,
        per_guild: app_commands.Range[int, 0, 100000] | None = None,
    ):
        guild = interaction.guild
        if not guild:
            return

        if per_user is not None:
            await self._set_llm_user_daily_cap(guild, per_user)
        if per_guild is not None:
            await self._set_llm_guild_daily_cap(guild, per_guild)

        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=(
                    f"Per user: **{await self._get_llm_user_daily_cap(guild)}**\n"
                    f"Per server: **{await self._get_llm_guild_daily_cap(guild)}**\n\n"
                    "Members with an elevated role are exempt from the per user cap."
                )
            ),
            ephemeral=True,
        )

    @_llm_group.command(name="usage", description="AI questions and tokens used today")
    @app_commands.describe(member="Show one member's usage instead of the server total")
    async def _llm_usage_cmd(self, interaction: discord.Interaction, member: discord.Member | None = None):
        guild = interaction.guild
        if not guild:
            return

        tz = await self.timezone(guild)
        now = datetime.now(tz)
        # User id 0 is the guild-wide bucket.
        scope_id = member.id if member else 0
        count, tokens = await usage_today(self, guild, scope_id, now)
        cap = await self._get_llm_user_daily_cap(guild) if member else await self._get_llm_guild_daily_cap(guild)

        embed = BlueEmbed(title="RSC AI Usage")
        embed.add_field(name="Scope", value=member.mention if member else guild.name, inline=True)
        embed.add_field(name="Date", value=now.strftime("%Y-%m-%d"), inline=True)
        embed.add_field(name="Questions", value=f"{count}" + (f" / {cap}" if cap else ""), inline=True)
        embed.add_field(name="Tokens", value=f"{tokens:,}", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

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

    async def clean_question(self, message: discord.Message) -> str:
        if not message.guild:
            return message.clean_content

        # Remove bot mention
        cleaned_msg = message.clean_content.replace(f"@{message.guild.me.display_name}", "").strip()
        log.debug(f"Original Question: {cleaned_msg}")

        log.debug(f"Question without bot mention: {cleaned_msg}")

        return cleaned_msg

    def _build_llm_query_embeds(
        self,
        question: str,
        response: str,
        sources: str | None = None,
        icon_url: str | None = None,
    ) -> list[BetterEmbed]:
        """Build the LLM query response embed(s), splitting long content as needed.

        A response too large for a single embed spills into continuation embeds.
        """
        embed = BlueEmbed(title="RSC AI")
        if icon_url:
            embed.set_thumbnail(url=icon_url)

        # Question is user input and only echoed back. Truncation is fine.
        if len(question) > EmbedLimits.Field.Value:
            question = question[: EmbedLimits.Field.Value - 1] + "…"
        embed.add_field(name="Question", value=question, inline=False)

        embeds: list[BetterEmbed] = [embed]
        leftover = embed.add_long_field(name="Response", value=response, inline=False)

        while leftover and len(embeds) <= LLM_QUERY_MAX_CONTINUATIONS:
            embed = BlueEmbed(title="RSC AI (continued)")
            embeds.append(embed)
            leftover = embed.add_long_field(name="Response (cont.)", value=leftover, inline=False)

        if leftover:
            log.warning(f"LLM response truncated after {len(embeds)} embeds. (Remaining: {len(leftover)})")
            embed.set_footer(text="Response was too long to display in full.")

        if sources:
            # Attach sources to the final embed so they follow the response
            embeds[-1].add_long_field(name="Sources", value=sources, inline=False)

        return embeds

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
                (
                    f"This channel appears to be broadly visible ({len(channel.members)} viewers). "
                    f"Ticket summaries are limited to <= {LLM_SUMMARY_MAX_VIEWERS} viewers."
                ),
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

    # Agent

    async def answer_with_agent(
        self,
        guild: discord.Guild,
        member: discord.Member | discord.User,
        question: str,
        *,
        surface: str,
    ) -> tuple[str, str | None]:
        """Answer a question with the tool-calling agent.

        Returns the answer and a sources line. Raises `AgentError` for failures
        the asker should be told about, and `PermissionError` when the spend
        controls decline the request.
        """
        org, key = await self.get_llm_credentials(guild)
        if not key:
            raise AgentError("The OpenAI API key is not configured for this server.")

        tz = await self.timezone(guild)
        now = datetime.now(tz)

        verdict = await check_budget(
            self,
            guild,
            member,
            cooldown=self._llm_cooldown,
            user_cap=await self._get_llm_user_daily_cap(guild),
            guild_cap=await self._get_llm_guild_daily_cap(guild),
            now=now,
        )
        if not verdict.allowed:
            raise PermissionError(verdict.reason)

        # Started before the call, so a slow answer does not let the same user
        # queue several more behind it.
        self._llm_cooldown.seconds = await self._get_llm_cooldown(guild)
        self._llm_cooldown.start(guild.id, member.id)

        ctx = await build_agent_context(
            self,
            guild,
            member,
            api_key=key,
            org=org,
            surface=surface,
            cache=self._llm_tool_cache,
            now=now,
        )

        try:
            result = await run_agent(ctx, question)
        except AgentError:
            # The question never completed, so it should not burn the asker's
            # cooldown.
            self._llm_cooldown.clear(guild.id, member.id)
            raise

        await record_usage(self, guild, member.id, tokens=ctx.usage.total, now=now)
        return (result.answer, self.format_agent_sources(result.tools_called, result.citations))

    @staticmethod
    def format_agent_sources(tools: list[str], citations: list[str]) -> str | None:
        """What the answer was based on: tools consulted and rules cited."""
        parts = []
        if citations:
            parts.append("Rules: " + ", ".join(citations[:6]))
        if tools:
            parts.append("Looked up: " + ", ".join(tools))
        return " | ".join(parts) or None

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

    async def _get_llm_cooldown(self, guild: discord.Guild) -> int:
        """Seconds a user must wait between questions"""
        return await self.config.custom("LLM", str(guild.id)).LLMUserCooldown()

    async def _set_llm_cooldown(self, guild: discord.Guild, seconds: int):
        await self.config.custom("LLM", str(guild.id)).LLMUserCooldown.set(seconds)

    async def _get_llm_user_daily_cap(self, guild: discord.Guild) -> int:
        """Questions per user per day. 0 disables the cap."""
        return await self.config.custom("LLM", str(guild.id)).LLMUserDailyCap()

    async def _set_llm_user_daily_cap(self, guild: discord.Guild, cap: int):
        await self.config.custom("LLM", str(guild.id)).LLMUserDailyCap.set(cap)

    async def _get_llm_guild_daily_cap(self, guild: discord.Guild) -> int:
        """Questions across the whole guild per day. 0 disables the cap."""
        return await self.config.custom("LLM", str(guild.id)).LLMGuildDailyCap()

    async def _set_llm_guild_daily_cap(self, guild: discord.Guild, cap: int):
        await self.config.custom("LLM", str(guild.id)).LLMGuildDailyCap.set(cap)

    async def _get_llm_public_ask(self, guild: discord.Guild) -> bool:
        """Whether /ask is available to everyone"""
        return await self.config.custom("LLM", str(guild.id)).LLMPublicAsk()

    async def _set_llm_public_ask(self, guild: discord.Guild, enabled: bool):
        await self.config.custom("LLM", str(guild.id)).LLMPublicAsk.set(enabled)

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
