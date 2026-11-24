"""Generate docs/commands.md, the reference page for every slash command.

Run `uv run python -m rsc.command_reference` after changing any command.
tests/test_command_reference.py fails while the committed page is stale.
"""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from discord import AppCommandOptionType, app_commands
from discord.utils import MISSING

from rsc.const import HIDDEN_COMMANDS
from rsc.enums import StaffPositions

AppCommand = app_commands.Command[Any, ..., Any] | app_commands.Group

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "commands.md"

PERMISSION_LABELS = {
    "administrator": "Administrator",
    "ban_members": "Ban Members",
    "kick_members": "Kick Members",
    "manage_channels": "Manage Channels",
    "manage_events": "Manage Events",
    "manage_guild": "Manage Server",
    "manage_messages": "Manage Messages",
    "manage_nicknames": "Manage Nicknames",
    "manage_roles": "Manage Roles",
    "manage_threads": "Manage Threads",
    "manage_webhooks": "Manage Webhooks",
    "moderate_members": "Timeout Members",
    "move_members": "Move Members",
    "mute_members": "Mute Members",
}

OPTION_TYPE_LABELS = {
    AppCommandOptionType.string: "Text",
    AppCommandOptionType.integer: "Whole number",
    AppCommandOptionType.number: "Number",
    AppCommandOptionType.boolean: "True/False",
    AppCommandOptionType.user: "Member",
    AppCommandOptionType.channel: "Channel",
    AppCommandOptionType.role: "Role",
    AppCommandOptionType.mentionable: "Member or role",
    AppCommandOptionType.attachment: "File",
}

INTRO = """\
# Command reference

Every slash command the bot registers, with its options and who can run it. \
For how and when to use them, see the [module pages](modules/README.md) and the [staff guide](staff-guide.md).

This page is generated from the code by `uv run python -m rsc.command_reference`. \
Do not edit it by hand. Change the command in code and run the generator again.

Server admins can change who sees a command under Server Settings > Integrations, \
so "Who can run it" is the default the bot ships with.
"""

# discord.py fills in this placeholder when a parameter has no describe() text.
NO_DESCRIPTION = "…"


@dataclass(frozen=True)
class ParamDoc:
    name: str
    type_label: str
    required: bool
    default: str | None
    description: str
    choices: tuple[str, ...]
    autocomplete: bool


@dataclass(frozen=True)
class Access:
    permissions: frozenset[str]
    staff_positions: frozenset[StaffPositions]
    owner_only: bool
    dm_allowed: bool


@dataclass(frozen=True)
class CommandDoc:
    qualified_name: str
    description: str
    params: tuple[ParamDoc, ...]
    access: Access


@dataclass(frozen=True)
class TopLevelDoc:
    name: str
    description: str
    is_group: bool
    commands: tuple[CommandDoc, ...]


def collect(top_level: Sequence[AppCommand]) -> list[TopLevelDoc]:
    docs = []
    for root in top_level:
        if root.name in HIDDEN_COMMANDS:
            continue
        leaves = sorted(_leaves(root), key=lambda c: c.qualified_name)
        docs.append(
            TopLevelDoc(
                name=root.name,
                description=root.description,
                is_group=isinstance(root, app_commands.Group),
                commands=tuple(_command_doc(c, root) for c in leaves),
            )
        )
    return sorted(docs, key=lambda d: d.name)


def render(docs: Sequence[TopLevelDoc]) -> str:
    lines = [INTRO, "## Index", "", "| Command | Description | Commands |", "|---|---|---|"]
    lines += [f"| [/{d.name}](#{_anchor('/' + d.name)}) | {_cell(d.description)} | {len(d.commands)} |" for d in docs]
    for d in docs:
        lines += ["", f"## /{d.name}", ""]
        if d.is_group:
            lines += [d.description]
            for c in d.commands:
                lines += ["", f"### /{c.qualified_name}", "", c.description, *_command_body(c)]
        else:
            (c,) = d.commands
            lines += [c.description, *_command_body(c)]
    return "\n".join(lines) + "\n"


def who_can_run(access: Access) -> str:
    if access.owner_only:
        return "Bot owner only"
    if access.staff_positions:
        positions = ", ".join(sorted(p.full_name for p in access.staff_positions))
        gate = f"Manage Server, or staff position: {positions}"
        others = _permission_labels(access.permissions - {"manage_guild"})
        return f"{_join(others)} and either {gate}" if others else gate
    if access.permissions:
        return _join(_permission_labels(access.permissions))
    return "Anyone"


def _leaves(node: AppCommand) -> Iterator[app_commands.Command[Any, ..., Any]]:
    if isinstance(node, app_commands.Command):
        yield node
        return
    for child in node.commands:
        yield from _leaves(child)


def _command_doc(command: app_commands.Command[Any, ..., Any], root: AppCommand) -> CommandDoc:
    return CommandDoc(
        qualified_name=command.qualified_name,
        description=command.description,
        params=tuple(_param_doc(p) for p in command.parameters),
        access=_access(command, root),
    )


def _access(command: app_commands.Command[Any, ..., Any], root: AppCommand) -> Access:
    # Discord only honours default_permissions on the top-level command, so subcommands inherit it.
    permissions = {name for name, granted in root.default_permissions or () if granted}
    for check in command.checks:
        if getattr(check, "__qualname__", "").startswith("has_permissions."):
            # discord.py keeps the required permissions only in the predicate's closure.
            for cell in getattr(check, "__closure__", None) or ():
                if isinstance(cell.cell_contents, dict):
                    permissions |= {name for name, granted in cell.cell_contents.items() if granted}
    callback = command.callback
    return Access(
        permissions=frozenset(permissions),
        staff_positions=frozenset(StaffPositions(v) for v in getattr(callback, "__rsc_elevated_positions__", ())),
        owner_only=getattr(callback, "__rsc_owner_only__", False),
        dm_allowed=not (command.guild_only or root.guild_only),
    )


def _param_doc(param: app_commands.Parameter) -> ParamDoc:
    choice_names = {c.value: c.name for c in param.choices}
    return ParamDoc(
        name=param.name,
        type_label=OPTION_TYPE_LABELS.get(param.type, param.type.name.title()),
        required=param.required,
        default=_default_label(param.default, choice_names),
        description="" if param.description == NO_DESCRIPTION else param.description,
        choices=tuple(choice_names.values()),
        autocomplete=bool(param.autocomplete),
    )


def _default_label(default: object, choice_names: dict[Any, str]) -> str | None:
    if default is None or default is MISSING:
        return None
    value = default.value if isinstance(default, Enum) else default
    return choice_names.get(value, str(value))


def _command_body(c: CommandDoc) -> list[str]:
    lines = ["", f"**Who can run it:** {who_can_run(c.access)}"]
    if c.access.dm_allowed:
        lines += ["", "Also works in direct messages with the bot."]
    if c.params:
        lines += ["", "| Option | Type | Required | Description |", "|---|---|---|---|"]
        lines += [f"| `{p.name}` | {p.type_label} | {'Yes' if p.required else 'No'} | {_cell(_param_description(p))} |" for p in c.params]
    return lines


def _param_description(p: ParamDoc) -> str:
    parts = [p.description]
    if p.choices:
        parts.append(f"One of: {', '.join(p.choices)}")
    if p.autocomplete:
        parts.append("Suggestions as you type")
    if p.default is not None:
        parts.append(f"Default: {p.default}")
    parts = [part for part in parts if part]
    return " ".join([*(_sentence(part) for part in parts[:-1]), *parts[-1:]])


def _sentence(text: str) -> str:
    return text if text.endswith((".", "?", "!")) else f"{text}."


def _permission_labels(permissions: frozenset[str]) -> list[str]:
    return sorted(PERMISSION_LABELS.get(p, p.replace("_", " ").title()) for p in permissions)


def _join(labels: list[str]) -> str:
    return " and ".join([", ".join(labels[:-1]), labels[-1]]) if len(labels) > 1 else labels[0]


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _anchor(heading: str) -> str:
    """The id GitHub gives a Markdown heading."""
    return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")


if __name__ == "__main__":
    from rsc.core import RSC

    OUTPUT.write_text(render(collect(RSC.__cog_app_commands__)))
    print(f"Wrote {OUTPUT}")
