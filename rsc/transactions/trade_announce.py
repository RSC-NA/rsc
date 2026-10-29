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
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, NamedTuple

import discord
from pydantic import ValidationError
from rscapi.models.player_franchise import PlayerFranchise
from rscapi.models.player_transaction_updates import PlayerTransactionUpdates
from rscapi.models.team_franchise import TeamFranchise
from rscapi.models.trade_object import TradeObject
from rscapi.models.transaction_franchise import TransactionFranchise
from rscapi.models.transaction_response import TransactionResponse

from rsc.embeds import ErrorEmbed, YellowEmbed
from rsc.enums import TransactionType
from rsc.exceptions import RscException
from rsc.logs import GuildLogAdapter
from rsc.transactions.roles import update_signed_player_discord
from rsc.transactions.views import TradeCard, TradeGiver, TradePick, TradePlayer, TradeReceiver
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


#: The two franchise shapes a trade response can carry. Player destinations come
#: through `PlayerFranchise` and pick destinations through `TransactionFranchise`.
#: They differ in nullability - `name`, `id` and `prefix` are all Optional on
#: `PlayerFranchise` - but both carry a `gm: FranchiseGM` whose `discord_id` is
#: required, which is why that is the grouping key.
TradeFranchise = PlayerFranchise | TransactionFranchise

#: A franchise's grouping key: its GM's discord id, or its lowercased name when it
#: has no GM. Never the franchise id, which is Optional on `PlayerFranchise` and
#: would split one franchise in two.
FranchiseKey = int | str


def _franchise_key(franchise: TradeFranchise | TeamFranchise) -> FranchiseKey | None:
    if franchise.gm:
        return franchise.gm.discord_id
    if franchise.name:
        return franchise.name.lower()
    return None


def _player_mention(ptu: PlayerTransactionUpdates) -> tuple[int | None, str]:
    """The player's discord id, and how the card names them: a mention, or their escaped name."""
    member = ptu.player.player if ptu.player else None
    if member and member.discord_id:
        return member.discord_id, f"<@{member.discord_id}>"
    name = member.name if member and member.name else "Unknown Player"
    return None, discord.utils.escape_markdown(name)


@dataclass
class _Received:
    """What one franchise receives from one giver, while the card is being assembled."""

    players: list[TradePlayer] = field(default_factory=list)
    picks: list[TradePick] = field(default_factory=list)
    tiers: set[str] = field(default_factory=set)


class FranchiseRef(NamedTuple):
    """A franchise found outside the response's franchise objects: its grouping key and name."""

    key: FranchiseKey
    name: str | None


def player_sources_from_trade(trades: list[TradeObject]) -> dict[int, FranchiseRef]:
    """Which franchise each player in a `/transactions trade` came from, keyed on their discord id.

    The command parsed this from the trade text, so passing it to `build_trade_card`
    saves the old-team lookups a trade of three or more franchises otherwise needs.
    """
    sources: dict[int, FranchiseRef] = {}
    for trade in trades:
        if not trade.value.player:
            continue
        source = trade.source
        key = source.gm or (source.name.lower() if source.name else None)
        if key is not None:
            sources[trade.value.player.id] = FranchiseRef(key, source.name)
    return sources


async def _player_givers(
    cog: "RSCMixIn",
    guild: discord.Guild,
    response: TransactionResponse,
    involved: set[FranchiseKey],
    hints: Mapping[int, FranchiseRef],
) -> list[FranchiseRef | None]:
    """The franchise each traded player left, in `player_updates` order.

    The response only names a player's old team, not its franchise. `hints` answers
    it when the caller knows; with two franchises in the trade it is simply the other
    one; otherwise the old team is looked up. None when it can't be found, so the
    player still shows, unlabelled.
    """
    cache: dict[tuple[str, str | None], FranchiseRef | None] = {}
    givers: list[FranchiseRef | None] = []
    for ptu in response.player_updates or []:
        discord_id, _ = _player_mention(ptu)
        if discord_id is not None and discord_id in hints:
            givers.append(hints[discord_id])
            continue

        if len(involved) == 2:
            dest = ptu.player.team.franchise if ptu.player and ptu.player.team else None
            dest_key = _franchise_key(dest) if dest else None
            other = next((k for k in involved if k != dest_key), None)
            givers.append(FranchiseRef(other, None) if other is not None else None)
            continue

        old = ptu.old_team
        if not (old and old.name):
            givers.append(None)
            continue
        lookup = (old.name, old.tier or None)
        if lookup not in cache:
            try:
                teams = await cog.teams(guild, name=old.name, tier=old.tier or None)
            except RscException as exc:
                log.warning("Unable to find the franchise of team %s: %s", old.name, exc, guild=guild)
                teams = []
            match = next((t for t in teams if t.name == old.name), None)
            key = _franchise_key(match.franchise) if match else None
            cache[lookup] = FranchiseRef(key, match.franchise.name) if match and key is not None else None
        givers.append(cache[lookup])
    return givers


async def _accent(guild: discord.Guild, name: str, tiers: set[str]) -> discord.Colour:
    """The franchise role's colour, or the tier's when the franchise receives from one tier only."""
    role = await utils.franchise_role_from_name(guild, name)
    if role and role.colour.value:
        return role.colour
    if len(tiers) == 1:
        return await utils.tier_color_by_name(guild, next(iter(tiers)))
    return discord.Colour.blue()


async def _logo(cog: "RSCMixIn", guild: discord.Guild, franchise_id: int | None) -> str | None:
    if franchise_id is None:
        return None
    try:
        return await cog.franchise_logo(guild, franchise_id)
    except RscException as exc:
        log.warning("Unable to fetch franchise logo %s: %s", franchise_id, exc, guild=guild)
        return None


async def _tier_order(cog: "RSCMixIn", guild: discord.Guild) -> tuple[str, ...]:
    """Tier names, highest first."""
    try:
        tiers = await cog.tiers(guild)
    except RscException as exc:
        log.warning("Unable to fetch tiers to order trade picks: %s", exc, guild=guild)
        return ()
    return tuple(t.name for t in sorted(tiers, key=lambda t: t.position, reverse=True))


async def build_trade_card(
    cog: "RSCMixIn",
    guild: discord.Guild,
    response: TransactionResponse,
    player_sources: Mapping[int, FranchiseRef] | None = None,
) -> TradeCard:
    """The trade card, from the API's trade response.

    Shared by website trades (`PTR` events and `/transactions processtrade`) and
    `/transactions trade`, which gets the same response back from the trade call.
    `player_sources` optionally says which franchise each player left (see
    `player_sources_from_trade`).

    Groups into insertion-ordered dicts keyed on `_franchise_key` rather than using
    `itertools.groupby`, which only groups *adjacent* runs and so silently emits a
    franchise twice when the input is not pre-sorted.
    """
    franchises: dict[FranchiseKey, TradeFranchise] = {}
    received: dict[FranchiseKey, dict[FranchiseKey | None, _Received]] = {}

    def register(franchise: TradeFranchise | None) -> FranchiseKey | None:
        if franchise is None:
            return None
        key = _franchise_key(franchise)
        if key is None:
            log.warning("Trade franchise has no GM and no name. Skipping.", guild=guild)
            return None
        # Prefer whichever shape carries a name and id; both are required on
        # TransactionFranchise but nullable on PlayerFranchise.
        known = franchises.get(key)
        if known is None or known.name is None or (known.id is None and franchise.id is not None and franchise.name):
            franchises[key] = franchise
        received.setdefault(key, {})
        return key

    # Seed from the top level franchises, so the card order follows the trade
    for franchise in (response.first_franchise, response.second_franchise):
        register(franchise)

    # Every franchise the trade touches, to tell a two-franchise trade from a bigger one
    for ptu in response.player_updates or []:
        register(ptu.player.team.franchise if ptu.player and ptu.player.team else None)
    for pick_update in response.pick_trades or []:
        register(pick_update.destination)
        register(pick_update.source)

    # Players. `player.team` is the POST-trade team - the API saves the new team
    # before serializing the event - so its franchise is the destination.
    updates = response.player_updates or []
    givers = await _player_givers(cog, guild, response, set(franchises), player_sources or {})
    # Names for givers found through hints or a team lookup, which may give without receiving
    giver_names: dict[FranchiseKey, str] = {}
    for ptu, ref in zip(updates, givers, strict=True):
        giver = ref.key if ref else None
        if ref and ref.name and ref.key not in franchises:
            giver_names.setdefault(ref.key, ref.name)
        dest = ptu.player.team.franchise if ptu.player and ptu.player.team else None
        dest_key = _franchise_key(dest) if dest else None
        if dest_key is None or dest_key not in received:
            log.warning("Trade player update has no destination franchise", guild=guild)
            continue
        _, mention = _player_mention(ptu)
        team = discord.utils.escape_markdown(ptu.new_team.name) if ptu.new_team and ptu.new_team.name else None
        group = received[dest_key].setdefault(giver if giver != dest_key else None, _Received())
        group.players.append(TradePlayer(mention=mention, team=team))
        tier = (ptu.new_team.tier if ptu.new_team else None) or (ptu.player.tier.name if ptu.player.tier else None)
        if tier:
            group.tiers.add(tier)

    # Picks
    for pick_update in response.pick_trades or []:
        pick = pick_update.pick
        if pick is None:
            continue
        dest_key = _franchise_key(pick_update.destination) if pick_update.destination else None
        if dest_key is None or dest_key not in received:
            log.warning("Trade pick update has no destination franchise", guild=guild)
            continue
        source = pick_update.source
        source_key = _franchise_key(source) if source else None
        # A pick "from" its own destination says nothing, so it shows unlabelled
        giver = source_key if source_key != dest_key else None
        via = pick.original_pick
        if via and source and source.prefix and via.lower() == source.prefix.lower():
            via = None
        tier = pick.tier or "Unknown Tier"
        group = received[dest_key].setdefault(giver, _Received())
        group.picks.append(
            TradePick(
                tier=tier,
                round=pick.round,
                number=pick.number,
                future=bool(pick.future_pick),
                # 0 is what the API sends for a pick with no season
                season=pick.future_season or None,
                via=via or None,
            )
        )
        if pick.tier:
            group.tiers.add(pick.tier)

    def _giver_name(key: FranchiseKey) -> str:
        known = franchises.get(key)
        return (known.name if known else None) or giver_names.get(key) or "Unknown Franchise"

    def _giver_gm(key: FranchiseKey) -> int | None:
        # Only a giver that receives nothing, since a receiver's GM is already pinged on its own card
        known = franchises.get(key)
        if received.get(key) or not known or not known.gm:
            return None
        return known.gm.discord_id

    receivers: list[TradeReceiver] = []
    for key, by_giver in received.items():
        if not by_giver:
            # A franchise that gave things up but received nothing. Its assets
            # show on the receiving cards.
            continue
        franchise = franchises[key]
        name = franchise.name or "Unknown Franchise"
        # Known givers in the order they appeared, then anything of unknown origin
        ordered = sorted(by_giver.items(), key=lambda item: item[0] is None)
        receivers.append(
            TradeReceiver(
                name=discord.utils.escape_markdown(name),
                colour=await _accent(guild, name, set().union(*(g.tiers for g in by_giver.values()))),
                givers=tuple(
                    TradeGiver(
                        name=discord.utils.escape_markdown(_giver_name(giver)) if giver is not None else None,
                        players=tuple(group.players),
                        picks=tuple(group.picks),
                        gm_id=_giver_gm(giver) if giver is not None else None,
                    )
                    for giver, group in ordered
                ),
                gm_id=franchise.gm.discord_id if franchise.gm else None,
                logo=await _logo(cog, guild, franchise.id),
            )
        )

    return TradeCard(
        receivers=tuple(receivers),
        banner=utils.TRADE_BANNER,
        created_at=response.var_date or discord.utils.utcnow(),
        transaction_id=response.id,
        tier_order=await _tier_order(cog, guild),
    )


async def announce_trade(
    cog: "RSCMixIn",
    guild: discord.Guild,
    response: TransactionResponse,
    player_sources: Mapping[int, FranchiseRef] | None = None,
) -> discord.Message | None:
    """Post a trade to the transaction channel. Returns None if unconfigured."""
    channel = await cog._trans_channel(guild)
    if not channel:
        log.warning("Transaction channel is not configured. Skipping trade announcement.", guild=guild)
        return None

    card = await build_trade_card(cog, guild, response, player_sources)
    view, files = card.render()
    # Every GM and player pings from the card's TextDisplays
    return await channel.send(
        view=view,
        files=files,
        # Explicit. `AllowedMentions(users=True)` leaves everyone and roles
        # enabled, because every field defaults to a truthy sentinel.
        allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
    )


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
    # Defence in depth. `EventMixIn._in_scope` already drops another league's
    # events before dispatch, so this should be unreachable from the poller -
    # but this function is a public entry point and the cost of being wrong is
    # announcing a foreign league's trade into this guild's transaction channel.
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
