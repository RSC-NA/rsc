from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from rsc.checks import bot_owner_required, configured_role_required, elevated_role_required
from rsc.command_reference import collect, render
from rsc.core import RSC
from rsc.enums import StaffPositions

COMMANDS_PAGE = Path(__file__).parent.parent / "docs" / "commands.md"


def test_committed_page_matches_the_code():
    assert render(collect(RSC.__cog_app_commands__)) == COMMANDS_PAGE.read_text(), (
        "docs/commands.md is out of date. Run `uv run python -m rsc.command_reference` and commit the result."
    )


class AccessCog(commands.Cog):
    _settings = app_commands.Group(
        name="settings",
        description="Settings",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )
    _stats = app_commands.Group(name="stats", description="Stats", guild_only=True)

    @_settings.command(name="secret", description="Owner only")
    @bot_owner_required()
    async def _secret(self, interaction: discord.Interaction): ...

    @_settings.command(name="roles", description="Needs roles too")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def _roles(self, interaction: discord.Interaction): ...

    @_stats.command(name="pull", description="Staff positions")
    @elevated_role_required(StaffPositions.NUMBERS, StaffPositions.ADMIN)
    async def _pull(self, interaction: discord.Interaction): ...

    @_stats.command(name="peaks", description="Configured role")
    @configured_role_required("Numbers Committee", lambda cog, guild: cog.numbers_role(guild))
    async def _peaks(self, interaction: discord.Interaction): ...

    @app_commands.command(name="kick", description="Permissions only")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.guild_only
    async def _kick(self, interaction: discord.Interaction): ...

    @app_commands.command(name="ping", description="Anyone, anywhere")
    async def _ping(self, interaction: discord.Interaction): ...


def _section(page: str, heading: str) -> str:
    start = page.index(f"{heading}\n")
    end = page.find("\n#", start + len(heading))
    return page[start : end if end != -1 else None]


def test_who_can_run_it():
    page = render(collect(AccessCog.__cog_app_commands__))

    assert "**Who can run it:** Bot owner only" in _section(page, "### /settings secret")
    assert "**Who can run it:** Manage Roles and Manage Server" in _section(page, "### /settings roles")
    assert "**Who can run it:** Manage Server, or staff position: Admin, Numbers\n" in _section(page, "### /stats pull")
    assert "**Who can run it:** Manage Server, or the Numbers Committee role\n" in _section(page, "### /stats peaks")
    assert "**Who can run it:** Kick Members\n" in _section(page, "## /kick")
    assert "**Who can run it:** Anyone\n" in _section(page, "## /ping")


def test_every_option_has_a_description_that_fits():
    """Discord shows an option's description as its only help, and allows 100 characters.

    discord.py fills in "…" for an option with no describe() text, and cuts a longer
    one to 100 characters ending in "…", so a trailing "…" means one or the other.
    """
    problems = []
    for root in RSC.__cog_app_commands__:
        nodes = [root, *root.walk_commands()] if isinstance(root, app_commands.Group) else [root]
        for node in nodes:
            if len(node.description) > 100:
                problems.append(f"/{node.qualified_name} description is {len(node.description)} characters")
            if isinstance(node, app_commands.Command):
                problems += [
                    f"/{node.qualified_name} {p.name} has no description, or one over 100 characters"
                    for p in node.parameters
                    if p.description.endswith("…")
                ]
    assert not problems, "\n".join(problems)


def test_only_commands_outside_guild_only_mention_direct_messages():
    page = render(collect(AccessCog.__cog_app_commands__))

    assert "direct messages" in _section(page, "## /ping")
    assert "direct messages" not in _section(page, "## /kick")
