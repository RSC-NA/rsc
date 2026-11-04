from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import ui
from tests.utils import api_exception
from rscapi.models.pending_series import PendingSeries

from rsc.ballchasing.views import FALLBACK_LOGO
from rsc.embeds import ErrorEmbed
from rsc.exceptions import RscException
from rsc.matches.matches import MatchMixIn
from rsc.matches.views import NO_UPCOMING_MATCH, MatchRefreshButton, PendingSeriesCard
from rsc.teams.teams import TeamMixIn

LEAGUE_ID = 1
STARTS = 1793676600
FEEDER_STARTS = 1793673900


def _create(cls, **attrs):
    saved = cls.__abstractmethods__
    cls.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(cls)
    finally:
        cls.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _series(home=True, feeder_date: str | None = "2026-11-02T21:45:00-05:00") -> PendingSeries:
    series = PendingSeries.from_dict(
        {
            "tier": "Master",
            "round": 2,
            "round_label": "Quarterfinals",
            "match_format": "BO5",
            "num_games": 5,
            "date": "2026-11-02T22:30:00-05:00",
            "home": home,
            "team": {"id": 1, "name": "Giraffes"},
            "possible_opponents": [{"id": 2, "name": "Wheelchairs"}, {"id": 3, "name": "Wet_Willies"}],
            "feeder_match": {
                "id": 9,
                "day": 1,
                "date": feeder_date,
                "match_format": "BO5",
                "home_team": {"id": 2, "name": "Wheelchairs"},
                "away_team": {"id": 3, "name": "Wet_Willies"},
            },
        }
    )
    assert series is not None
    return series


def _mixin(**attrs) -> MatchMixIn:
    team = MagicMock(id=1)
    team.franchise.id = 5
    defaults: dict[str, Any] = {
        "_api_conf": {},
        "_league": {},
        "teams": AsyncMock(return_value=[MagicMock(id=99), team]),
        "franchise_logo": AsyncMock(return_value="https://cdn.example/safari.png"),
        "season_id_for_number": AsyncMock(return_value=11),
    }
    defaults.update(attrs)
    return _create(MatchMixIn, **defaults)


async def _card(mock_guild, mixin: MatchMixIn | None = None, **kwargs) -> PendingSeriesCard:
    with patch("rsc.matches.matches.tier_color_by_name", AsyncMock(return_value=discord.Color.purple())):
        return await (mixin or _mixin()).pending_series_card(mock_guild, _series(**kwargs), team_id=1, asked=False)


def _container(view: ui.LayoutView) -> ui.Container:
    (container,) = view.children
    assert isinstance(container, ui.Container)
    return container


def _texts(item: ui.Container | ui.Section) -> list[str]:
    return [c.content for c in item.children if isinstance(c, ui.TextDisplay)]


def _section(view: ui.LayoutView) -> ui.Section:
    section = _container(view).children[0]
    assert isinstance(section, ui.Section)
    return section


def _buttons(view: ui.LayoutView) -> list[ui.Button]:
    items = [b for row in _container(view).children if isinstance(row, ui.ActionRow) for b in row.children]
    # Refresh is a DynamicItem wrapping its button
    buttons = [b.item if isinstance(b, ui.DynamicItem) else b for b in items]
    return [b for b in buttons if isinstance(b, ui.Button)]


class TestPendingSeriesApi:
    async def _call(self, mock_guild, **api_behaviour):
        mixin = _create(TeamMixIn, _api_conf={mock_guild.id: MagicMock()}, _league={mock_guild.id: 1})
        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            for name, value in api_behaviour.items():
                setattr(mock_api.teams_pending_series_retrieve, name, value)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                return await mixin.pending_series(mock_guild, 1)

    async def test_returns_the_series(self, mock_guild):
        series = _series()
        assert await self._call(mock_guild, return_value=series) is series

    async def test_no_pending_series_is_none(self, mock_guild):
        assert await self._call(mock_guild, side_effect=api_exception(404, "Not Found")) is None

    async def test_other_api_errors_raise(self, mock_guild):
        with pytest.raises(RscException):
            await self._call(mock_guild, side_effect=api_exception(500, "Error"))


class TestPendingSeriesCard:
    async def test_names_the_series_its_start_and_both_possible_opponents(self, mock_guild):
        view, files = (await _card(mock_guild)).render()

        section = _section(view)
        assert _texts(section) == [
            "-# Master · Quarterfinals · Best of 5",
            "## Giraffes vs TBD",
            r"Winner of **Wheelchairs** / **Wet\_Willies**",
        ]
        assert isinstance(section.accessory, ui.Thumbnail)
        assert section.accessory.media.url == "https://cdn.example/safari.png"
        assert files == []
        assert _texts(_container(view))[0] == f"<t:{STARTS}:F> · <t:{STARTS}:R>"
        assert _container(view).accent_colour == discord.Color.purple()

    async def test_the_lobby_comes_once_the_feeder_is_reported(self, mock_guild):
        view, _ = (await _card(mock_guild)).render()

        assert f"**Lobby** Posted once the Wildcard series (<t:{FEEDER_STARTS}:t>) is reported." in _texts(_container(view))

    async def test_a_feeder_with_no_date_still_reads(self, mock_guild):
        view, _ = (await _card(mock_guild, feeder_date=None)).render()

        assert "**Lobby** Posted once the Wildcard series is reported." in _texts(_container(view))

    @pytest.mark.parametrize(
        ("home", "expected"),
        [
            (True, "You're **home** whichever team wins."),
            (False, "You're **away** whichever team wins."),
            (None, "The higher seed is home, so it depends on who wins."),
        ],
    )
    async def test_home_side(self, mock_guild, home, expected):
        view, _ = (await _card(mock_guild, home=home)).render()

        assert _texts(_container(view))[-1] == expected

    async def test_refresh_then_bracket(self, mock_guild):
        mixin = _mixin(_api_conf={mock_guild.id: MagicMock(host="https://www.rscna.com/api/v1")}, _league={mock_guild.id: LEAGUE_ID})
        card = await _card(mock_guild, mixin)
        refresh, bracket = _buttons(card.render()[0])

        assert (refresh.label, refresh.style, refresh.custom_id) == ("Refresh", discord.ButtonStyle.primary, "match_refresh:1:0")
        assert (bracket.label, bracket.url) == ("Bracket", "https://www.rscna.com/playoffs/?tier=Master&league=1")

    async def test_no_site_no_bracket(self, mock_guild):
        (refresh,) = _buttons((await _card(mock_guild)).render()[0])

        assert refresh.label == "Refresh"

    async def test_logo_falls_back_to_the_server_icon(self, mock_guild):
        card = await _card(mock_guild, _mixin(franchise_logo=AsyncMock(return_value=None)))

        assert card.logo_url == mock_guild.icon.url

    async def test_no_logo_and_no_icon_attaches_the_rsc_logo(self, mock_guild):
        mock_guild.icon = None
        view, files = (await _card(mock_guild, _mixin(teams=AsyncMock(return_value=[])))).render()

        (logo,) = files
        assert logo.filename == FALLBACK_LOGO.name
        accessory = _section(view).accessory
        assert isinstance(accessory, ui.Thumbnail)
        assert accessory.media.url == f"attachment://{FALLBACK_LOGO.name}"


class TestMatchCommandFallsBackToThePendingSeries:
    async def _run(self, mock_guild, pending):
        mixin = _mixin(
            next_match=AsyncMock(return_value=None),
            pending_series=AsyncMock(return_value=pending),
            team_id_by_name=AsyncMock(return_value=1),
        )
        interaction = MagicMock()
        interaction.guild = mock_guild
        interaction.user = MagicMock(spec=discord.Member)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        with patch("rsc.matches.matches.tier_color_by_name", AsyncMock(return_value=discord.Color.purple())):
            # The unbound command callback, called the way discord.py calls it on the cog.
            match_cmd = cast("Any", MatchMixIn._match_cmd.callback)
            await match_cmd(mixin, interaction, team="Giraffes")
        call = interaction.followup.send.await_args
        assert call is not None
        return call.kwargs

    async def test_a_bye_seed_sees_its_pending_series(self, mock_guild):
        sent = await self._run(mock_guild, _series())

        assert _texts(_section(sent["view"]))[1] == "## Giraffes vs TBD"
        assert sent["ephemeral"] is True
        assert sent["allowed_mentions"].users is False
        # Named, but anyone may see a pending series: it has no lobby
        assert _buttons(sent["view"])[0].custom_id == "match_refresh:1:1"

    async def test_no_match_and_no_pending_series_says_so(self, mock_guild):
        sent = await self._run(mock_guild, None)

        assert sent["embed"].description == NO_UPCOMING_MATCH


class TestRefresh:
    async def _click(self, mock_guild, reply):
        cog = MagicMock()
        cog.match_reply = AsyncMock(return_value=reply)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = mock_guild
        interaction.user = MagicMock(spec=discord.Member)
        interaction.response = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()
        with patch("rsc.matches.views.ready_cog", AsyncMock(return_value=cog)):
            await MatchRefreshButton(1, asked=True).callback(interaction)
        interaction.response.defer.assert_awaited_once()
        cog.match_reply.assert_awaited_once_with(mock_guild, interaction.user, 1, asked=True)
        return interaction

    async def test_swaps_in_the_new_card(self, mock_guild):
        card = await _card(mock_guild)
        interaction = await self._click(mock_guild, card)

        call = interaction.edit_original_response.await_args
        assert call is not None
        assert _texts(_section(call.kwargs["view"]))[1] == "## Giraffes vs TBD"
        assert call.kwargs["attachments"] == []
        interaction.followup.send.assert_not_awaited()

    async def test_no_match_left_says_so_in_place(self, mock_guild):
        interaction = await self._click(mock_guild, None)

        call = interaction.edit_original_response.await_args
        assert call is not None
        assert _texts(_container(call.kwargs["view"])) == [NO_UPCOMING_MATCH]

    async def test_an_error_is_a_private_followup(self, mock_guild):
        error = ErrorEmbed(description="Only franchise managers can specify a team for match information.")
        interaction = await self._click(mock_guild, error)

        interaction.edit_original_response.assert_not_awaited()
        interaction.followup.send.assert_awaited_once_with(embed=error, ephemeral=True)
