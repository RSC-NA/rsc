"""The tracker accounts card, shared by `/accounts` and the player card's Trackers button."""

from collections.abc import Sequence

import discord
from discord import ui
from rscapi.models.tracker_link import TrackerLink

from rsc.const import RSC_TRACKER_URL
from rsc.enums import Platform
from rsc.utils.utils import fix_tracker_url

# Plenty for any real player, and well inside a TextDisplay's limit
MAX_TRACKERS = 25


async def tracker_accounts_card(
    *,
    name: str,
    mention: str,
    trackers: Sequence[TrackerLink],
    avatar_url: str | None = None,
) -> ui.LayoutView:
    """Every tracker account a player has, each linked to its profile.

    Send it with `AllowedMentions.none()`: it names the player, and an old embed never pinged them.
    """
    heading = ui.TextDisplay(f"### {discord.utils.escape_markdown(name)}'s accounts")
    if trackers:
        lines = [await _tracker_line(t) for t in trackers[:MAX_TRACKERS]]
        if len(trackers) > MAX_TRACKERS:
            lines.append(f"-# And {len(trackers) - MAX_TRACKERS} more")
        body = ui.TextDisplay("\n".join(lines))
    else:
        body = ui.TextDisplay(f"{mention} has no registered RL trackers.")

    container = ui.Container(accent_colour=discord.Colour.blue())
    if avatar_url:
        container.add_item(ui.Section(heading, body, accessory=ui.Thumbnail(avatar_url)))
    else:
        container.add_item(heading)
        container.add_item(body)
    container.add_item(ui.ActionRow(ui.Button(label="RSC Tracker Links", url=RSC_TRACKER_URL)))

    view = ui.LayoutView(timeout=None)
    view.add_item(container)
    return view


async def _tracker_line(tracker: TrackerLink) -> str:
    url = await fix_tracker_url(tracker.link)
    platform = _platform_label(tracker.platform.value if tracker.platform else None)
    # Steam accounts are known by their Steam64ID; the rest by account name
    ident = tracker.platform_id if tracker.platform and tracker.platform.value == Platform.STEAM else tracker.name
    label = discord.utils.escape_markdown(f"{platform} · {ident or 'Unknown'}").replace("]", "\\]")
    return f"- [{label}]({url})"


def _platform_label(value: str | None) -> str:
    try:
        return Platform(value).label if value else "Unknown"
    except ValueError:
        return value or "Unknown"
