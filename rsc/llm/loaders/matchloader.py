import logging
from collections.abc import AsyncIterator, Iterator

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from rscapi.models.match_list import MatchList
from rsc.enums import MatchType

log = logging.getLogger("red.rsc.llm.loaders.matchloader")


MATCH_INPUT = """
{match_day}

Date: {date}

Home Team: {home_team}
Away Team: {away_team}
"""


class MatchDocumentLoader(BaseLoader):
    """RSC Match Document loader"""

    def __init__(self, matches: list[MatchList], chunk_index: int = 0) -> None:
        self.matches: list[MatchList] = matches
        self.chunk_index: int = chunk_index

    def _process_matches(self) -> Iterator[Document]:
        """Process matches and yield Documents."""
        for m in self.matches:
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

            content = MATCH_INPUT.format(
                match_day=match_day,
                date=date_fmt,
                home_team=m.home_team,
                away_team=m.away_team,
            )

            yield Document(
                page_content=content,
                metadata={"source": "Matches API", "id": str(m.id), "chunk_index": self.chunk_index},
            )
            self.chunk_index += 1

    def lazy_load(self) -> Iterator[Document]:
        """A lazy loader that reads RSC Match documents."""
        yield from self._process_matches()

    async def alazy_load(self) -> AsyncIterator[Document]:
        """An async lazy loader for RSC Match documents."""
        for doc in self._process_matches():
            yield doc
