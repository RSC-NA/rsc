import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ui import FileUpload, Label, TextDisplay, TextInput

from rsc.ballchasing.ballchasing import BallchasingMixIn
from rsc.ballchasing.modals import TITLE_MAX, ReportMatchModal, report_title, score_error
from rsc.enums import MatchFormat, MatchType

from .utils import command_callback


def _match(*, fmt=MatchFormat.GAME_SERIES, games=4, home="Quantum", away="Voltage", tier="Elite") -> MagicMock:
    match = MagicMock()
    match.match_format = fmt
    match.num_games = games
    match.match_type = MatchType.REGULAR
    match.day = 7
    match.home_team.name = home
    match.home_team.tier = tier
    match.away_team.name = away
    return match


def _summary(modal: ReportMatchModal) -> str:
    text = modal.children[0]
    assert isinstance(text, TextDisplay)
    return text.content


def _labels(modal: ReportMatchModal) -> list[Label]:
    return [c for c in modal.children if isinstance(c, Label)]


class TestCopy:
    def test_game_series(self):
        modal = ReportMatchModal("Quantum", "Voltage", match=_match())
        assert modal.title == "Report Quantum vs Voltage"
        assert _summary(modal) == (
            "**Elite** · Match Day 7 · 4-game series\n"
            "Wins must add up to 4. Attach one replay per game.\n"
            "-# Something wrong? DM the ModMail bot."
        )
        home, away, upload = _labels(modal)
        assert (home.text, home.description) == ("Quantum games won", "Home team")
        assert (away.text, away.description) == ("Voltage games won", "Away team")
        assert isinstance(home.component, TextInput) and home.component.placeholder == "Number from 0 to 4"
        assert (upload.text, upload.description) == ("Replay files", "All 4 .replay files from this series")
        assert isinstance(upload.component, FileUpload)

    def test_best_of(self):
        modal = ReportMatchModal("Quantum", "Voltage", match=_match(fmt=MatchFormat.BEST_OF_FIVE, games=5))
        assert _summary(modal).splitlines()[:2] == ["**Elite** · Match Day 7 · Best of 5", "First to 3 wins. Attach one replay per game."]
        assert _labels(modal)[2].description == "One .replay file per game played"

    def test_teams_only_when_the_lookup_was_slow(self):
        modal = ReportMatchModal("Quantum", "Voltage", day=7)
        assert _summary(modal) == (
            "**Match Day 7**\nEnter each team's wins and attach one replay per game.\n-# Something wrong? DM the ModMail bot."
        )
        home = _labels(modal)[0]
        assert isinstance(home.component, TextInput) and home.component.placeholder == "Number of games won"

    def test_swapped_teams_are_labelled_by_their_real_side(self):
        modal = ReportMatchModal("Voltage", "Quantum", match=_match())
        home, away, _ = _labels(modal)
        assert (home.text, home.description) == ("Voltage games won", "Away team")
        assert (away.text, away.description) == ("Quantum games won", "Home team")

    def test_long_names_fit_discord_limits(self):
        long = "A Very Long Franchise Team Name Indeed"
        modal = ReportMatchModal(long, long, match=_match(home=long, away=long))
        assert len(modal.title) <= TITLE_MAX
        assert all(len(label.text) <= 45 for label in _labels(modal))

    def test_title_falls_back_to_the_matchup(self):
        assert report_title("Quantum", "Voltage") == "Report Quantum vs Voltage"
        title = report_title("x" * 20, "y" * 20)
        assert title == f"{'x' * 20} vs {'y' * 20}"[:TITLE_MAX]


class TestScoreError:
    @pytest.mark.parametrize(("home", "away"), [(3, 1), (2, 2), (4, 0)])
    def test_game_series_must_total_the_games(self, home, away):
        assert score_error(home, away, _match()) is None

    def test_game_series_message(self):
        assert score_error(3, 3, _match()) == (
            "You entered 3\N{EN DASH}3, which is 6 games. This series has 4, so the wins must add up to 4."
        )

    @pytest.mark.parametrize(("home", "away"), [(3, 0), (3, 2), (2, 1)])
    def test_best_of_rule_is_unchanged(self, home, away):
        assert score_error(home, away, _match(fmt=MatchFormat.BEST_OF_FIVE, games=5)) is None

    def test_best_of_message(self):
        assert score_error(1, 1, _match(fmt=MatchFormat.BEST_OF_FIVE, games=5)) == (
            "You entered 1\N{EN DASH}1, which is 2 games. This is a best of 5, so the wins must add up to 3\N{EN DASH}5."
        )

    def test_unknown_game_count_is_not_checked(self):
        assert score_error(9, 9, _match(games=None)) is None


def _mixin(**attrs) -> BallchasingMixIn:
    saved = BallchasingMixIn.__abstractmethods__
    BallchasingMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(BallchasingMixIn)
    finally:
        BallchasingMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _interaction() -> MagicMock:
    interaction = MagicMock()
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.response.send_modal = AsyncMock()
    interaction.response.send_message = AsyncMock()
    return interaction


async def _run(mixin: BallchasingMixIn, interaction: MagicMock) -> None:
    # The modal "times out" at once, so the command stops right after opening it
    with patch("rsc.ballchasing.ballchasing.ReportMatchModal.wait", AsyncMock(return_value=True)):
        await command_callback(BallchasingMixIn._reportmatch_cmd)(mixin, interaction, "Quantum", "Voltage", None, False)


class TestEarlyLookup:
    async def test_found_match_shapes_the_modal(self):
        match = _match()
        interaction = _interaction()
        await _run(_mixin(_find_report_match=AsyncMock(return_value=match)), interaction)

        call = interaction.response.send_modal.await_args
        assert call is not None
        modal = call.args[0]
        assert isinstance(modal, ReportMatchModal)
        assert modal.match is match

    async def test_no_match_is_reported_before_the_modal(self):
        interaction = _interaction()
        await _run(_mixin(_find_report_match=AsyncMock(return_value=None)), interaction)

        interaction.response.send_modal.assert_not_awaited()
        reply = interaction.response.send_message.await_args
        assert reply is not None
        assert "No matches found for **Quantum** vs **Voltage**." in reply.kwargs["embed"].description
        assert reply.kwargs["ephemeral"] is True

    async def test_slow_lookup_opens_the_teams_only_modal(self):
        async def slow(*args, **kwargs):
            await asyncio.sleep(10)

        interaction = _interaction()
        with patch("rsc.ballchasing.ballchasing.EARLY_MATCH_LOOKUP", 0.01):
            await _run(_mixin(_find_report_match=slow), interaction)

        call = interaction.response.send_modal.await_args
        assert call is not None
        assert call.args[0].match is None
