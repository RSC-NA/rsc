"""Announce trades performed outside Discord, and reconcile Discord state.

A trade executed through the RSC web UI touches only the database. It emits a
`PTR` league event but performs no Discord side effects at all, so without this
module a traded player keeps their old franchise role and nickname prefix and
nobody in the server is told.

`process_trade_event` is the entry point, registered against `EventAction.PLAYER_TRADED`
in `rsc.events.handlers`. `announce_trade` and `apply_trade_role_updates` are also
driven directly by `/transactions announce <id>`, which exists because several
poller paths advance the cursor without running handlers at all.

Ordering is announce-then-roles, deliberately the reverse of `/transactions trade`.
The slash command's ordering is an artifact of needing `interaction.followup.send`
for per-player errors before its summary. Role application is roughly five to seven
HTTP requests per player, so putting the human-visible output downstream of it makes
the announcement hostage to rate limits. Mentions render client-side at view time, so
nothing about the ordering affects how nicknames appear.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import discord
from pydantic import ValidationError
from rscapi.models.transaction_response import TransactionResponse

from rscapi.models.player_franchise import PlayerFranchise
from rscapi.models.transaction_franchise import TransactionFranchise

from rsc.embeds import BetterEmbed, BlueEmbed, ErrorEmbed, YellowEmbed
from rsc.enums import TransactionType
from rsc.exceptions import RscException
from rsc.logs import GuildLogAdapter
from rsc.transactions.roles import update_signed_player_discord
from rsc.utils import utils

if TYPE_CHECKING:
    from rsc.abc import RSCMixIn
    from rsc.events.models import LeagueEventData

logger = logging.getLogger("red.rsc.transactions.trade_announce")
log = GuildLogAdapter(logger)

#: Beyond this age an event is still reconciled but no longer announced. After
#: extended downtime the poller drains a day of trades at 25 per tick; replaying
#: those announcements is noise, and later trades in the same queue may already
#: have superseded them.
TRADE_ANNOUNCE_MAX_AGE = timedelta(hours=6)

#: How many transaction ids to remember for deduplication. Bounded because it is
#: persisted to config on every trade.
ANNOUNCED_TRADES_MAX = 200

#: Pause between players when applying roles. `Member.add_roles` defaults to
#: `atomic=True`, meaning one HTTP request per role, so a multi-player trade is
#: easily 30+ requests on tight per-guild buckets.
ROLE_UPDATE_DELAY = 0.5

#: Transaction types this module will act on.
TRADE_TYPES = frozenset({TransactionType.TRADE, TransactionType.PLAYER_TRADE})


def _ordinal(round_no: int | None) -> str:
    """Render a draft round. `TransactionPick.round` is Optional."""
    if round_no is None:
        return "Unknown Round"
    match round_no:
        case 1:
            return "1st"
        case 2:
            return "2nd"
        case 3:
            return "3rd"
        case _:
            return f"{round_no}th"


#: The two franchise shapes a trade response can carry. Player destinations come
#: through `PlayerFranchise` and pick destinations through `TransactionFranchise`.
#: They differ in nullability - `name`, `id` and `prefix` are all Optional on
#: `PlayerFranchise` - but both carry a required `gm: FranchiseGM` whose
#: `discord_id` is required, which is why that is the grouping key.
TradeFranchise = PlayerFranchise | TransactionFranchise


async def _franchise_label(guild: discord.Guild, franchise: TradeFranchise) -> str:
    """`Franchise (GM Name)`, preferring the live member's display name."""
    name = franchise.name or "Unknown Franchise"

    # A franchise between GMs has no gm at all.
    if not franchise.gm:
        return name

    member = guild.get_member(franchise.gm.discord_id)
    if member:
        gm_name = await utils.remove_prefix(member)
        gm_name = await utils.strip_discord_accolades(gm_name)
        return f"{name} ({gm_name.strip()})"

    # The payload carries the GM's RSC name, so a GM who has left the server still
    # renders with a name instead of degrading to a bare franchise.
    if franchise.gm.rsc_name:
        return f"{name} ({franchise.gm.rsc_name})"
    return name


async def build_trade_embed_from_response(
    guild: discord.Guild,
    response: TransactionResponse,
) -> tuple[list[int], BetterEmbed]:
    """Render a trade from the API response.

    Returns `(ping_ids, embed)` where `ping_ids` holds destination GM ids and
    traded player ids, matching the contract of `TransactionMixIn.build_trade_embed`.

    Groups into an insertion-ordered dict keyed on GM discord id rather than using
    `itertools.groupby`, which only groups *adjacent* runs and so silently emits
    duplicate fields for one franchise when the input is not pre-sorted.
    """
    lines: dict[int, list[str]] = {}
    franchises: dict[int, TradeFranchise] = {}
    ping_ids: list[int] = []

    def _register(franchise: TradeFranchise) -> int | None:
        # Grouping and pinging are both keyed on the GM's discord id, so a
        # franchise sitting without a GM cannot participate in either.
        if not franchise.gm:
            log.warning(f"Trade franchise {franchise.name} has no GM. Skipping.", guild=guild)
            return None

        gm_id = franchise.gm.discord_id
        # Prefer whichever shape actually carries a name; it is required on
        # TransactionFranchise but nullable on PlayerFranchise.
        if gm_id not in franchises or franchises[gm_id].name is None:
            franchises[gm_id] = franchise
        lines.setdefault(gm_id, [])
        if gm_id not in ping_ids:
            ping_ids.append(gm_id)
        return gm_id

    # Seed from the top level franchises so a franchise that only gives up assets
    # still resolves to a proper label.
    for franchise in (response.first_franchise, response.second_franchise):
        if franchise is not None:
            _register(franchise)

    # Players. `player.team` is the POST-trade team - the API saves the new team
    # before serializing the event - so its franchise is the destination.
    for ptu in response.player_updates or []:
        team = ptu.player.team if ptu.player else None
        if not (team and team.franchise):
            log.warning("Trade player update has no destination franchise", guild=guild)
            continue
        gm_id = _register(team.franchise)
        if gm_id is None:
            continue

        discord_id = ptu.player.player.discord_id if ptu.player and ptu.player.player else None
        if discord_id:
            if discord_id not in ping_ids:
                ping_ids.append(discord_id)
            mention = f"<@!{discord_id}>"
        else:
            mention = (ptu.player.player.name if ptu.player and ptu.player.player else None) or "Unknown Player"

        destination_team = ptu.new_team.name if ptu.new_team else None
        lines[gm_id].append(f"{mention} to {destination_team}" if destination_team else mention)

    # Picks.
    for pick_update in response.pick_trades or []:
        pick = pick_update.pick
        if pick is None:
            continue

        if pick_update.destination is None:
            log.warning("Trade pick update has no destination franchise", guild=guild)
            continue
        gm_id = _register(pick_update.destination)
        if gm_id is None:
            continue

        # Show the source whenever it differs from the destination. The original
        # builder used a `len(groups) > 2` heuristic, which counts groupby runs
        # rather than franchises and misfires on unsorted input.
        prefix = ""
        if pick_update.source is not None:
            source_id = _register(pick_update.source)
            if source_id is not None and source_id != gm_id:
                prefix = f"<@!{source_id}> "

        round_fmt = _ordinal(pick.round)
        tier = pick.tier or "Unknown Tier"

        if pick.future_pick:
            lines[gm_id].append(f"{prefix}Future {round_fmt} Round {tier}")
        elif pick.number is None:
            lines[gm_id].append(f"{prefix}{round_fmt} Round {tier}")
        else:
            lines[gm_id].append(f"{prefix}{round_fmt} Round {tier} ({pick.number})")

    embed = BlueEmbed(title="Trade Confirmed")

    truncated = False
    for gm_id, entries in lines.items():
        if not entries:
            # A franchise seeded from first/second_franchise that gave up nothing
            # trackable. Nothing useful to show.
            continue
        label = await _franchise_label(guild, franchises[gm_id])
        # add_long_field enforces the 1024 / 6000 / 25-field limits and returns
        # whatever did not fit. A bare add_field would 400 the send on a large
        # futures dump.
        leftover = embed.add_long_field(name=label, value="\n".join(entries))
        if leftover:
            truncated = True
            log.warning("Trade embed truncated for franchise %s", label, guild=guild)

    if truncated:
        embed.set_footer(text="Trade too large to display in full. See the web UI for the complete trade.")

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    return ping_ids, embed


async def announce_trade(
    cog: "RSCMixIn",
    guild: discord.Guild,
    response: TransactionResponse,
) -> discord.Message | None:
    """Post a trade to the transaction channel. Returns None if unconfigured."""
    channel = await cog._trans_channel(guild)
    if not channel:
        log.warning("Transaction channel is not configured. Skipping trade announcement.", guild=guild)
        return None

    ping_ids, embed = await build_trade_embed_from_response(guild, response)
    content = " ".join(f"<@!{i}>" for i in ping_ids)

    msg = await channel.send(
        content=content or None,
        embed=embed,
        # Explicit. `AllowedMentions(users=True)` leaves everyone and roles
        # enabled, because every field defaults to a truthy sentinel.
        allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
    )
    # Ping, then strip the content so the message body stays clean.
    await msg.edit(content=None, embed=embed)
    return msg


async def apply_trade_role_updates(
    cog: "RSCMixIn",
    guild: discord.Guild,
    response: TransactionResponse,
) -> list[str]:
    """Reconcile Discord roles and nicknames for every traded player.

    Returns human-readable failure strings rather than writing to an interaction,
    so both the event handler and the slash command can report them their own way.
    One failing player never aborts the rest.
    """
    errors: list[str] = []

    updates = response.player_updates or []
    if not updates:
        return errors

    try:
        tiers = await cog.tiers(guild)
    except RscException as exc:
        log.warning("Unable to fetch tiers for trade role updates: %s", exc, guild=guild)
        tiers = None

    for idx, ptu in enumerate(updates):
        discord_id = ptu.player.player.discord_id if ptu.player and ptu.player.player else None
        if not discord_id:
            errors.append(f"League player `{ptu.player.id if ptu.player else '?'}` has no Discord ID.")
            continue

        member = guild.get_member(discord_id)
        if not member:
            errors.append(f"<@{discord_id}> is not in the server. Roles and nickname were not updated.")
            continue

        try:
            await update_signed_player_discord(guild=guild, player=member, ptu=ptu, tiers=tiers)
        except discord.Forbidden as exc:
            errors.append(f"Missing permissions to update {member.mention}: {exc}")
        except (AttributeError, ValueError) as exc:
            errors.append(f"Unable to update {member.mention}: {exc}")
        except discord.HTTPException as exc:
            errors.append(f"Discord error updating {member.mention}: {exc}")

        # Bound the request burst across a multi-player trade.
        if idx < len(updates) - 1:
            await asyncio.sleep(ROLE_UPDATE_DELAY)

    return errors


async def _parse_trade_response(
    cog: "RSCMixIn",
    guild: discord.Guild,
    event: "LeagueEventData",
) -> TransactionResponse | None:
    """Typed transaction from the event payload, refetching if it will not parse."""
    payload = event.payload if isinstance(event.payload, dict) else {}
    raw = payload.get("transaction")

    if isinstance(raw, dict):
        try:
            return TransactionResponse.from_dict(raw)
        except (ValidationError, ValueError) as exc:
            log.warning("Trade event %d payload did not parse: %s", event.id, exc, guild=guild)

    # The history endpoint uses the same serializer, so this mostly helps when the
    # payload was truncated or the event predates a client regen.
    if event.object_id is None:
        return None

    try:
        return await cog.transaction_history_by_id(guild, event.object_id)
    except Exception as exc:
        # Broad on purpose: this is already the recovery path, and returning None
        # lets the caller post an actionable "announce it manually" report instead
        # of dying silently inside `_run_handler`.
        log.warning("Unable to refetch transaction %d: %s", event.object_id, exc, guild=guild)
        return None


def _is_trade(response: TransactionResponse) -> bool:
    if response.type is None:
        return False
    try:
        # TransactionResponseTypeEnum is (str, Enum), not StrEnum. Convert via
        # .value; never interpolate the member itself into text.
        return TransactionType(response.type.value) in TRADE_TYPES
    except ValueError:
        return False


async def _record_announced(cog: "RSCMixIn", guild: discord.Guild, transaction_id: int) -> None:
    conf = cog.config.custom("Transactions", str(guild.id))
    announced: list[int] = await conf.AnnouncedTrades()
    announced.append(transaction_id)
    await conf.AnnouncedTrades.set(announced[-ANNOUNCED_TRADES_MAX:])


async def process_trade_event(cog: "RSCMixIn", guild: discord.Guild, event: "LeagueEventData") -> None:
    """Handle one `PTR` league event.

    Runs inside `EventMixIn._run_handler`, which swallows exceptions so a failure
    here can never block the poll cursor.
    """
    # Global scoping (`IncludeGlobal`) queries by guild rather than league, so
    # events from another league attached to this guild can reach us. Display
    # filters do not help - handlers run unconditionally by design.
    league = cog._league.get(guild.id)
    if league is not None and event.league is not None and event.league != league:
        log.debug("Ignoring trade event %d from league %s", event.id, event.league, guild=guild)
        return

    response = await _parse_trade_response(cog, guild, event)
    if response is None:
        await _report(
            cog,
            guild,
            ErrorEmbed(
                title="Trade Announcement Failed",
                description=(
                    f"Could not read the transaction for league event **{event.id}**.\n"
                    f"Transaction ID: **{event.object_id}**\n\n"
                    "Announce it manually with `/transactions announce`."
                ),
            ),
        )
        return

    if not _is_trade(response):
        log.debug("Event %d is not a trade transaction. Ignoring.", event.id, guild=guild)
        return

    settings = await cog.config.custom("Transactions", str(guild.id)).all()
    transaction_id = response.id if response.id is not None else event.object_id

    # Announce
    skip_reason = None
    if not settings["TradeAnnouncements"]:
        skip_reason = "announcements are disabled"
    elif transaction_id is not None and transaction_id in settings["AnnouncedTrades"]:
        skip_reason = "it was already announced"
    elif event.created_at and datetime.now(UTC) - event.created_at > TRADE_ANNOUNCE_MAX_AGE:
        skip_reason = "the event is older than the announcement window"

    if skip_reason:
        log.info("Not announcing trade %s: %s", transaction_id, skip_reason, guild=guild)
    else:
        # Record before sending. A crash between the two costs a missed
        # announcement, which is recoverable via `/transactions announce`;
        # recording afterwards would risk announcing the same trade twice.
        if transaction_id is not None:
            await _record_announced(cog, guild, transaction_id)
        try:
            await announce_trade(cog, guild, response)
        except discord.HTTPException as exc:
            log.exception("Failed to announce trade %s", transaction_id, guild=guild)
            await _report(
                cog,
                guild,
                ErrorEmbed(
                    title="Trade Announcement Failed",
                    description=f"Transaction **{transaction_id}** could not be posted: {exc}",
                ),
            )

    # Roles. Independent of the announcement so neither can suppress the other.
    if not settings["TradeRoleUpdates"]:
        return

    errors = await apply_trade_role_updates(cog, guild, response)
    if errors:
        embed = YellowEmbed(
            title="Trade Role Updates Incomplete",
            description=f"Transaction **{transaction_id}** was announced, but some players could not be updated.",
        )
        embed.add_long_field(name="Errors", value="\n".join(f"- {e}" for e in errors))
        await _report(cog, guild, embed)


async def _report(cog: "RSCMixIn", guild: discord.Guild, embed: discord.Embed) -> None:
    """Send a handler diagnostic to the league event log channel.

    Uses `_try_post_embeds` rather than `_post_embeds`: the latter clears the
    channel configuration on Forbidden/NotFound, which should not happen as a
    side effect of reporting a role failure.
    """
    try:
        await cog._try_post_embeds(guild, [embed])
    except Exception:
        log.exception("Unable to report trade handler diagnostics", guild=guild)
