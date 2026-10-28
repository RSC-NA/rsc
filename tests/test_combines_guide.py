from unittest.mock import AsyncMock, MagicMock

import discord
from discord import app_commands, ui

from rsc.combines.guide import (
    GUIDE_AUTHOR_ID,
    REPLAYS_PATH,
    ReplayLocationButton,
    combines_command_mentions,
    combines_guide,
)
from rsc.combines.manager import CombineManagerMixIn

MENTIONS = {
    "checkin": "</combines checkin:42>",
    "checkout": "</combines checkout:42>",
    "lobbyinfo": "</combines lobbyinfo:42>",
}


def _container(view: ui.LayoutView) -> ui.Container:
    (container,) = view.children
    assert isinstance(container, ui.Container)
    return container


def _texts(view: ui.LayoutView) -> list[str]:
    out = []
    for child in _container(view).children:
        if isinstance(child, ui.TextDisplay):
            out.append(child.content)
        elif isinstance(child, ui.Section):
            out.extend(t.content for t in child.children if isinstance(t, ui.TextDisplay))
    return out


class TestGuide:
    def test_steps_with_screenshots(self):
        view, files = combines_guide(MENTIONS, announcements="<#99>")
        sections = [c for c in _container(view).children if isinstance(c, ui.Section)]
        assert [f.filename for f in files] == [
            "combines_login.png",
            "combines_check_in.png",
            "combines_announcement.png",
            "combines_report.png",
        ]
        for section, file in zip(sections, files, strict=True):
            assert isinstance(section.accessory, ui.Thumbnail)
            assert section.accessory.media.url == f"attachment://{file.filename}"

        texts = _texts(view)
        assert texts[0] == "## How to play combines"
        assert "Opens 10 minutes before start. Hit **Check In** on the site or run </combines checkin:42>." in texts
        assert "Watch <#99>. Missed it? Run </combines lobbyinfo:42>." in texts
        assert texts[-2] == "### 5 · Queue again\nCheck in again for every series. Leave the queue with </combines checkout:42>."
        assert texts[-1] == f"-# Thanks to <@{GUIDE_AUTHOR_ID}> for putting this guide together"

    def test_commands_fall_back_to_inline_code(self):
        view, _ = combines_guide({})
        texts = _texts(view)
        assert any("run `/combines checkin`." in t for t in texts)
        assert "Watch #combines-announcements. Missed it? Run `/combines lobbyinfo`." in texts

    def test_buttons(self):
        view, _ = combines_guide(MENTIONS)
        (row,) = [c for c in _container(view).children if isinstance(c, ui.ActionRow)]
        link, replays = row.children
        assert isinstance(link, ui.Button) and (link.label, link.url) == ("Open Dev League", "https://devleague.rscna.com")
        assert isinstance(replays, ReplayLocationButton)
        assert replays.item.custom_id == "combines:replays"

    def test_within_component_limits(self):
        view, _ = combines_guide(MENTIONS)
        assert view.total_children_count <= 40


class TestReplayLocationButton:
    async def test_replies_privately_with_the_path(self):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await ReplayLocationButton().callback(interaction)

        reply = interaction.response.send_message.await_args
        assert reply is not None
        assert REPLAYS_PATH in reply.args[0]
        assert reply.kwargs["ephemeral"] is True


def _group(name: str) -> MagicMock:
    group = MagicMock(spec=app_commands.AppCommandGroup)
    group.name = name
    group.mention = f"</combines {name}:42>"
    return group


def _command(name: str, options: list) -> MagicMock:
    command = MagicMock(spec=app_commands.AppCommand)
    command.name = name
    command.options = options
    return command


class TestCommandMentions:
    def test_picks_the_guide_subcommands(self):
        subcommands = [_group("checkin"), _group("checkout"), _group("lobbyinfo"), _group("active")]
        commands = [_command("other", []), _command("combines", subcommands)]
        assert combines_command_mentions(commands) == MENTIONS

    def test_unsynced_combines_has_none(self):
        assert combines_command_mentions([_command("other", [])]) == {}


class TestSendGuide:
    async def test_sends_one_card_without_pings(self):
        saved = CombineManagerMixIn.__abstractmethods__
        CombineManagerMixIn.__abstractmethods__ = frozenset()
        try:
            m = object.__new__(CombineManagerMixIn)
        finally:
            CombineManagerMixIn.__abstractmethods__ = saved
        m.bot = MagicMock()
        m.bot.tree.fetch_commands = AsyncMock(return_value=[_command("combines", [_group("checkin")])])
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        announcements = MagicMock(spec=discord.TextChannel)
        announcements.mention = "<#99>"

        await m.send_combines_how_to_play(channel, announcements=announcements)

        send = channel.send.await_args
        assert send is not None
        assert send.kwargs["allowed_mentions"].users is False
        assert len(send.kwargs["files"]) == 4
        texts = _texts(send.kwargs["view"])
        assert any("</combines checkin:42>" in t for t in texts)
        assert any("Watch <#99>." in t for t in texts)
