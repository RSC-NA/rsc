import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from rscapi.models.match_list import MatchList
from rscapi.models.match_results import MatchResults
from rsc.enums import MatchType
from rsc.exceptions import RscException

log = logging.getLogger("red.rsc.llm.loaders.matchloader")

# Type alias for match fetcher callback
MatchFetcher = Callable[[int], Awaitable[MatchResults]]


def is_match_in_past(match_date: datetime | None) -> bool:
    """Check if a match date is in the past, accounting for timezone."""
    if not match_date:
        return False

    effective_tz = match_date.tzinfo or UTC
    now = datetime.now(effective_tz)
    return match_date < now


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


def get_match_status(match_date: datetime | None) -> str:
    """Get a simple temporal status for the match.

    This provides semantic markers for vector search to distinguish
    past/future matches when users ask about 'last' or 'next' matches.
    """
    if not match_date:
        return "Status: SCHEDULED (date TBD)"

    effective_tz = match_date.tzinfo or UTC
    now = datetime.now(effective_tz)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    match_day = match_date.replace(hour=0, minute=0, second=0, microsecond=0)

    delta = (match_day - today).days

    if delta < 0:
        return "Status: COMPLETED (past match, already played)"
    elif delta == 0:
        return "Status: TODAY (match day)"
    else:
        return "Status: SCHEDULED (upcoming future match)"


MATCH_INPUT = """
{match_day}
{status}

Date: {date}

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
        status = get_match_status(m.var_date)
        results_str = ""
        if results:
            results_str = format_match_results(
                results,
                home_team=m.home_team,
                away_team=m.away_team,
            )

        content = MATCH_INPUT.format(
            match_day=match_day,
            status=status,
            date=date_fmt,
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
                    results = await self.match_fetcher(match_id)
                except RscException as e:
                    # Silently skip 404 errors (match not found)
                    if e.status == 404:
                        log.debug(f"Match {match_id} not found or invalid (HTTP {e.status})")
                    else:
                        log.error(f"Failed to fetch match {match_id} results: HTTP {e.status} - {e.reason}")
                except Exception as e:
                    log.warning(f"Failed to fetch match {match_id} results: {e}")

            yield self._build_document(m, results=results)
