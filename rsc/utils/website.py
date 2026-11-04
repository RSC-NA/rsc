"""Links into the RSC league website.

The website and its REST API are one Django project, with the API mounted under
`/api/<version>/`. So the site's base URL is the guild's configured API URL with
that suffix removed, and a staging API naturally yields the staging site.
"""

import re
from urllib.parse import urlencode, urlsplit

# The API mount point and everything after it, e.g. "/api/v1" or "/api/v1/".
_API_SUFFIX = re.compile(r"/api(?:/.*)?$")


def website_url(api_url: str) -> str | None:
    """The website's base URL for an RSC API URL, or None if it isn't an http(s) URL.

    `https://www.rscna.com/api/v1` -> `https://www.rscna.com`
    """
    parts = urlsplit(api_url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    path = _API_SUFFIX.sub("", parts.path).rstrip("/")
    return f"{parts.scheme}://{parts.netloc}{path}"


def match_page_url(site: str, match_id: int, *, league_id: int, season_id: int | None = None) -> str:
    """The public match page.

    Only `match_id` selects the match. `league` and `season` (a season *ID*, not its
    number) set the page's league/season selector, and the site falls back to the
    current season when `season` is missing. `source=matches` points the page's back
    link at the matches list.
    """
    params: dict[str, int | str] = {"league": league_id}
    if season_id is not None:
        params["season"] = season_id
    params["source"] = "matches"
    return f"{site.rstrip('/')}/matches/{match_id}/?{urlencode(params)}"


def standings_page_url(site: str, *, league_id: int, tier: str, season_id: int | None = None) -> str:
    """The public standings page, opened on one tier's playoff view.

    `league` and `season` (a season *ID*, not its number) set the page's league/season selector,
    and the site falls back to the current season when `season` is missing. `tier` is the tier's
    name, as the page's tier chips use it, and `mode=playoffs` opens the playoff view rather than
    the overall table.
    """
    params: dict[str, int | str] = {"league": league_id}
    if season_id is not None:
        params["season"] = season_id
    params["tier"] = tier
    params["mode"] = "playoffs"
    return f"{site.rstrip('/')}/standings/?{urlencode(params)}"


def bracket_url(site: str, tier: str, *, league_id: int, season_id: int | None = None) -> str:
    """The public playoff bracket for one tier.

    `tier` is the tier's name. `league` and `season` (a season *ID*, not its number) set the page's
    league/season selector.
    """
    params: dict[str, int | str] = {"tier": tier, "league": league_id}
    if season_id is not None:
        params["season"] = season_id
    return f"{site.rstrip('/')}/playoffs/?{urlencode(params)}"


def rsc_id_number(rsc_id: str) -> int | None:
    """The number in an RSC ID, which keys the player page: `RSC001187` -> 1187. None if it isn't one."""
    match = re.fullmatch(r"RSC(\d+)", rsc_id.strip(), flags=re.IGNORECASE)
    return int(match[1]) if match else None


def player_page_url(site: str, rsc_number: int, *, league_id: int) -> str:
    """The public player page. `rsc_number` is the number in the player's RSC ID (see `rsc_id_number`)."""
    return f"{site.rstrip('/')}/player/{rsc_number}/?{urlencode({'league': league_id})}"


def team_page_url(site: str, team_id: int, *, league_id: int) -> str:
    """The public team page."""
    return f"{site.rstrip('/')}/team/{team_id}/?{urlencode({'league': league_id})}"


def franchise_page_url(site: str, franchise_id: int, *, league_id: int) -> str:
    """The public franchise page."""
    return f"{site.rstrip('/')}/franchise/{franchise_id}/?{urlencode({'league': league_id})}"
