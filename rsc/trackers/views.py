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
UNKNOWN_PLATFORM = "Other"


async def tracker_accounts_card(
    *,
    mention: str,
    trackers: Sequence[TrackerLink],
    avatar_url: str | None = None,
) -> ui.LayoutView:
    """Every tracker account a player has, grouped by platform, each linked to its profile.

    Send it with `AllowedMentions.none()`: it names the player, and the old embed never pinged them.
    """
    shown = trackers[:MAX_TRACKERS]
    count = f"{len(trackers)} account{'' if len(trackers) == 1 else 's'}"
    heading = ui.TextDisplay(f"### Tracker accounts\n-# {mention} · {count}" if trackers else f"### Tracker accounts\n-# {mention}")

    if shown:
        groups: dict[str, list[str]] = {}
        for tracker in shown:
            platform = _platform_label(tracker.platform.value if tracker.platform else None)
            groups.setdefault(platform, []).append(await _tracker_line(tracker))
        sections = [f"**{platform}**\n" + "\n".join(lines) for platform, lines in sorted(groups.items(), key=_platform_order)]
        if len(trackers) > MAX_TRACKERS:
            sections.append(f"-# And {len(trackers) - MAX_TRACKERS} more")
        body = ui.TextDisplay("\n".join(sections))
    else:
        body = ui.TextDisplay("No registered RL trackers.")

    container = ui.Container(accent_colour=discord.Colour.blue())
    if avatar_url:
        # The list sits beside the avatar too: a Section is as tall as its thumbnail, so the heading
        # alone would leave a blank band under it
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
    # Steam accounts are known by their Steam64ID; the rest by account name
    ident = tracker.platform_id if tracker.platform and tracker.platform.value == Platform.STEAM else tracker.name
    label = discord.utils.escape_markdown(ident or "Unknown").replace("]", "\\]")
    return f"- [{label}]({url})"


def _platform_label(value: str | None) -> str:
    try:
        return Platform(value).label if value else UNKNOWN_PLATFORM
    except ValueError:
        return value or UNKNOWN_PLATFORM


def _platform_order(group: tuple[str, list[str]]) -> int:
    """Platforms in `Platform` order, anything unrecognised last."""
    labels = [p.label for p in Platform]
    return labels.index(group[0]) if group[0] in labels else len(labels)
