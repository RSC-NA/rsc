"""Post, DM and finish the lobby card for combines and Dev League matches.

Both runners use these. Each lobby's card and message ids are kept in Config
under `LobbyMessages`, keyed by lobby id, so teardown can redraw the channel post
and every player's DM as Final, even after a restart.
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING

import discord
from pydantic import BaseModel, ValidationError
from redbot.core.config import Group

from rsc.combines.models import CombinesLobby
from rsc.combines.views import LobbyCard, LobbyKind, LobbyScore, LobbyTeam
from rsc.utils.dm import DMOutcome

if TYPE_CHECKING:
    from rsc.abc import RSCMixIn

log = logging.getLogger("red.rsc.combines.lobby")

# Every player named on the card is pinged; nothing else is
LOBBY_MENTIONS = discord.AllowedMentions(everyone=False, roles=False, users=True)


class LobbyMessages(BaseModel):
    """Where a lobby's card was sent, kept until the match is torn down."""

    card: LobbyCard
    channel_id: int
    message_id: int
    # (DM channel id, message id, team) for each player's copy
    dms: list[tuple[int, int, LobbyTeam]] = []
    # A player who can read the lobby from the combines API, to fetch the final score
    executor_id: int | None = None


def lobby_card(
    guild: discord.Guild,
    lobby: CombinesLobby,
    *,
    kind: LobbyKind,
    channels: list[discord.VoiceChannel],
    match_url: str,
    started_at: datetime,
) -> LobbyCard:
    def players(team: list) -> tuple[str, ...]:
        return tuple(m.mention if (m := guild.get_member(p.discord_id)) else discord.utils.escape_markdown(p.name) for p in team)

    home_vc, away_vc = channels
    return LobbyCard(
        kind=kind,
        lobby_id=lobby.id,
        tier=lobby.tier,
        lobby_name=lobby.lobby_user,
        lobby_pass=lobby.lobby_pass,
        home=players(lobby.home),
        away=players(lobby.away),
        lobby_maker=discord.utils.escape_markdown(lobby.home[0].name) if lobby.home else None,
        home_vc_url=home_vc.jump_url,
        away_vc_url=away_vc.jump_url,
        match_url=match_url,
        started_at=started_at,
    )


async def post_lobby(
    cog: "RSCMixIn",
    guild: discord.Guild,
    lobby: CombinesLobby,
    card: LobbyCard,
    channel: discord.TextChannel,
    store: Group,
    active: set[tuple[int, int]],
) -> discord.Message:
    """Send the card to `channel`, remember it, and queue a DM copy for each player."""
    msg = await channel.send(view=card.render(live_emoji=cog.live_emoji()), allowed_mentions=LOBBY_MENTIONS)

    entry = LobbyMessages(
        card=card,
        channel_id=channel.id,
        message_id=msg.id,
        executor_id=next((p.discord_id for p in [*lobby.home, *lobby.away]), None),
    )
    async with store.LobbyMessages() as saved:
        saved[str(card.lobby_id)] = entry.model_dump(mode="json")

    key = (guild.id, card.lobby_id)
    for team, roster in ((LobbyTeam.HOME, lobby.home), (LobbyTeam.AWAY, lobby.away)):
        for index, player in enumerate(roster):
            member = guild.get_member(player.discord_id)
            if not member:
                continue
            makes_lobby = team is LobbyTeam.HOME and index == 0
            # Urgent, so a mass DM already running doesn't hold back the lobby details
            await cog._dm_helper.enqueue(
                member,
                view=card.render(live_emoji=cog.live_emoji(), viewer=team, viewer_makes_lobby=makes_lobby),
                precheck=_still_active(active, key),
                on_result=_record_dm(store, card, team),
                urgent=True,
            )
    return msg


def _still_active(active: set[tuple[int, int]], key: tuple[int, int]):
    async def check() -> bool:
        # A DM still queued when the match ends would only show stale lobby details
        return key in active

    return check


def _record_dm(store: Group, card: LobbyCard, team: LobbyTeam):
    async def record(outcome: DMOutcome, msg: discord.Message | None) -> None:
        if outcome is not DMOutcome.SENT or msg is None:
            return
        async with store.LobbyMessages() as saved:
            raw = saved.get(str(card.lobby_id))
            if raw is not None:
                raw.setdefault("dms", []).append([msg.channel.id, msg.id, team.value])
                return
        # The match ended while this DM was in flight, so it missed teardown's edit
        try:
            await msg.edit(view=card.render(viewer=team, final=True))
        except discord.HTTPException as exc:
            log.debug(f"Unable to mark a late lobby DM final: {exc}")

    return record


async def lobby_messages(store: Group, lobby_id: int) -> LobbyMessages | None:
    raw = (await store.LobbyMessages()).get(str(lobby_id))
    if raw is None:
        return None
    try:
        return LobbyMessages.model_validate(raw)
    except ValidationError as exc:
        log.warning(f"Discarding unreadable lobby message record {lobby_id}: {exc}")
        return None


async def finish_lobby(cog: "RSCMixIn", entry: LobbyMessages, store: Group, score: LobbyScore | None) -> None:
    """Redraw the channel post and every DM as Final, then forget the lobby."""
    card = entry.card
    async with store.LobbyMessages() as saved:
        # Read again under the lock: DMs sent since `entry` was loaded must be edited too
        raw = saved.pop(str(card.lobby_id), None)
    dms = LobbyMessages.model_validate(raw).dms if raw else entry.dms

    channel = cog.bot.get_partial_messageable(entry.channel_id)
    try:
        await channel.get_partial_message(entry.message_id).edit(view=card.render(final=True, score=score))
    except discord.HTTPException as exc:
        log.warning(f"Unable to mark lobby {card.lobby_id} final: {exc}")

    for channel_id, message_id, team in dms:
        dm = cog.bot.get_partial_messageable(channel_id, type=discord.ChannelType.private)
        try:
            await dm.get_partial_message(message_id).edit(view=card.render(viewer=team, final=True, score=score))
        except discord.HTTPException as exc:
            log.debug(f"Unable to mark a lobby {card.lobby_id} DM final: {exc}")
