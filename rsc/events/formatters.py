"""Embed rendering for league events.

Side effects live in `rsc.events.handlers`, deliberately kept out of this module:
everything rendered here is untrusted API JSON destined for a channel that
suppresses mentions, whereas handlers ping people and edit members.

Only the actions the API actually produces today have dedicated formatters:
`PTR` (player traded) and `WCW`/`WCL` (waiver claim resolved). Every other
action, and any action this bot's enum does not recognise, falls through to
`generic_event_embed`. That is intentional so an API side addition shows up as a
readable payload dump rather than an error.

Everything rendered here originates from the API's free form `payload` JSON and
ends up in a Discord message. Callers must send with
`discord.AllowedMentions.none()`; strings interpolated from a payload are run
through `escape_markdown` here.
"""

import json
import logging
from collections.abc import Callable

import discord

from rsc.embeds import BetterEmbed, BlueEmbed, GreenEmbed, OrangeEmbed, RedEmbed, YellowEmbed
from rsc.enums import EventAction, EventCategory, EventSeverity
from rsc.events.models import LeagueEventData

log = logging.getLogger("red.rsc.events.formatters")

MAX_PAYLOAD_CHARS = 3000


def _clean(value: object, default: str = "N/A") -> str:
    """Render an untrusted payload value as safe embed text."""
    if value is None or value == "":
        return default
    return discord.utils.escape_markdown(str(value))


def _payload_block(payload: object) -> str:
    try:
        rendered = json.dumps(payload, indent=2, default=str, sort_keys=True)
    except (TypeError, ValueError):
        rendered = str(payload)

    if len(rendered) > MAX_PAYLOAD_CHARS:
        rendered = f"{rendered[:MAX_PAYLOAD_CHARS]}\n... (truncated)"
    return f"```json\n{rendered}\n```"


def _actor_value(event: LeagueEventData) -> str:
    if not (event.actor_name or event.actor_discord_id):
        return "System"
    name = _clean(event.actor_name, default="Unknown")
    if event.actor_discord_id:
        # Safe to render as a mention only because sends use AllowedMentions.none()
        return f"{name} (<@{event.actor_discord_id}>)"
    return name


#: Severity drives the embed colour. `SYS` events are an operational error
#: stream, so a failed MMR pull must not look like a routine signing.
SEVERITY_EMBED: dict[EventSeverity, type[BetterEmbed]] = {
    EventSeverity.INFO: BlueEmbed,
    EventSeverity.WARNING: YellowEmbed,
    EventSeverity.ERROR: OrangeEmbed,
    EventSeverity.CRITICAL: RedEmbed,
}

SEVERITY_ICON: dict[EventSeverity, str] = {
    EventSeverity.INFO: "\N{INFORMATION SOURCE}",
    EventSeverity.WARNING: "\N{WARNING SIGN}",
    EventSeverity.ERROR: "\N{CROSS MARK}",
    EventSeverity.CRITICAL: "\N{POLICE CARS REVOLVING LIGHT}",
}


def _embed_for(event: LeagueEventData, default: type[BetterEmbed] = BlueEmbed, **kwargs) -> BetterEmbed:
    """Build an embed coloured by severity, falling back to `default`.

    Anything above INFO overrides a formatter's own colour choice, so an errored
    event is never rendered as if it succeeded.
    """
    severity = event.event_severity
    if severity and severity is not EventSeverity.INFO:
        return SEVERITY_EMBED[severity](**kwargs)
    return default(**kwargs)


def _add_common_fields(embed: BetterEmbed, event: LeagueEventData) -> None:
    embed.add_field(name="Event ID", value=str(event.id), inline=True)
    if event.object_id is not None:
        embed.add_field(name="Object ID", value=str(event.object_id), inline=True)
    embed.add_field(name="Actor", value=_actor_value(event), inline=True)
    if event.created_at:
        embed.add_field(
            name="Occurred",
            value=discord.utils.format_dt(event.created_at, style="R"),
            inline=True,
        )

    severity = event.event_severity
    if severity and severity is not EventSeverity.INFO:
        embed.add_field(
            name="Severity",
            value=f"{SEVERITY_ICON[severity]} {severity.full_name}",
            inline=True,
        )
    elif event.severity and severity is None:
        embed.add_field(name="Severity", value=_clean(event.severity), inline=True)

    if event.is_global:
        embed.add_field(name="Scope", value="\N{EARTH GLOBE AMERICAS} Global", inline=True)
    if not event.is_public:
        embed.add_field(name="Visibility", value="\N{LOCK} Private", inline=True)


def _title(event: LeagueEventData) -> str:
    category = event.event_category
    action = event.event_action

    if action:
        return action.full_name
    if category:
        return f"{category.full_name} Event"
    return "League Event"


def generic_event_embed(event: LeagueEventData) -> BetterEmbed:
    """Fallback renderer. Also handles actions this bot's enum does not know.

    This is the path every `SYS` event takes, so it must stay readable for the
    operational error stream, not just for unrecognised league activity.
    """
    category = event.event_category
    action = event.event_action

    embed = _embed_for(event, title=_title(event))

    category_str = category.full_name if category else _clean(event.category, default="Unknown")
    action_str = action.full_name if action else _clean(event.action, default="None")

    embed.add_field(name="Category", value=category_str, inline=True)
    embed.add_field(name="Action", value=action_str, inline=True)
    _add_common_fields(embed, event)

    if action is None and event.action:
        embed.set_footer(text="Unrecognized action. The bot may need an update.")

    if event.payload:
        # Return value matters: add_long_field silently drops the remainder.
        leftover = embed.add_long_field(name="Payload", value=_payload_block(event.payload))
        if leftover:
            log.debug("Truncated payload for event %d (%d chars dropped)", event.id, len(leftover))

    return embed


def player_traded_embed(event: LeagueEventData) -> BetterEmbed:
    """`PTR` - a compact audit record, not the announcement.

    The real announcement goes to the transaction channel via
    `rsc.transactions.trade_announce`, complete with GM pings. Repeating the whole
    transaction here would just be noise, so this records only enough to tie the
    event back to a transaction and to spot a trade the handler skipped.
    """
    payload = event.payload if isinstance(event.payload, dict) else {}
    transaction = payload.get("transaction")
    if not isinstance(transaction, dict):
        return generic_event_embed(event)

    embed = _embed_for(event, default=YellowEmbed, title="Player Traded")

    transaction_id = transaction.get("id")
    embed.add_field(name="Transaction ID", value=_clean(transaction_id), inline=True)

    players = transaction.get("player_updates") or []
    picks = transaction.get("pick_trades") or []
    embed.add_field(name="Players", value=str(len(players)), inline=True)
    embed.add_field(name="Picks", value=str(len(picks)), inline=True)

    names = []
    for key in ("first_franchise", "second_franchise"):
        franchise = transaction.get(key)
        if isinstance(franchise, dict) and franchise.get("name"):
            names.append(_clean(franchise["name"]))
    if names:
        embed.add_field(name="Franchises", value=" \N{LEFT RIGHT ARROW} ".join(names), inline=False)

    if notes := transaction.get("notes"):
        embed.add_field(name="Notes", value=_clean(notes)[:1024], inline=False)

    _add_common_fields(embed, event)
    return embed


def waiver_claim_embed(event: LeagueEventData) -> BetterEmbed:
    """`WCW`/`WCL` - payload carries a `waiver_claim` object."""
    payload = event.payload if isinstance(event.payload, dict) else {}
    claim = payload.get("waiver_claim")
    if not isinstance(claim, dict):
        return generic_event_embed(event)

    won = event.event_action is EventAction.WAIVER_CLAIM_WON
    embed = _embed_for(
        event,
        default=GreenEmbed if won else OrangeEmbed,
        title="Waiver Claim Won" if won else "Waiver Claim Lost",
    )

    embed.add_field(name="Player", value=_clean(claim.get("player_name")), inline=True)
    embed.add_field(name="Franchise", value=_clean(claim.get("franchise_name")), inline=True)
    embed.add_field(name="Tier", value=_clean(claim.get("tier_name")), inline=True)

    if outcome := claim.get("outcome"):
        embed.add_field(name="Outcome", value=_clean(outcome), inline=True)
    if reason := claim.get("reason"):
        embed.add_field(name="Reason", value=_clean(reason)[:1024], inline=False)

    _add_common_fields(embed, event)
    return embed


#: Action to embed builder. Anything absent renders via `generic_event_embed`.
EVENT_FORMATTERS: dict[EventAction, Callable[[LeagueEventData], BetterEmbed]] = {
    EventAction.PLAYER_TRADED: player_traded_embed,
    EventAction.WAIVER_CLAIM_WON: waiver_claim_embed,
    EventAction.WAIVER_CLAIM_LOST: waiver_claim_embed,
}


def build_event_embed(event: LeagueEventData) -> BetterEmbed:
    """Render one event, falling back to generic on any formatter failure."""
    action = event.event_action
    formatter = EVENT_FORMATTERS.get(action) if action else None
    if formatter is None:
        return generic_event_embed(event)

    try:
        return formatter(event)
    except Exception:
        # A malformed payload must not stop the event from being logged.
        log.exception("Formatter failed for event %d (%s). Falling back to generic.", event.id, event.action)
        return generic_event_embed(event)


def backlog_summary_embed(count: int, low: int, high: int) -> YellowEmbed:
    """Posted instead of individual embeds when a response is oversized."""
    embed = YellowEmbed(
        title="League Event Backlog Skipped",
        description=(
            f"Received **{count}** events in a single poll, which is above the posting threshold. "
            "The cursor was advanced without logging them individually to avoid flooding this channel."
        ),
    )
    embed.add_field(name="Event ID Range", value=f"{low} - {high}", inline=True)
    return embed


def unhealthy_embed(failures: int, error: str | None) -> RedEmbed:
    embed = RedEmbed(
        title="League Event Poller Unhealthy",
        description=f"The poller has failed **{failures}** consecutive times. Events are not being processed.",
    )
    embed.add_field(name="Last Error", value=discord.utils.escape_markdown(str(error or "Unknown"))[:1024], inline=False)
    return embed


def recovered_embed() -> GreenEmbed:
    return GreenEmbed(
        title="League Event Poller Recovered",
        description="Polling has resumed successfully.",
    )


def category_label(value: str) -> str:
    try:
        return EventCategory(value).full_name
    except ValueError:
        return value


def action_label(value: str) -> str:
    try:
        return EventAction(value).full_name
    except ValueError:
        return value


def severity_label(value: str) -> str:
    try:
        return EventSeverity(value).full_name
    except ValueError:
        return value
