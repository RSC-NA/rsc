import logging
import re
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import aiofiles

log = logging.getLogger("red.rsc.llm.loaders.ruleloader")

RULE_LINE_RE = re.compile(r"^(?:#{1,10}\s+)?(?:[-*+]\s+)?\**(?P<number>\d+(?:\.\d+)*)(?:\.)?\**\s*(?P<text>.*)$")
GLOSSARY_ENTRY_RE = re.compile(r'(?P<terms>(?:"[^"]+"(?:,\s*)?)+)\s*-\s*(?P<definition>.+)')
HEADING_PREFIX_RE = re.compile(r"^(#{1,10})\s+")


@dataclass(slots=True)
class RuleDocument:
    """A parsed rule or glossary entry.

    Structurally compatible with the `langchain_core` `Document` this loader
    used to emit, so consumers only touching `.page_content` / `.metadata` are
    unaffected.
    """

    page_content: str
    metadata: dict[str, int | str]


@dataclass
class RuleNode:
    number: str
    title: str
    lines: list[str]
    order: int
    # Markdown heading depth of the line that introduced this rule, or 0 when it
    # was a plain body line. Only heading nodes are real section titles, which
    # is what a table of contents needs -- depth alone is not a proxy for it,
    # since some books number ordinary prose sentences several levels deep.
    heading_level: int = 0


@dataclass
class GlossaryEntry:
    terms: list[str]
    definition_parts: list[str]
    order: int


class RuleDocumentLoader:
    """RSC Rule Document style loader"""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.file_name = Path(file_path).stem.replace("-", " ")

    def _read_file(self) -> str:
        with Path(self.file_path).open(encoding="utf-8") as fd:
            return fd.read()

    @staticmethod
    def _normalize_line(line: str) -> str:
        return line.replace("\u200b", "").strip()

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "entry"

    @staticmethod
    def _parent_rule_number(rule_number: str) -> str:
        if "." not in rule_number:
            return ""
        return rule_number.rsplit(".", maxsplit=1)[0]

    @staticmethod
    def _ancestor_rule_numbers(rule_number: str) -> list[str]:
        parts = rule_number.split(".")
        return [".".join(parts[:idx]) for idx in range(1, len(parts))]

    @staticmethod
    def _is_glossary_heading(line: str) -> bool:
        normalized = re.sub(r"[#*_]", "", line).strip().lower()
        return normalized == "general glossary"

    @staticmethod
    def _is_terminal_heading(line: str) -> bool:
        normalized = re.sub(r"[#*_]", "", line).strip().lower()
        return normalized in {"disclaimer", "release:", "release", "changelog"}

    @staticmethod
    def _match_rule_line(line: str) -> tuple[str, str] | None:
        line = RuleDocumentLoader._normalize_line(line)
        if not line or line.startswith("|"):
            return None
        match = RULE_LINE_RE.match(line)
        if not match:
            return None
        number = match.group("number").removesuffix(".")
        text = match.group("text").strip().strip("*").strip()
        return number, text

    @staticmethod
    def _heading_level(line: str) -> int:
        """Markdown heading depth of a line, or 0 if it is not a heading."""
        match = HEADING_PREFIX_RE.match(RuleDocumentLoader._normalize_line(line))
        return len(match.group(1)) if match else 0

    def parse_rule_nodes(self, data: str) -> list[RuleNode]:
        """Parse rule text into ordered nodes.

        Public so callers building their own index (rather than documents) do
        not have to reach for the private parser.
        """
        return self._parse_rule_nodes(data)

    def _parse_rule_nodes(self, data: str) -> list[RuleNode]:
        nodes: dict[str, RuleNode] = {}
        current_number = ""
        started_rules = False

        for line in data.splitlines():
            normalized = self._normalize_line(line)
            if not normalized:
                continue
            if self._is_terminal_heading(normalized):
                break

            matched_rule = self._match_rule_line(normalized)
            if matched_rule:
                number, title = matched_rule
                heading_level = self._heading_level(normalized)
                started_rules = True
                current_number = number
                if number not in nodes:
                    nodes[number] = RuleNode(
                        number=number,
                        title=title,
                        lines=[normalized],
                        order=len(nodes),
                        heading_level=heading_level,
                    )
                else:
                    nodes[number].lines.append(normalized)
                    if title and not nodes[number].title:
                        nodes[number].title = title
                    # A rule can recur as both a heading and a body reference.
                    # Keep the shallowest heading seen so the TOC reflects the
                    # real section level rather than whichever line came last.
                    if heading_level and (not nodes[number].heading_level or heading_level < nodes[number].heading_level):
                        nodes[number].heading_level = heading_level
                continue

            if started_rules and current_number:
                nodes[current_number].lines.append(normalized)

        return sorted(nodes.values(), key=lambda node: node.order)

    def _rule_path(self, node: RuleNode, nodes_by_number: dict[str, RuleNode]) -> str:
        path_parts = []
        for rule_number in [*self._ancestor_rule_numbers(node.number), node.number]:
            path_node = nodes_by_number.get(rule_number)
            if not path_node:
                path_parts.append(rule_number)
                continue
            title = f" {path_node.title}" if path_node.title else ""
            path_parts.append(f"{rule_number}{title}".strip())
        return " > ".join(path_parts)

    def _direct_child_summaries(self, node: RuleNode, nodes: list[RuleNode]) -> list[str]:
        summaries = []
        for child in nodes:
            if self._parent_rule_number(child.number) == node.number:
                summary = f"- {child.number}"
                if child.title:
                    summary = f"{summary}: {child.title}"
                summaries.append(summary)
        return summaries

    def _build_rule_content(self, node: RuleNode, nodes: list[RuleNode], nodes_by_number: dict[str, RuleNode]) -> str:
        content_parts = [
            f"Rule: {node.number}",
            f"Rule Path: {self._rule_path(node, nodes_by_number)}",
        ]
        parent_rule = self._parent_rule_number(node.number)
        if parent_rule:
            content_parts.append(f"Parent Rule: {parent_rule}")
        content_parts.append("Text:")
        content_parts.extend(node.lines)

        child_summaries = self._direct_child_summaries(node, nodes)
        if child_summaries:
            content_parts.append("Direct Subrules:")
            content_parts.extend(child_summaries)

        return "\n".join(content_parts)

    def _parse_content(self, data: str) -> Iterator[RuleDocument]:
        """Parse RSC Rule document content and yield Documents."""
        nodes = self._parse_rule_nodes(data)
        nodes_by_number = {node.number: node for node in nodes}

        for chunk_index, node in enumerate(nodes):
            parent_rule_number = self._parent_rule_number(node.number)
            ancestor_rule_numbers = self._ancestor_rule_numbers(node.number)
            metadata: dict[str, int | str] = {
                "chunk_index": chunk_index,
                "title": self.file_name,
                "source": f"{self.file_name}: {node.number}",
                "id": node.number,
                "rule_number": node.number,
                "parent_rule_number": parent_rule_number,
                "ancestor_rule_numbers": "|".join(ancestor_rule_numbers),
                "depth": len(node.number.split(".")),
                "rule_title": node.title,
                "rule_path": self._rule_path(node, nodes_by_number),
            }
            yield RuleDocument(
                page_content=self._build_rule_content(node, nodes, nodes_by_number),
                metadata=metadata,
            )

    def _parse_glossary_entries(self, data: str) -> list[GlossaryEntry]:
        entries: list[GlossaryEntry] = []
        in_glossary = False

        for line in data.splitlines():
            normalized = self._normalize_line(line)
            if not normalized:
                continue
            if self._is_glossary_heading(normalized):
                in_glossary = True
                continue
            if not in_glossary:
                continue
            if self._match_rule_line(normalized):
                break

            match = GLOSSARY_ENTRY_RE.match(normalized)
            if match:
                terms = re.findall(r'"([^"]+)"', match.group("terms"))
                if terms:
                    entries.append(
                        GlossaryEntry(
                            terms=terms,
                            definition_parts=[match.group("definition").strip()],
                            order=len(entries),
                        )
                    )
                continue

            if entries and not normalized.startswith("#"):
                entries[-1].definition_parts.append(normalized)

        return entries

    def _parse_glossary_content(self, data: str) -> Iterator[RuleDocument]:
        for entry in self._parse_glossary_entries(data):
            term = entry.terms[0]
            aliases = entry.terms[1:]
            definition = " ".join(entry.definition_parts)
            content_parts = [
                f"Glossary Term: {term}",
            ]
            if aliases:
                content_parts.append(f"Aliases: {', '.join(aliases)}")
            content_parts.append(f"Definition: {definition}")
            metadata: dict[str, int | str] = {
                "chunk_index": entry.order,
                "title": self.file_name,
                "source": f"{self.file_name}: Glossary: {term}",
                "id": f"glossary:{self._slug(term)}",
                "term": term,
                "aliases": "|".join(aliases),
            }
            yield RuleDocument(page_content="\n".join(content_parts), metadata=metadata)

    def lazy_load(self) -> Iterator[RuleDocument]:
        """A lazy loader that reads RSC Rule style documents."""
        yield from self._parse_content(self._read_file())

    def lazy_load_glossary(self) -> Iterator[RuleDocument]:
        """A lazy loader that reads glossary definitions from an RSC rule document."""
        yield from self._parse_glossary_content(self._read_file())

    async def alazy_load(self) -> AsyncIterator[RuleDocument]:
        """An async lazy loader for RSC Rule document style files."""
        async with aiofiles.open(self.file_path, encoding="utf-8") as fd:
            data = await fd.read()
        for doc in self._parse_content(data):
            yield doc

    async def alazy_load_glossary(self) -> AsyncIterator[RuleDocument]:
        """An async lazy loader for glossary definitions in an RSC rule document."""
        async with aiofiles.open(self.file_path, encoding="utf-8") as fd:
            data = await fd.read()
        for doc in self._parse_glossary_content(data):
            yield doc
