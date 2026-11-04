"""`/admin matches fix`: correcting a reported match or playoff series result."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import discord
import pytest
from discord import ui
from rscapi.models.base_team import BaseTeam
from rscapi.models.match import Match
from rscapi.models.match_format_enum import MatchFormatEnum
from rscapi.models.match_results import MatchResults
from rscapi.models.match_team import MatchTeam
from rscapi.models.match_type_enum import MatchTypeEnum
from rscapi.models.pending_series import PendingSeries
from rscapi.models.pending_series_feeder import PendingSeriesFeeder

from rsc.admin.match import AdminMatchMixIn
from rsc.admin.match_fix import MeetingPickerView
from rsc.exceptions import RscException
from rsc.views import ConfirmLayoutView

from .utils import command_callback

fix = command_callback(AdminMatchMixIn._matches_fix_cmd)

LOGO = "https://cdn.example/bravo.png"
MATCH_PAGE = "https://rsc.example/matches/10"
SCORE_2_3 = "2\N{NO-BREAK SPACE}\N{EN DASH}\N{WORD JOINER}\N{NO-BREAK SPACE}3"
SCORE_3_1 = "3\N{NO-BREAK SPACE}\N{EN DASH}\N{WORD JOINER}\N{NO-BREAK SPACE}1"
FINALS_AT = datetime(2026, 11, 6, 2, 0, tzinfo=UTC)


def _create_mixin(**attrs):
    """Create an AdminMatchMixIn instance bypassing ABC restrictions."""
    saved = AdminMatchMixIn.__abstractmethods__
    AdminMatchMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(AdminMatchMixIn)
    finally:
        AdminMatchMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _match(
    *,
    id: int = 10,
    home: tuple[int, str] = (1, "Alpha"),
    away: tuple[int, str] = (2, "Bravo"),
    day: int = 3,
    match_type: MatchTypeEnum = MatchTypeEnum.PST,
    score: tuple[int, int] | None = (3, 1),
    match_format: MatchFormatEnum = MatchFormatEnum.BO5,
    num_games: int = 5,
    date: datetime | None = None,
    tier: str | None = "Elite",
) -> Match:
    return Match(
        id=id,
        day=day,
        num_games=num_games,
        match_format=match_format,
        match_type=match_type,
        home_team=MatchTeam(id=home[0], name=home[1], tier=tier),
        away_team=MatchTeam(id=away[0], name=away[1], tier=tier),
        results=MatchResults(home_wins=score[0], away_wins=score[1], ballchasing_group="stored-group") if score else None,
        date=date,
    )


def _regular(*, id: int = 30, day: int = 7, score: tuple[int, int] | None = (3, 1), match_type=MatchTypeEnum.REG, **kwargs) -> Match:
    return _match(id=id, day=day, match_type=match_type, score=score, match_format=MatchFormatEnum.GMS, num_games=4, **kwargs)


def _finals(home: tuple[int, str], *, score: tuple[int, int] | None = None, date: datetime | None = FINALS_AT) -> Match:
    return _match(id=40, home=home, away=(3, "Charlie"), day=4, score=score, date=date)


def _pending() -> PendingSeries:
    return PendingSeries.model_validate(
        {
            "tier": "Elite",
            "round": 4,
            "round_label": "Finals",
            "match_format": "BO5",
            "num_games": 5,
            "date": None,
            "home": None,
            "team": {"id": 2, "name": "Bravo"},
            "possible_opponents": [{"id": 3, "name": "Charlie"}, {"id": 4, "name": "Delta"}],
            "feeder_match": PendingSeriesFeeder(
                id=20, day=3, home_team=BaseTeam(id=3, name="Charlie"), away_team=BaseTeam(id=4, name="Delta")
            ),
        }
    )


@pytest.fixture
def interaction():
    i = MagicMock(spec=discord.Interaction)
    i.guild = MagicMock(spec=discord.Guild)
    i.user = MagicMock(spec=discord.Member)
    i.response = MagicMock()
    i.response.defer = AsyncMock()
    i.followup = MagicMock()
    i.followup.send = AsyncMock()
    i.edit_original_response = AsyncMock()
    return i


@pytest.fixture
def mixin():
    return _create_mixin(
        find_match=AsyncMock(return_value=[_match()]),
        report_match=AsyncMock(),
        pending_series=AsyncMock(return_value=None),
        winning_logo_url=AsyncMock(return_value=LOGO),
        match_page_link=AsyncMock(return_value=MATCH_PAGE),
        timezone=AsyncMock(return_value=ZoneInfo("America/New_York")),
    )


def _lookups(mixin, *, old_next: list[Match] | Exception = [], new_next: list[Match] | Exception = []) -> None:  # noqa: B006
    """The series lookup returns the fixed series, then the old winner's and the new winner's next-round lookups."""
    mixin.find_match.side_effect = [[_match()], old_next, new_next]


class Admin:
    """Plays the admin: answers the picker and the confirm as each is shown, and keeps every message shown."""

    def __init__(self, interaction, *, pick: int | None = None, click: str | None = "Save"):
        self.pick = pick
        self.click = click
        self.shown: list[tuple[str, ui.LayoutView | None]] = []
        self.click_reply = MagicMock(spec=discord.Interaction)
        self.click_reply.user = interaction.user
        self.click_reply.response = MagicMock()
        self.click_reply.response.defer = AsyncMock()
        self.click_reply.response.edit_message = AsyncMock()
        interaction.followup.send.side_effect = self._on("send")
        interaction.edit_original_response.side_effect = self._on("edit")

    def _on(self, method: str):
        async def shown(*args, view=None, **kwargs):
            self.shown.append((method, view))
            if isinstance(view, MeetingPickerView):
                if self.pick is None:
                    view.stop()
                    return
                select = next(c for c in view.walk_children() if isinstance(c, ui.Select))
                select._values = [str(self.pick)]
                await select.callback(self.click_reply)
            elif isinstance(view, ConfirmLayoutView):
                if self.click is None:
                    view.stop()
                    return
                await next(b for b in _buttons(view) if b.label == self.click).callback(self.click_reply)

        return shown

    def views(self, kind: type) -> list:
        return [v for _, v in self.shown if isinstance(v, kind)]

    @property
    def confirm(self) -> ConfirmLayoutView:
        [view] = self.views(ConfirmLayoutView)
        return view

    @property
    def last(self) -> tuple[str, ui.LayoutView]:
        method, view = self.shown[-1]
        assert view is not None
        return method, view


def _container(view: ui.LayoutView) -> ui.Container:
    [container] = view.children
    assert isinstance(container, ui.Container)
    return container


def _texts(view: ui.LayoutView) -> list[str]:
    return [c.content for c in view.walk_children() if isinstance(c, ui.TextDisplay)]


def _buttons(view: ui.LayoutView) -> list[ui.Button]:
    return [c for c in view.walk_children() if isinstance(c, ui.Button)]


def _kinds(view: ui.LayoutView) -> list[str]:
    """The container's top-level components, by kind."""
    return [type(c).__name__ for c in _container(view).children]


def _body(view: ui.LayoutView) -> list[str]:
    """The texts below the headline."""
    return [c.content for c in _container(view).children if isinstance(c, ui.TextDisplay)]


def _select(view: MeetingPickerView) -> ui.Select:
    return next(c for c in view.walk_children() if isinstance(c, ui.Select))


class TestSave:
    async def test_save_overrides_with_oriented_scores_and_stored_group(self, mixin, interaction):
        # Reporter names the API's away team first; Bravo actually won 3-2.
        Admin(interaction)
        await fix(mixin, interaction, home="Bravo", away="Alpha", home_wins=3, away_wins=2)

        mixin.report_match.assert_awaited_once_with(
            interaction.guild,
            match_id=10,
            ballchasing_group="stored-group",
            home_score=2,
            away_score=3,
            executor=interaction.user,
            override=True,
        )

    async def test_confirm_offers_save_and_cancel(self, mixin, interaction):
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        buttons = [(b.label, b.style) for b in _buttons(admin.confirm)]
        assert buttons == [("Save", discord.ButtonStyle.success), ("Cancel", discord.ButtonStyle.secondary)]
        assert _container(admin.confirm).accent_colour == discord.Colour.orange()

    async def test_cancel_changes_nothing(self, mixin, interaction):
        admin = Admin(interaction, click="Cancel")
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        mixin.report_match.assert_not_awaited()
        cancelled = admin.click_reply.response.edit_message.await_args.kwargs["view"]
        assert _texts(cancelled) == ["## Cancelled", "The result is unchanged."]
        assert _container(cancelled).accent_colour == discord.Colour.red()

    async def test_timeout_changes_nothing(self, mixin, interaction):
        Admin(interaction, click=None)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        mixin.report_match.assert_not_awaited()

    async def test_api_refusal_replaces_the_confirm(self, mixin, interaction):
        admin = Admin(interaction)
        mixin.report_match.side_effect = RscException(message="You need the Stats or Admin staff position.")
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        method, view = admin.last
        assert method == "edit"
        assert _texts(view) == ["### The API refused the fix", "You need the Stats or Admin staff position."]
        assert _container(view).accent_colour == discord.Colour.red()


class TestRefused:
    async def test_unreported_series_is_refused(self, mixin, interaction):
        mixin.find_match.return_value = [_match(score=None)]
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        assert admin.views(ConfirmLayoutView) == []
        mixin.report_match.assert_not_awaited()
        assert "/reportmatch" in interaction.followup.send.await_args.kwargs["embed"].description

    async def test_same_score_has_nothing_to_change(self, mixin, interaction):
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Bravo", away="Alpha", home_wins=1, away_wins=3)

        assert admin.views(ConfirmLayoutView) == []
        mixin.report_match.assert_not_awaited()
        method, view = admin.last
        assert method == "send"
        assert _texts(view) == ["### Nothing to change", "Alpha vs Bravo is already recorded as 3\N{EN DASH}1."]
        assert _container(view).accent_colour == discord.Colour.greyple()

    async def test_impossible_score_is_refused(self, mixin, interaction):
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=1, away_wins=1)

        assert admin.views(ConfirmLayoutView) == []
        mixin.report_match.assert_not_awaited()
        _, view = admin.last
        title, reason = _texts(view)
        assert title == "### That score doesn't fit"
        assert reason.startswith("You entered 1\N{EN DASH}1, which is 2 games.")
        assert _container(view).accent_colour == discord.Colour.red()


class TestHeadline:
    async def test_confirm_shows_the_new_score_over_the_recorded_one(self, mixin, interaction):
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        [section] = [c for c in _container(admin.confirm).children if isinstance(c, ui.Section)]
        assert [t.content for t in section.children if isinstance(t, ui.TextDisplay)] == [
            "-# Elite · Semifinals · Fixing the result",
            f"## Alpha {SCORE_2_3} Bravo",
            f"Recorded as ~~{SCORE_3_1}~~",
        ]
        assert isinstance(section.accessory, ui.Thumbnail)
        assert section.accessory.media.url == LOGO
        mixin.winning_logo_url.assert_awaited_once_with(interaction.guild, mixin.find_match.return_value[0], 2, 3)

    async def test_result_shows_the_corrected_score(self, mixin, interaction):
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        _, view = admin.last
        [section] = [c for c in _container(view).children if isinstance(c, ui.Section)]
        assert [t.content for t in section.children if isinstance(t, ui.TextDisplay)] == [
            "-# Elite · Semifinals · Corrected",
            f"## Alpha {SCORE_2_3} Bravo",
        ]
        assert isinstance(section.accessory, ui.Thumbnail)
        assert section.accessory.media.url == LOGO

    async def test_no_logo_falls_back_to_plain_text(self, mixin, interaction):
        mixin.winning_logo_url.return_value = None
        mixin.find_match.return_value = [_match(tier=None)]
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        for view, suffix in ((admin.confirm, "Fixing the result"), (admin.last[1], "Corrected")):
            assert "Section" not in _kinds(view)
            assert _texts(view)[:2] == [f"-# Semifinals · {suffix}", f"## Alpha {SCORE_2_3} Bravo"]
        assert interaction.followup.send.await_args.kwargs.get("files") is None

    async def test_team_names_are_escaped(self, mixin, interaction):
        mixin.find_match.return_value = [_match(home=(1, "Al_pha"))]
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Al_pha", away="Bravo", home_wins=2, away_wins=3)

        assert f"## Al\\_pha {SCORE_2_3} Bravo" in _texts(admin.confirm)


def _consequence(admin: Admin) -> list[str]:
    """The confirm's texts after its separator."""
    children = _container(admin.confirm).children
    after = children[[type(c) for c in children].index(ui.Separator) + 1 :]
    return [c.content for c in after if isinstance(c, ui.TextDisplay)]


class TestConfirmConsequence:
    async def test_new_winner_takes_the_old_winners_unplayed_next_series(self, mixin, interaction):
        # The regular season meeting on the same day number is not the next series.
        _lookups(mixin, old_next=[_regular(home=(1, "Alpha"), away=(5, "Echo"), day=4, score=None), _finals((1, "Alpha"))])
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        assert _consequence(admin) == [
            (
                "**Bravo** win the series instead. They take Alpha's place in the **Finals** against **Charlie**,"
                " unless the Finals have been played."
            )
        ]
        old_lookup = mixin.find_match.await_args_list[1].kwargs
        assert (old_lookup["teams"], old_lookup["day"]) == (["Alpha"], 4)

    async def test_possessive_of_a_name_ending_in_s(self, mixin, interaction):
        mixin.find_match.side_effect = [[_match(home=(1, "Aeronauts"))], [], []]
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Aeronauts", away="Bravo", home_wins=2, away_wins=3)

        assert _consequence(admin) == ["**Bravo** win the series instead and take Aeronauts' place in the **Finals**."]

    async def test_old_winner_already_played_the_next_series(self, mixin, interaction):
        _lookups(mixin, old_next=[_finals((1, "Alpha"), score=(3, 0))])
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        assert _consequence(admin) == [
            (
                "**Bravo** win the series instead. Alpha already played the Finals, so the API can't move Bravo into it."
                " Fix the Finals by hand."
            )
        ]

    @pytest.mark.parametrize("old_next", [[], RscException(message="down")], ids=["no next series yet", "lookup failed"])
    async def test_next_series_not_found(self, mixin, interaction, old_next):
        _lookups(mixin, old_next=old_next)
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        assert _consequence(admin) == ["**Bravo** win the series instead and take Alpha's place in the **Finals**."]
        assert mixin.report_match.await_args.kwargs["away_score"] == 3

    async def test_new_winner_of_the_finals(self, mixin, interaction):
        mixin.find_match.return_value = [_match(day=4)]
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        assert _consequence(admin) == ["**Bravo** win the Finals instead."]
        assert mixin.find_match.await_count == 1

    async def test_same_winner_leaves_the_bracket_alone(self, mixin, interaction):
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=3, away_wins=2)

        assert _consequence(admin) == ["**Alpha** still win the series, so the bracket doesn't change."]

    async def test_no_winner_at_the_new_score(self, mixin, interaction):
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=1)

        assert _consequence(admin) == ["No team has won the series at this score, so the next series stays as it was."]

    @pytest.mark.parametrize(("tier", "whose"), [("Elite", "Elite's"), (None, "this tier's")])
    async def test_regular_season_warns_of_reseeding(self, mixin, interaction, tier, whose):
        mixin.find_match.return_value = [_regular(tier=tier)]
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=2)

        assert _consequence(admin) == [
            (
                f"-# Standings update from this result. If {whose} playoffs are already seeded,"
                " the seeds can change and unplayed playoff matches move to follow."
            )
        ]
        assert mixin.report_match.await_args.kwargs["match_id"] == 30

    async def test_preseason_says_nothing_more(self, mixin, interaction):
        mixin.find_match.return_value = [_regular(day=2, match_type=MatchTypeEnum.PRE)]
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=2)

        assert _kinds(admin.confirm) == ["Section", "ActionRow"]
        assert "-# Elite · Preseason 2 · Fixing the result" in _texts(admin.confirm)


class TestResult:
    async def test_names_the_next_series_the_winner_moved_into(self, mixin, interaction):
        _lookups(mixin, new_next=[_regular(home=(2, "Bravo"), away=(5, "Echo"), day=4, score=None), _finals((2, "Bravo"))])
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        _, view = admin.last
        assert _kinds(view) == ["Section", "Separator", "TextDisplay", "TextDisplay", "Separator", "ActionRow"]
        assert _body(view) == ["### Next series", f"**Finals** · Bravo vs Charlie\n<t:{int(FINALS_AT.timestamp())}:F>"]
        assert _container(view).accent_colour == discord.Colour.green()
        new_lookup = mixin.find_match.await_args_list[2].kwargs
        assert (new_lookup["teams"], new_lookup["day"]) == (["Bravo"], 4)

    async def test_undated_next_series_has_no_time(self, mixin, interaction):
        _lookups(mixin, new_next=[_finals((2, "Bravo"), date=None)])
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        assert _body(admin.last[1]) == ["### Next series", "**Finals** · Bravo vs Charlie"]

    async def test_names_the_series_a_pending_winner_waits_on(self, mixin, interaction):
        _lookups(mixin)
        mixin.pending_series.return_value = _pending()
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        _, view = admin.last
        assert _body(view) == ["### Next series", "**Bravo** wait on the winner of **Charlie** vs **Delta** for the **Finals**."]
        assert _container(view).accent_colour == discord.Colour.green()

    async def test_warns_when_the_next_series_was_already_played(self, mixin, interaction):
        _lookups(mixin)
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        _, view = admin.last
        assert _body(view) == [
            "### Finals not moved",
            "Alpha already played the Finals, so the API left it as it was. Fix the Finals by hand.",
        ]
        assert _container(view).accent_colour == discord.Colour.yellow()
        assert [(b.label, b.url) for b in _buttons(view)] == [("Match page", MATCH_PAGE)]

    async def test_warns_when_the_next_series_could_not_be_checked(self, mixin, interaction):
        _lookups(mixin, new_next=RscException(message="Service unavailable"))
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        _, view = admin.last
        assert _body(view)[-1] == "The score was saved, but the next round could not be checked: Service unavailable"
        assert _container(view).accent_colour == discord.Colour.yellow()

    @pytest.mark.parametrize(
        ("home_wins", "away_wins", "day"),
        [(2, 3, 4), (3, 2, 3)],
        ids=["new winner of the finals", "same winner"],
    )
    async def test_no_next_series_to_show(self, mixin, interaction, home_wins, away_wins, day):
        mixin.find_match.return_value = [_match(day=day)]
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=home_wins, away_wins=away_wins)

        _, view = admin.last
        assert _kinds(view) == ["Section", "Separator", "ActionRow"]
        assert _container(view).accent_colour == discord.Colour.green()
        mixin.pending_series.assert_not_awaited()

    async def test_no_winner_at_the_new_score(self, mixin, interaction):
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=1)

        _, view = admin.last
        assert _body(view) == ["-# No team has won the series at this score, so the next series stays as it was."]
        assert _container(view).accent_colour == discord.Colour.green()

    async def test_regular_season(self, mixin, interaction):
        mixin.find_match.return_value = [_regular()]
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=2)

        _, view = admin.last
        assert _kinds(view) == ["Section", "TextDisplay", "Separator", "ActionRow"]
        assert _body(view) == ["-# Standings and playoff seeds update from this result."]
        assert "-# Elite · Match Day 7 · Corrected" in _texts(view)
        assert [(b.label, b.url) for b in _buttons(view)] == [("Match page", MATCH_PAGE)]
        mixin.pending_series.assert_not_awaited()

    async def test_preseason_is_the_headline_and_match_page(self, mixin, interaction):
        mixin.find_match.return_value = [_regular(day=2, match_type=MatchTypeEnum.PRE)]
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=2)

        _, view = admin.last
        assert _kinds(view) == ["Section", "Separator", "ActionRow"]
        assert [(b.label, b.url) for b in _buttons(view)] == [("Match page", MATCH_PAGE)]

    async def test_no_match_page_no_buttons(self, mixin, interaction):
        _lookups(mixin)
        mixin.match_page_link.return_value = None
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        _, view = admin.last
        assert _buttons(view) == []
        assert _kinds(view) == ["Section", "Separator", "TextDisplay", "TextDisplay"]

    async def test_failed_match_page_lookup_still_shows_the_result(self, mixin, interaction):
        _lookups(mixin)
        mixin.match_page_link.side_effect = RscException(message="down")
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        method, view = admin.last
        assert method == "edit"
        assert "-# Elite · Semifinals · Corrected" in _texts(view)
        assert _buttons(view) == []

    async def test_failed_logo_lookup_still_saves(self, mixin, interaction):
        mixin.winning_logo_url.side_effect = RscException(message="down")
        interaction.guild.icon = None
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        assert "Section" not in _kinds(admin.confirm)
        mixin.report_match.assert_awaited_once()

    async def test_result_replaces_the_confirm(self, mixin, interaction):
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=3)

        assert [m for m, _ in admin.shown] == ["send", "edit"]
        assert admin.shown[0][1] is admin.confirm


class TestMeetingPicker:
    @pytest.fixture
    def meetings(self):
        return [
            _regular(id=1, day=3, score=(4, 0), date=datetime(2026, 9, 9, 1, 0, tzinfo=UTC)),
            _regular(id=2, day=9, score=None),
            _match(id=3, day=3, home=(2, "Bravo"), away=(1, "Alpha"), date=datetime(2026, 11, 4, 2, 0, tzinfo=UTC)),
        ]

    async def test_offers_the_reported_meetings_newest_first(self, mixin, interaction, meetings):
        mixin.find_match.return_value = meetings
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=2)

        [picker] = admin.views(MeetingPickerView)
        # Dates are in the server's timezone: 02:00 UTC on Nov 4 is Nov 3 in New York.
        assert [(o.label, o.description, o.value) for o in _select(picker).options] == [
            ("Semifinals", "Bravo 3\N{EN DASH}1 Alpha · Nov 3", "3"),
            ("Match Day 3", "Alpha 4\N{EN DASH}0 Bravo · Sep 8", "1"),
        ]
        assert _texts(picker) == ["-# Fix a result", "## Alpha vs Bravo", "They met twice this season. Pick the match to fix."]
        assert _container(picker).accent_colour == discord.Colour.orange()

    async def test_counts_more_than_two_meetings(self, interaction):
        reported = [_regular(id=1), _regular(id=2), _match(id=3)]
        picker = MeetingPickerView(interaction, reported, home="Al_pha", away="Bravo", tz=ZoneInfo("UTC"))

        assert _texts(picker)[1:] == ["## Al\\_pha vs Bravo", "They met 3 times this season. Pick the match to fix."]
        assert [o.description for o in _select(picker).options] == ["Alpha 3\N{EN DASH}1 Bravo"] * 3

    async def test_choice_turns_the_picker_into_the_confirm(self, mixin, interaction, meetings):
        mixin.find_match.return_value = meetings
        admin = Admin(interaction, pick=1)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=2)

        assert [m for m, _ in admin.shown] == ["send", "edit", "edit"]
        assert admin.shown[1][1] is admin.confirm
        assert "-# Elite · Match Day 3 · Fixing the result" in _texts(admin.confirm)
        mixin.report_match.assert_awaited_once_with(
            interaction.guild,
            match_id=1,
            ballchasing_group="stored-group",
            home_score=2,
            away_score=2,
            executor=interaction.user,
            override=True,
        )

    async def test_bad_score_after_a_choice_replaces_the_picker(self, mixin, interaction, meetings):
        mixin.find_match.return_value = meetings
        admin = Admin(interaction, pick=3)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=1, away_wins=1)

        assert admin.views(ConfirmLayoutView) == []
        mixin.report_match.assert_not_awaited()
        method, view = admin.last
        assert method == "edit"
        assert _container(view).accent_colour == discord.Colour.red()

    async def test_no_choice_reports_nothing(self, mixin, interaction, meetings):
        mixin.find_match.return_value = meetings
        admin = Admin(interaction, pick=None)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=2)

        assert admin.views(ConfirmLayoutView) == []
        mixin.report_match.assert_not_awaited()

    async def test_one_reported_meeting_is_fixed_without_a_picker(self, mixin, interaction):
        mixin.find_match.return_value = [_regular(id=1, score=None), _regular(id=2, day=9, score=(1, 3))]
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=2)

        assert admin.views(MeetingPickerView) == []
        assert admin.shown[0] == ("send", admin.confirm)
        assert mixin.report_match.await_args.kwargs["match_id"] == 2

    @pytest.mark.parametrize(
        ("found", "message"),
        [
            ([_regular(id=1, score=None), _regular(id=2, day=9, score=None)], "/reportmatch"),
            ([], "No match this season"),
        ],
    )
    async def test_nothing_reported_is_refused(self, mixin, interaction, found, message):
        mixin.find_match.return_value = found
        admin = Admin(interaction)
        await fix(mixin, interaction, home="Alpha", away="Bravo", home_wins=2, away_wins=2)

        assert admin.views(ConfirmLayoutView) == []
        mixin.report_match.assert_not_awaited()
        assert message in interaction.followup.send.await_args.kwargs["embed"].description

    async def test_select_records_the_choice_and_answers_the_click(self, interaction, meetings):
        reported = [meetings[0], meetings[2]]
        picker = MeetingPickerView(interaction, reported, home="Alpha", away="Bravo", tz=ZoneInfo("UTC"))
        select = _select(picker)
        select._values = ["3"]
        click = MagicMock(spec=discord.Interaction)
        click.response = MagicMock()
        click.response.defer = AsyncMock()

        await select.callback(click)

        assert picker.choice is reported[1]
        click.response.defer.assert_awaited_once_with()
        assert picker.is_finished()
