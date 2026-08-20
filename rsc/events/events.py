import asyncio
import logging
import random
import time
from collections.abc import Sequence
from datetime import UTC, datetime

import discord
from discord.ext import tasks
from redbot.core import app_commands
from rscapi import IntegrationsApi
from rscapi.exceptions import ApiException

from rsc.abc import RSCMixIn
from rsc.checks import bot_owner_required
from rsc.const import API_TIMEOUT
from rsc.embeds import ApiExceptionErrorEmbed, BlueEmbed, EmbedLimits, ErrorEmbed, SuccessEmbed
from rsc.enums import EventAction, EventCategory
from rsc.events.formatters import (
    backlog_summary_embed,
    build_event_embed,
    recovered_embed,
    unhealthy_embed,
)
from rsc.events.handlers import EVENT_HANDLERS
from rsc.events.models import (
    EVENT_LOOP_TICK,
    FAILURE_ALERT_THRESHOLD,
    MAX_BACKLOG,
    MAX_BACKOFF,
    MAX_EMBEDS_PER_MESSAGE,
    MAX_EVENTS_PER_TICK,
    MAX_WINDOW_LIMIT,
    SUPPRESSED_ACTIONS,
    EventPage,
    EventPollState,
    LeagueEventData,
    plan_batch,
)
from rsc.events.views import ConfirmCursorView, EventFilterView
from rsc.exceptions import RscException
from rsc.logs import GuildLogAdapter
from rsc.settings import RSCSettingsMixIn
from rsc.types import EventSettings

logger = logging.getLogger("red.rsc.events")
log = GuildLogAdapter(logger)

MIN_INTERVAL = 30
MAX_INTERVAL = 3600
SEND_PACING_DELAY = 1.0

EventChannel = discord.TextChannel | discord.Thread

defaults_guild = EventSettings(
    EventsEnabled=False,
    EventChannel=None,
    EventInterval=60,
    ConfirmedId=0,
    ConfirmedCreatedAt=None,
    SeenIds=[],
    CategoryFilter=[],
    ActionFilter=[],
    SeverityFilter=[],
    IncludePrivate=False,
    IncludeGlobal=False,
    TotalProcessed=0,
)


class PermanentSendError(Exception):
    """The log channel is unusable and retrying will not help."""


class EventMixIn(RSCMixIn):
    """Polls the RSC API `/integrations/events/` feed and mirrors it into Discord.

    Each processed event is also re-broadcast as a `rsc_league_event` bot event
    carrying a `LeagueEventData`, so other features can react without touching
    the poller. Register side effects in `EVENT_HANDLERS`.
    """

    def __init__(self):
        log.debug("Initializing EventMixIn")
        self.config.init_custom("Events", 1)
        self.config.register_custom("Events", **defaults_guild)
        self._event_state: dict[int, EventPollState] = {}
        super().__init__()

        if not self.rsc_events_loop.is_running():
            self.rsc_events_loop.start()

    # Tasks

    @tasks.loop(seconds=EVENT_LOOP_TICK)
    async def rsc_events_loop(self):
        """Base tick. Each guild polls on its own configured interval."""
        for guild in list(self.bot.guilds):
            state = self._event_state.setdefault(guild.id, EventPollState())
            now = time.monotonic()
            if now < state.next_due or now < state.next_retry:
                continue

            try:
                await self.poll_league_events(guild, state)
            except Exception as exc:
                # tasks.Loop only tolerates a handful of network errors before it
                # stops permanently, and ApiException/RscException/ValidationError
                # are not among them. Contain every failure to the guild it came
                # from so one bad guild cannot kill the loop.
                await self._record_failure(guild, state, exc)
            finally:
                interval = await self._get_event_interval(guild)
                state.next_due = time.monotonic() + interval

    @rsc_events_loop.before_loop
    async def before_rsc_events_loop(self):
        await self.bot.wait_until_ready()
        # Stagger guilds so a reload does not fire every unbounded fetch at once.
        for guild in list(self.bot.guilds):
            interval = await self._get_event_interval(guild)
            state = self._event_state.setdefault(guild.id, EventPollState())
            state.next_due = time.monotonic() + random.uniform(0, interval)  # noqa: S311

    @rsc_events_loop.error
    async def rsc_events_loop_error(self, exc: BaseException):
        """Backstop. A loop that raises out of `_loop` never restarts on its own."""
        logger.error("League event loop crashed. Restarting.", exc_info=exc)
        self.rsc_events_loop.restart()

    # Poller

    async def poll_league_events(self, guild: discord.Guild, state: EventPollState):
        """Fetch, process, and persist one poll for a single guild."""
        if not await self._get_events_enabled(guild):
            return
        # Both are plain dicts only populated on successful setup.
        if not (self._api_conf.get(guild.id) and self._league.get(guild.id)):
            return

        state.last_poll = datetime.now(UTC)
        settings = await self.config.custom("Events", str(guild.id)).all()

        confirmed_id: int = settings["ConfirmedId"]
        confirmed_at = self._parse_dt(settings["ConfirmedCreatedAt"])

        if not confirmed_id and confirmed_at is None:
            await self._bootstrap_cursor(guild)
            state.consecutive_failures = 0
            state.last_success = datetime.now(UTC)
            return

        seen_ids = set(settings["SeenIds"])

        # The window starts at the lagged watermark, so its oldest entries are
        # the ids already handled and awaiting confirmation. Ask for enough rows
        # to clear those and still surface a full batch of new ones.
        limit = min(len(seen_ids) + MAX_EVENTS_PER_TICK, MAX_WINDOW_LIMIT)

        page = await self.fetch_league_events(
            guild,
            id__gt=confirmed_id,
            limit=limit,
            include_private=settings["IncludePrivate"],
            include_global=settings["IncludeGlobal"],
        )

        if page.count > MAX_BACKLOG:
            await self._skip_backlog(guild, state, page.count, settings)
            return

        plan = plan_batch(
            page.events,
            confirmed_id=confirmed_id,
            seen_ids=seen_ids,
            watermark_history=state.watermark_history,
            now=time.monotonic(),
            max_events=MAX_EVENTS_PER_TICK,
        )
        state.watermark_history = plan.watermark_history

        processed = 0
        for event in plan.to_process:
            # Dispatch is unconditional and fire-and-forget. Filters are display only.
            self.bot.dispatch("rsc_league_event", guild, event)
            await self._run_handler(guild, event)
            processed += 1

        embeds = [build_event_embed(e) for e in plan.to_process if EventMixIn._passes_filter(e, settings)]
        if embeds:
            await self._try_post_embeds(guild, embeds)

        # One write per tick, and only when something actually moved. Red's JSON
        # driver rewrites the whole cog file per set(), so an idle guild polling
        # every 60s must not keep rewriting it.
        #
        # Note this persists AFTER the whole batch, so a crash or cog reload
        # partway through re-runs every handler in the batch on restart. Handlers
        # are expected to be idempotent for that reason - see the AnnouncedTrades
        # dedup in rsc.transactions.trade_announce.
        if plan.confirmed_id != confirmed_id or set(settings["SeenIds"]) != plan.seen_ids or processed:
            await self._persist_poll(guild, plan, processed, confirmed_at)

        state.processed_since_start += processed
        state.consecutive_failures = 0
        state.last_error = None
        state.last_success = datetime.now(UTC)

        if state.alerted:
            state.alerted = False
            await self._try_post_embeds(guild, [recovered_embed()])

        if plan.remaining:
            log.debug("%d events remain queued for next tick", plan.remaining, guild=guild)

    async def _skip_backlog(self, guild: discord.Guild, state: EventPollState, count: int, settings: dict):
        """Jump the cursor past an oversized backlog instead of draining it.

        Deliberately lossy, and the same decision bootstrap makes: posting
        hundreds of embeds would rate limit the channel for an hour and bury
        anything useful. The events remain retrievable via `/rsc events replay`.
        """
        low = settings["ConfirmedId"]
        newest = await self.newest_league_event(
            guild,
            include_private=settings["IncludePrivate"],
            include_global=settings["IncludeGlobal"],
        )
        if newest is None:
            # count said there was a backlog, so an empty feed means the window
            # moved underneath us. Leave the cursor alone and retry next tick.
            log.warning("Backlog of %d reported but the feed is empty. Skipping.", count, guild=guild)
            return

        log.warning(
            "Oversized league event backlog (%d). Skipping to id %d without posting individually.",
            count,
            newest.id,
            guild=guild,
        )

        conf = self.config.custom("Events", str(guild.id))
        await conf.ConfirmedId.set(newest.id)
        await conf.SeenIds.set([])
        if newest.created_at:
            await conf.ConfirmedCreatedAt.set(newest.created_at.isoformat())
        state.watermark_history.clear()

        await self._try_post_embeds(guild, [backlog_summary_embed(count, low, newest.id)])

        state.consecutive_failures = 0
        state.last_error = None
        state.last_success = datetime.now(UTC)

    async def _bootstrap_cursor(self, guild: discord.Guild):
        """Seed a fresh cursor from the newest event without processing anything.

        A single `ordering=-id&limit=1` lookup, so it costs the same whether the
        feed holds ten events or a million.
        """
        newest = await self.newest_league_event(
            guild,
            include_private=await self._get_include_private(guild),
            include_global=await self._get_include_global(guild),
        )
        conf = self.config.custom("Events", str(guild.id))
        await conf.ConfirmedId.set(newest.id if newest else 0)
        # Recorded even on an empty feed, so bootstrap does not run again.
        await conf.ConfirmedCreatedAt.set((newest.created_at or datetime.now(UTC)).isoformat() if newest else datetime.now(UTC).isoformat())
        await conf.SeenIds.set([])
        log.info(
            "Bootstrapped league event cursor at id %d (skipped backlog)",
            newest.id if newest else 0,
            guild=guild,
        )

    async def _persist_poll(
        self,
        guild: discord.Guild,
        plan,  # noqa: ANN001 - BatchPlan
        processed: int,
        previous_confirmed_at: datetime | None,
    ):
        conf = self.config.custom("Events", str(guild.id))
        await conf.ConfirmedId.set(plan.confirmed_id)
        await conf.SeenIds.set(sorted(plan.seen_ids))

        newest_at = max((e.created_at for e in plan.to_process if e.created_at), default=None)
        if newest_at and (previous_confirmed_at is None or newest_at > previous_confirmed_at):
            await conf.ConfirmedCreatedAt.set(newest_at.isoformat())

        if processed:
            total = await conf.TotalProcessed()
            await conf.TotalProcessed.set(total + processed)

    async def _run_handler(self, guild: discord.Guild, event: LeagueEventData):
        action = event.event_action
        handler = EVENT_HANDLERS.get(action) if action else None
        if handler is None:
            return
        try:
            await handler(self, guild, event)
        except Exception as exc:
            # A handler must never block the cursor or the rest of the batch.
            log.exception("Handler for %s failed on event %d", event.action, event.id, exc_info=exc, guild=guild)

    async def _record_failure(self, guild: discord.Guild, state: EventPollState, exc: BaseException):
        state.consecutive_failures += 1
        state.last_error = f"{type(exc).__name__}: {exc}"
        state.next_retry = time.monotonic() + min(
            EVENT_LOOP_TICK * (2**state.consecutive_failures),
            MAX_BACKOFF,
        )
        log.warning(
            "League event poll failed (%d consecutive): %s",
            state.consecutive_failures,
            state.last_error,
            guild=guild,
        )

        if state.consecutive_failures >= FAILURE_ALERT_THRESHOLD and not state.alerted:
            state.alerted = True
            try:
                await self._post_embeds(guild, [unhealthy_embed(state.consecutive_failures, state.last_error)])
            except Exception as send_exc:
                # Never let a failed health alert replace the failure it reports.
                log.warning("Could not post unhealthy alert: %s", send_exc, guild=guild)

    @staticmethod
    def _passes_filter(event: LeagueEventData, settings: dict) -> bool:
        """Client side only. Never push these to the API.

        `category`/`action` accept a single value server side, and filtering
        there means the highest visible id never reaches the true max, stalling
        the watermark behind every excluded event.
        """
        if event.event_action in SUPPRESSED_ACTIONS:
            return False

        categories: list[str] = settings.get("CategoryFilter") or []
        actions: list[str] = settings.get("ActionFilter") or []
        severities: list[str] = settings.get("SeverityFilter") or []

        if categories and event.category not in categories:
            return False
        if actions and event.action not in actions:
            return False
        # An event with no severity is only excluded by an explicit filter, never
        # by omission, so older events keep flowing if the field is ever dropped.
        return not (severities and event.severity is not None and event.severity not in severities)

    # Discord output

    async def _post_embeds(self, guild: discord.Guild, embeds: Sequence[discord.Embed]):
        """Send embeds to the log channel, batched to stay inside rate limits.

        Does nothing when no channel is configured, which is the documented
        "not set up yet" behaviour.

        Failure handling is split deliberately. A transient error propagates so
        the caller leaves the cursor alone and retries next tick. A permanent one
        (missing perms, channel deleted) clears the channel configuration and
        raises `PermanentSendError`, which the caller swallows so the cursor
        still advances instead of wedging forever.
        """
        channel = await self._get_event_channel(guild)
        if not channel:
            return

        chunks = self._chunk_embeds(embeds)
        for idx, chunk in enumerate(chunks):
            try:
                await channel.send(
                    embeds=chunk,
                    # payload is untrusted API JSON. Never let it ping anyone.
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.Forbidden:
                log.error("Missing permissions in event log channel. Clearing configuration.", guild=guild)
                await self._set_event_channel(guild, None)
                raise PermanentSendError("Missing permissions in event log channel") from None
            except discord.NotFound:
                log.error("Event log channel no longer exists. Clearing configuration.", guild=guild)
                await self._set_event_channel(guild, None)
                raise PermanentSendError("Event log channel no longer exists") from None

            # Pace multi-message batches. The per channel send bucket is roughly
            # 5 requests / 5 seconds. Nothing to wait for after the last one.
            if idx < len(chunks) - 1:
                await asyncio.sleep(SEND_PACING_DELAY)

    async def _try_post_embeds(self, guild: discord.Guild, embeds: Sequence[discord.Embed]):
        """`_post_embeds` but permanent failures do not stop the cursor."""
        try:
            await self._post_embeds(guild, embeds)
        except PermanentSendError as exc:
            log.warning("Dropped %d event embed(s): %s", len(embeds), exc, guild=guild)

    @staticmethod
    def _chunk_embeds(embeds: Sequence[discord.Embed]) -> list[list[discord.Embed]]:
        """Pack embeds into messages within Discord's 10 embed / 6000 char caps."""
        chunks: list[list[discord.Embed]] = []
        current: list[discord.Embed] = []
        current_len = 0

        for embed in embeds:
            size = len(embed)
            if current and (len(current) >= MAX_EMBEDS_PER_MESSAGE or current_len + size > EmbedLimits.Total):
                chunks.append(current)
                current, current_len = [], 0
            current.append(embed)
            current_len += size

        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    # Group

    _rsc_events = app_commands.Group(
        name="events",
        description="RSC API league event integration",
        parent=RSCSettingsMixIn.rsc_settings,
        guild_only=True,
    )

    @_rsc_events.command(name="settings", description="Display the current league event integration settings.")
    async def _rsc_events_settings(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        settings = await self.config.custom("Events", str(guild.id)).all()
        channel = await self._get_event_channel(guild)

        embed = BlueEmbed(
            title="League Event Settings",
            description="Configuration for the RSC API league event poller.",
        )
        embed.add_field(name="Enabled", value=str(settings["EventsEnabled"]), inline=True)
        embed.add_field(name="Interval", value=f"{settings['EventInterval']}s", inline=True)
        embed.add_field(name="Include Private", value=str(settings["IncludePrivate"]), inline=True)
        embed.add_field(name="Include Global", value=str(settings["IncludeGlobal"]), inline=True)
        embed.add_field(name="Log Channel", value=channel.mention if channel else "None", inline=False)
        embed.add_field(name="Categories", value=EventFilterView.summary(settings["CategoryFilter"]), inline=False)
        embed.add_field(name="Actions", value=EventFilterView.summary(settings["ActionFilter"]), inline=False)
        embed.add_field(name="Severities", value=EventFilterView.summary(settings["SeverityFilter"]), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_rsc_events.command(name="status", description="Display league event poller health and cursor position.")
    async def _rsc_events_status(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        settings = await self.config.custom("Events", str(guild.id)).all()
        state = self._event_state.get(guild.id)

        embed = BlueEmbed(title="League Event Poller Status")
        embed.add_field(name="Loop Running", value=str(self.rsc_events_loop.is_running()), inline=True)
        embed.add_field(name="Enabled", value=str(settings["EventsEnabled"]), inline=True)
        embed.add_field(name="Confirmed Event ID", value=str(settings["ConfirmedId"]), inline=True)

        confirmed_at = self._parse_dt(settings["ConfirmedCreatedAt"])
        embed.add_field(
            name="Latest Event Time",
            value=discord.utils.format_dt(confirmed_at, style="R") if confirmed_at else "Never",
            inline=True,
        )
        embed.add_field(name="Pending Dedup IDs", value=str(len(settings["SeenIds"])), inline=True)
        embed.add_field(name="Lifetime Processed", value=str(settings["TotalProcessed"]), inline=True)

        if state:
            embed.add_field(
                name="Last Poll",
                value=discord.utils.format_dt(state.last_poll, style="R") if state.last_poll else "Never",
                inline=True,
            )
            embed.add_field(
                name="Last Success",
                value=discord.utils.format_dt(state.last_success, style="R") if state.last_success else "Never",
                inline=True,
            )
            embed.add_field(name="Consecutive Failures", value=str(state.consecutive_failures), inline=True)
            embed.add_field(name="Processed Since Start", value=str(state.processed_since_start), inline=True)
            if state.last_error:
                embed.add_field(name="Last Error", value=f"```{state.last_error[:1000]}```", inline=False)
        else:
            embed.add_field(name="Runtime State", value="Not yet polled", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_rsc_events.command(name="replay", description="Re-render a single league event. Does not move the cursor.")
    @app_commands.describe(
        id="Event ID to fetch from the API",
        post="Send to the configured event log channel instead of replying privately",
    )
    async def _rsc_events_replay(self, interaction: discord.Interaction, id: int, post: bool = False):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)
        try:
            event = await self.league_event(guild, id)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        if not event:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"Event **{id}** could not be parsed."),
                ephemeral=True,
            )

        embed = build_event_embed(event)
        if not post:
            return await interaction.followup.send(embed=embed, ephemeral=True)

        channel = await self._get_event_channel(guild)
        if not channel:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="No event log channel is configured."),
                ephemeral=True,
            )

        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"Unable to post to {channel.mention}: {exc}"),
                ephemeral=True,
            )

        return await interaction.followup.send(
            embed=SuccessEmbed(description=f"Event **{id}** posted to {channel.mention}"),
            ephemeral=True,
        )

    @_rsc_events.command(name="toggle", description="Toggle the league event poller on or off.")
    @bot_owner_required()
    async def _rsc_events_toggle(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        status = await self._get_events_enabled(guild)
        status ^= True
        await self.config.custom("Events", str(guild.id)).EventsEnabled.set(status)
        result = "**enabled**" if status else "**disabled**"
        await interaction.response.send_message(
            embed=SuccessEmbed(description=f"League event polling has been {result}."),
            ephemeral=True,
        )

    @_rsc_events.command(name="channel", description="Set the channel league events are logged to.")
    @app_commands.describe(channel="Text channel or thread to post league events in")
    @bot_owner_required()
    async def _rsc_events_channel(self, interaction: discord.Interaction, channel: EventChannel):
        guild = interaction.guild
        if not guild:
            return

        await self._set_event_channel(guild, channel)

        embed = SuccessEmbed(description=f"League event log channel set to {channel.mention}")
        perms = channel.permissions_for(guild.me)
        missing = [name for name, ok in (("Send Messages", perms.send_messages), ("Embed Links", perms.embed_links)) if not ok]
        if missing:
            embed.add_field(name="\N{WARNING SIGN} Missing Permissions", value=", ".join(missing), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_rsc_events.command(name="interval", description="Set how often the league event poller runs.")
    @app_commands.describe(seconds=f"Poll interval in seconds ({MIN_INTERVAL}-{MAX_INTERVAL})")
    @bot_owner_required()
    async def _rsc_events_interval(
        self,
        interaction: discord.Interaction,
        seconds: app_commands.Range[int, MIN_INTERVAL, MAX_INTERVAL],
    ):
        guild = interaction.guild
        if not guild:
            return

        await self.config.custom("Events", str(guild.id)).EventInterval.set(seconds)
        if state := self._event_state.get(guild.id):
            state.next_due = time.monotonic() + seconds

        await interaction.response.send_message(
            embed=SuccessEmbed(description=f"League event poll interval set to **{seconds}** seconds."),
            ephemeral=True,
        )

    @_rsc_events.command(name="private", description="Toggle logging of non-public league events.")
    @bot_owner_required()
    async def _rsc_events_private(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        status = await self._get_include_private(guild)
        status ^= True
        await self.config.custom("Events", str(guild.id)).IncludePrivate.set(status)
        result = "**included**" if status else "**excluded**"
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=(
                    f"Private league events are now {result}.\n\n"
                    "Note this only has an effect if the configured API key has admin privileges."
                )
            ),
            ephemeral=True,
        )

    @_rsc_events.command(name="global", description="Toggle logging of league events not scoped to any league.")
    @bot_owner_required()
    async def _rsc_events_global(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        status = await self._get_include_global(guild)
        status ^= True
        await self.config.custom("Events", str(guild.id)).IncludeGlobal.set(status)
        result = "**included**" if status else "**excluded**"
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=(
                    f"Global league events are now {result}.\n\n"
                    "Global events have no league, for example a failure in the nightly MMR pull. "
                    "They are only visible to a superuser API key, and every guild with this "
                    "enabled will log its own copy of them."
                )
            ),
            ephemeral=True,
        )

    @_rsc_events.command(name="cursor", description="Manually move the league event cursor.")
    @app_commands.describe(id="Event ID to resume from. Events at or below this are treated as processed.")
    @bot_owner_required()
    async def _rsc_events_cursor(self, interaction: discord.Interaction, id: app_commands.Range[int, 0, None]):
        guild = interaction.guild
        if not guild:
            return

        current = await self.config.custom("Events", str(guild.id)).ConfirmedId()

        view = ConfirmCursorView(interaction=interaction, current=current, target=id)
        await view.prompt()
        await view.wait()

        if not view.result:
            return

        conf = self.config.custom("Events", str(guild.id))
        await conf.ConfirmedId.set(id)
        await conf.SeenIds.set([])
        await conf.ConfirmedCreatedAt.set(datetime.now(UTC).isoformat())
        if state := self._event_state.get(guild.id):
            state.watermark_history.clear()

        await interaction.edit_original_response(
            embed=SuccessEmbed(description=f"League event cursor set to **{id}**."),
            view=None,
        )

    @_rsc_events.command(name="filter", description="Choose which league events are posted to the log channel.")
    @bot_owner_required()
    async def _rsc_events_filter(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        settings = await self.config.custom("Events", str(guild.id)).all()

        async def save(categories: list[str], actions: list[str], severities: list[str]):
            conf = self.config.custom("Events", str(guild.id))
            await conf.CategoryFilter.set(categories)
            await conf.ActionFilter.set(actions)
            await conf.SeverityFilter.set(severities)

        view = EventFilterView(
            interaction=interaction,
            categories=settings["CategoryFilter"],
            actions=settings["ActionFilter"],
            severities=settings["SeverityFilter"],
            on_save=save,
        )
        await view.prompt()

    # Config

    async def _get_events_enabled(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Events", str(guild.id)).EventsEnabled()

    async def _get_event_interval(self, guild: discord.Guild) -> int:
        return await self.config.custom("Events", str(guild.id)).EventInterval()

    async def _get_include_private(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Events", str(guild.id)).IncludePrivate()

    async def _get_include_global(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Events", str(guild.id)).IncludeGlobal()

    async def _get_event_channel(self, guild: discord.Guild) -> EventChannel | None:
        cid = await self.config.custom("Events", str(guild.id)).EventChannel()
        if not cid:
            return None
        channel = guild.get_channel_or_thread(cid)
        if not isinstance(channel, discord.TextChannel | discord.Thread):
            return None
        return channel

    async def _set_event_channel(self, guild: discord.Guild, channel: EventChannel | None):
        await self.config.custom("Events", str(guild.id)).EventChannel.set(channel.id if channel else None)

    # API

    async def fetch_league_events(
        self,
        guild: discord.Guild,
        *,
        id__gt: int,
        limit: int,
        include_private: bool = False,
        include_global: bool = False,
    ) -> EventPage:
        """Fetch the oldest slice of unprocessed events, in ascending id order.

        One request. `ordering=id` plus an `id__gt` cursor makes this drift-free
        by construction: new events always append past the end of the window, so
        unlike offset paging over a newest-first list there is nothing that can
        shift a row out of the page before it is read.

        `count` on the envelope is the size of the whole backlog above the
        cursor, not of this slice, so an oversized backlog is detectable without
        downloading it.

        `is_public` is passed explicitly rather than omitted. Server side
        visibility depends on the API key's privilege level, so leaving it off
        would make the visible id set change if the key were ever upgraded or
        downgraded, shifting ids underneath the cursor.

        Deliberately does NOT narrow by `category`/`action`/`severity`, even
        though the API now supports `__in` for each. Those are display filters:
        every event is dispatched internally regardless of what gets posted to
        Discord, so the poller has to see all of them.
        """
        return await self._request_events(
            guild,
            ordering="id",
            id__gt=id__gt,
            limit=limit,
            include_private=include_private,
            include_global=include_global,
        )

    async def newest_league_event(
        self,
        guild: discord.Guild,
        *,
        include_private: bool = False,
        include_global: bool = False,
    ) -> LeagueEventData | None:
        """Return the single newest event, or None if the feed is empty.

        Used to seed a fresh cursor and to jump past an oversized backlog.
        `ordering=-id&limit=1` makes that a constant-cost lookup.
        """
        page = await self._request_events(
            guild,
            ordering="-id",
            id__gt=None,
            limit=1,
            include_private=include_private,
            include_global=include_global,
        )
        return page.events[0] if page.events else None

    async def _request_events(
        self,
        guild: discord.Guild,
        *,
        ordering: str,
        id__gt: int | None,
        limit: int,
        include_private: bool,
        include_global: bool,
    ) -> EventPage:
        """Single request against the events feed."""
        is_public = None if include_private else True

        # Global events (league is null) cannot be reached through `league=`,
        # which is an inner join. They need guild scoping plus an explicit
        # opt-in, and the API only honours it for superuser keys.
        league: int | None = None
        guild_id: int | None = None
        global_scope: bool | None = None
        if include_global:
            guild_id = guild.id
            global_scope = True
        else:
            league = self._league[guild.id]

        async with self.api_client(guild) as client:
            api = IntegrationsApi(client)
            try:
                page = await api.integrations_events_list(
                    ordering=ordering,
                    id__gt=id__gt,
                    limit=limit,
                    is_public=is_public,
                    league=league,
                    guild_id=guild_id,
                    include_global=global_scope,
                    _request_timeout=API_TIMEOUT,
                )
            except ApiException as exc:
                raise RscException(response=exc) from exc

        events = []
        for raw in page.results:
            event = LeagueEventData.from_api(raw)
            if event is None:
                # The id is the cursor and cannot be substituted.
                log.warning("Skipping league event with no id", guild=guild)
                continue
            events.append(event)

        return EventPage(events=events, count=page.count)

    async def league_event(self, guild: discord.Guild, event_id: int) -> LeagueEventData | None:
        """Fetch a single league event by id."""
        async with self.api_client(guild) as client:
            api = IntegrationsApi(client)
            try:
                event = await api.integrations_events_retrieve(id=event_id, _request_timeout=API_TIMEOUT)
            except ApiException as exc:
                raise RscException(response=exc) from exc
        return LeagueEventData.from_api(event)


# Re-exported for convenience so consumers of the dispatched event do not need
# to reach into rsc.events.models / rsc.enums directly.
__all__ = ["EventAction", "EventCategory", "EventMixIn", "LeagueEventData"]
