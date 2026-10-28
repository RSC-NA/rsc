import re
from dataclasses import dataclass
from enum import StrEnum

from rsc.utils.utils import fix_tracker_url

# rocketleague.tracker.network/rocket-league/profile/{platform}/{id}/...
TRACKER_PROFILE_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?rocketleague\.tracker\.network/rocket-league/profile/(?P<platform>[a-z]+)/(?P<id>[^/?#\s]+)",
    re.IGNORECASE,
)
STEAM64_RE = re.compile(r"^\d{17}$")

TRACKER_EXAMPLE = "rocketleague.tracker.network/rocket-league/profile/epic/YourName/overview"

# Platform segment of a tracker URL -> player-facing name
TRACKER_PLATFORMS = {
    "steam": "Steam",
    "epic": "Epic",
    "psn": "PlayStation",
    "xbl": "Xbox",
    "switch": "Switch",
}


class TrackerProblem(StrEnum):
    NOT_PROFILE = "isn't a tracker profile link"
    UNKNOWN_PLATFORM = "isn't on a platform the tracker site supports"
    NOT_STEAM64 = "needs your Steam64ID, a 17-digit number"


@dataclass(frozen=True)
class TrackerLine:
    """One line of the tracker links field, checked against the profile URL format."""

    raw: str
    url: str = ""
    platform: str = ""
    player_id: str = ""
    problem: TrackerProblem | None = None

    @property
    def valid(self) -> bool:
        return self.problem is None

    @property
    def platform_name(self) -> str:
        return TRACKER_PLATFORMS.get(self.platform, self.platform)


async def parse_tracker_line(line: str) -> TrackerLine:
    raw = line.strip()
    url = await fix_tracker_url(raw)
    match = TRACKER_PROFILE_RE.match(url)
    if not match:
        return TrackerLine(raw=raw, problem=TrackerProblem.NOT_PROFILE)

    platform = match.group("platform").lower()
    player_id = match.group("id")
    if platform not in TRACKER_PLATFORMS:
        return TrackerLine(raw=raw, url=url, platform=platform, player_id=player_id, problem=TrackerProblem.UNKNOWN_PLATFORM)
    if platform == "steam" and not STEAM64_RE.match(player_id):
        return TrackerLine(raw=raw, url=url, platform=platform, player_id=player_id, problem=TrackerProblem.NOT_STEAM64)
    if not url.lower().startswith("http"):
        url = f"https://{url}"
    return TrackerLine(raw=raw, url=url, platform=platform, player_id=player_id)


async def parse_tracker_links(text: str) -> list[TrackerLine]:
    """Parse the tracker links field. Blank lines and repeated links are dropped."""
    lines: list[TrackerLine] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        parsed = await parse_tracker_line(line)
        key = f"{parsed.platform}/{parsed.player_id}".lower() if parsed.valid else parsed.raw
        if key in seen:
            continue
        seen.add(key)
        lines.append(parsed)
    return lines
