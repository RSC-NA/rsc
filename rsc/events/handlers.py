"""Side effects the bot performs in response to league events.

Separate from `rsc.events.formatters` on purpose. That module's contract is that
everything it renders is untrusted API JSON destined for a channel that suppresses
mentions; handlers here deliberately ping people and edit members, so the two
should not share a namespace.

Handlers run inside `EventMixIn._run_handler`, which catches every exception so a
handler failure can never block the poll cursor. They also run unconditionally -
the category/action/severity filters only govern what reaches the event log
channel, never what gets processed.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import discord

from rsc.enums import EventAction

if TYPE_CHECKING:
    from rsc.abc import RSCMixIn
    from rsc.events.models import LeagueEventData

log = logging.getLogger("red.rsc.events.handlers")

EventHandler = Callable[["RSCMixIn", discord.Guild, "LeagueEventData"], Awaitable[None]]


async def handle_player_traded(cog: "RSCMixIn", guild: discord.Guild, event: "LeagueEventData") -> None:
    """A trade was performed outside Discord, most likely through the web UI.

    Imported lazily. `rsc.transactions` is a large package that pulls in franchises,
    teams and settings, and importing it at module scope here would make the events
    package depend on transactions at import time.
    """
    from rsc.transactions.trade_announce import process_trade_event

    await process_trade_event(cog, guild, event)


#: Optional side effects keyed by action. An action with no entry is logged and
#: dispatched but triggers nothing else.
EVENT_HANDLERS: dict[EventAction, EventHandler] = {
    EventAction.PLAYER_TRADED: handle_player_traded,
}
