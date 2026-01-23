import logging
import re
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import aiofiles
from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document

log = logging.getLogger("red.rsc.llm.loaders.ruleloader")


class RuleDocumentLoader(BaseLoader):
    """RSC Rule Document style loader"""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.file_name = Path(file_path).stem.replace("-", " ")

    def _parse_content(self, data: str) -> Iterator[Document]:
        """Parse RSC Rule document content and yield Documents."""
        source = None
        rule_group: list[str] = []
        chunk_index = 0
        for line in data.splitlines():
            if len(line.strip()) == 0:
                continue

            # Locate header
            if m := re.match(r"^#{2,10}\s+(?P<rulenum>(\d\.)+)", line):
                log.debug(f"Found header: {m}")
                if rule_group:
                    metadata: dict[str, int | str] = {"chunk_index": chunk_index}
                    if source:
                        metadata["source"] = source
                    yield Document(
                        page_content="\n".join(rule_group),
                        metadata=metadata,
                    )
                    chunk_index += 1

                    # reset for next group
                    source = None
                    rule_group = []

                rule_num = m.group("rulenum").removesuffix(".")
                source = f"{self.file_name}: {rule_num}".strip()
                rule_group.append(line.strip())
            else:
                rule_group.append(line.strip())

        # Get final group
        if rule_group:
            metadata = {"chunk_index": chunk_index}
            if source:
                metadata["source"] = source
            yield Document(page_content="\n".join(rule_group), metadata=metadata)

    def lazy_load(self) -> Iterator[Document]:
        """A lazy loader that reads RSC Rule style documents."""
        with Path(self.file_path).open(encoding="utf-8") as fd:
            data = fd.read()
        yield from self._parse_content(data)

    async def alazy_load(self) -> AsyncIterator[Document]:
        """An async lazy loader for RSC Rule document style files."""
        async with aiofiles.open(self.file_path, encoding="utf-8") as fd:
            data = await fd.read()
        for doc in self._parse_content(data):
            yield doc
