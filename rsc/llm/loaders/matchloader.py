import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime, tzinfo

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from rscapi.models.match import Match
from rscapi.models.match_list import MatchList
from rscapi.models.match_results import MatchResults
from rsc.enums import MatchType

log = logging.getLogger("red.rsc.llm.loaders.matchloader")

# Type alias for match fetcher callback
MatchFetcher = Callable[[int], Awaitable[Match]]


def is_match_in_past(match_date: datetime | None) -> bool:
    """Check if a match date is in the past, accounting for timezone."""
    if not match_date:
        return False

    effective_tz = match_date.tzinfo or UTC
    now = datetime.now(effective_tz)
    return match_date < now


def get_relative_time_description(match_date: datetime | None, tz: tzinfo | None = None) -> str:
    """Convert a match date to a human-readable relative time description.

    Args:
        match_date: The match datetime (should be timezone-aware)
        tz: Optional timezone to use for "now". If None, uses the match's timezone
            or falls back to UTC.
    """
    if not match_date:
        return "Date not yet scheduled"

    # Use provided tz, or match's tz, or fallback to UTC
    effective_tz = tz or match_date.tzinfo or UTC
    now = datetime.now(effective_tz)
    # Normalize to start of day for comparison
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    match_day = match_date.replace(hour=0, minute=0, second=0, microsecond=0)

    delta = (match_day - today).days

    if delta < 0:
        # Past matches
        if delta == -1:
            return "This match was yesterday (already played)"
        elif delta >= -7:
            return f"This match was {abs(delta)} days ago (already played)"
        elif delta >= -14:
            return "This match was last week (already played)"
        else:
            return f"This match was {abs(delta)} days ago (already played)"
    elif delta == 0:
        return "This match is TODAY"
    elif delta == 1:
        return "This match is TOMORROW"
    elif delta <= 7:
        return f"This match is in {delta} days (this week)"
    elif delta <= 14:
        return f"This match is in {delta} days (next week)"
    else:
        weeks = delta // 7
        return f"This match is in {delta} days (about {weeks} weeks away)"


def format_match_results(results: MatchResults | None, home_team: str, away_team: str) -> str:
    """Format match results into a human-readable string.

    Args:
        results: MatchResults object or None
        home_team: Name of the home team
        away_team: Name of the away team

    Returns:
        Formatted results string or empty string if no results
    """
    if not results:
        return ""

    home_wins = getattr(results, "home_wins", None)
    away_wins = getattr(results, "away_wins", None)

    if home_wins is None or away_wins is None:
        return ""

    # Determine winner
    if home_wins > away_wins:
        outcome = f"{home_team} won"
    elif away_wins > home_wins:
        outcome = f"{away_team} won"
    else:
        outcome = "Match ended in a tie"

    result_lines = [
        f"\nMatch Result: {outcome}",
        f"Score: {home_team} {home_wins} - {away_wins} {away_team}",
    ]

    # Add ballchasing link if available
    bc_group = getattr(results, "ballchasing_group", None)
    if bc_group:
        result_lines.append(f"Replays: https://ballchasing.com/group/{bc_group}")

    return "\n".join(result_lines)


MATCH_INPUT = """
{match_day}

Date: {date}
{relative_time}

Home Team: {home_team}
Away Team: {away_team}
{results}
"""


class MatchDocumentLoader(BaseLoader):
    """RSC Match Document loader"""

    def __init__(
        self,
        matches: list[MatchList],
        chunk_index: int = 0,
        match_fetcher: MatchFetcher | None = None,
    ) -> None:
        """Initialize the match document loader.

        Args:
            matches: List of MatchList objects to process
            chunk_index: Starting chunk index for document IDs
            match_fetcher: Optional async callback to fetch full Match object by ID.
                          Used to get results for past matches.
        """
        self.matches: list[MatchList] = matches
        self.chunk_index: int = chunk_index
        self.match_fetcher: MatchFetcher | None = match_fetcher

    def _build_document(
        self,
        m: MatchList,
        results: MatchResults | None = None,
    ) -> Document:
        """Build a Document from a match."""
        match m.match_type:
            case MatchType.REGULAR:
                match_day = f"Regular Season Match Day {m.day}"
            case MatchType.PRESEASON:
                match_day = f"Pre-season Match {m.day}"
            case MatchType.POSTSEASON:
                match_day = f"Post-season Match {m.day}"
            case MatchType.FINALS:
                match_day = "Finals Match"
            case _:
                match_day = "Match"

        date_fmt = m.var_date.strftime("%m-%d-%Y") if m.var_date else "TBD"
        relative_time = get_relative_time_description(m.var_date)
        results_str = ""
        if results:
            results_str = format_match_results(
                results,
                home_team=m.home_team,
                away_team=m.away_team,
            )

        content = MATCH_INPUT.format(
            match_day=match_day,
            date=date_fmt,
            relative_time=relative_time,
            home_team=m.home_team,
            away_team=m.away_team,
            results=results_str,
        )

        doc = Document(
            page_content=content,
            metadata={"source": "Matches API", "id": str(m.id), "chunk_index": self.chunk_index},
        )
        self.chunk_index += 1
        return doc

    def _process_matches(self) -> Iterator[Document]:
        """Process matches and yield Documents (sync, no results fetching)."""
        for m in self.matches:
            yield self._build_document(m)

    def lazy_load(self) -> Iterator[Document]:
        """A lazy loader that reads RSC Match documents."""
        yield from self._process_matches()

    async def alazy_load(self) -> AsyncIterator[Document]:
        """An async lazy loader for RSC Match documents.

        If a match_fetcher was provided and the match date is in the past,
        fetches the full Match object to include results.
        """
        for m in self.matches:
            results: MatchResults | None = None

            # Fetch results for past matches if we have a fetcher and valid ID
            match_id = m.id
            if self.match_fetcher and match_id is not None and is_match_in_past(m.var_date):
                try:
                    full_match = await self.match_fetcher(match_id)
                    results = getattr(full_match, "results", None)
                except Exception as e:
                    log.warning(f"Failed to fetch match {match_id} results: {e}")

            yield self._build_document(m, results=results)
