import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import ui

from rsc.ballchasing import ballchasing as bc
from rsc.ballchasing.ballchasing import BallchasingMixIn, PrerenderedBanner
from rsc.ballchasing.views import ChampionsCard, MatchResultCard
from rsc.enums import MatchType, PostSeasonType, Status, SubStatus
from rsc.exceptions import ApiError
from rsc.matches.series import FinalWin, final_win, is_final
from rsc.utils.champions_banner import ChampionsBanner
from tests.utils import command_callback

GUILD_ID = 1234
LEAGUE_ID = 1
IN_SERVER = {11, 101, 102}
BANNER = b"RIFF-banner"


def _player(name: str, discord_id: int, status: Status, sub_status: SubStatus = SubStatus.NOT) -> MagicMock:
    player = MagicMock(discord_id=discord_id, status=status, sub_status=sub_status, captain=False)
    # `name` is MagicMock's own argument, so it's set after
    player.name = name
    return player


def _team(name: str, *, franchise: str, gm_id: int, players: list[MagicMock]) -> MagicMock:
    team = MagicMock()
    team.name = name
    team.tier = "Elite"
    team.franchise = franchise
    team.gm = MagicMock(discord_id=gm_id)
    team.players = players
    return team


def _match(*, match_type=MatchType.FINALS, day=1, num_games=7) -> MagicMock:
    match = MagicMock()
    match.id = 36901
    match.day = day
    match.season_number = 23
    match.match_type = match_type
    match.num_games = num_games
    match.home_team = _team(
        "Quantum",
        franchise="Hex Systems",
        gm_id=11,
        players=[
            _player("Captain", 101, Status.ROSTERED),
            _player("Renewed", 102, Status.RENEWED),
            _player("Sub_In", 103, Status.FREE_AGENT, SubStatus.IN),
            _player("Benched", 110, Status.ROSTERED, SubStatus.OUT),
            _player("Perm", 104, Status.PERM_FA),
            _player("Hurt", 105, Status.IR),
            _player("AgmHurt", 106, Status.AGMIR),
            _player("Gone", 107, Status.FORMER),
            _player("Waived", 108, Status.WAIVERS),
            _player("Draftee", 109, Status.DRAFT_ELIGIBLE),
        ],
    )
    match.away_team = _team("Voltage", franchise="Solstice Esports", gm_id=22, players=[_player("Rival", 201, Status.ROSTERED)])
    return match


def _result(home: int, away: int) -> MagicMock:
    return MagicMock(home_wins=home, away_wins=away)


def _guild() -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.name = "RSC"
    guild.icon = MagicMock(url="https://cdn.example/guild.png")
    guild.get_member.side_effect = lambda i: MagicMock(mention=f"<@{i}>") if i in IN_SERVER else None
    return guild


def _mixin(**attrs) -> BallchasingMixIn:
    saved = BallchasingMixIn.__abstractmethods__
    BallchasingMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(BallchasingMixIn)
    finally:
        BallchasingMixIn.__abstractmethods__ = saved
    defaults = {
        "_api_conf": {GUILD_ID: MagicMock(host="https://www.rscna.com/api/v1")},
        "_league": {GUILD_ID: LEAGUE_ID},
        "season_id_for_number": AsyncMock(return_value=11),
        "franchises": AsyncMock(return_value=[MagicMock(id=5)]),
        "franchise_logo": AsyncMock(return_value="https://cdn.example/logo.png"),
        "bracket_link": AsyncMock(return_value="https://www.rscna.com/playoffs/?tier=Elite&league=1&season=11"),
        "champions_banner": AsyncMock(return_value=BANNER),
    }
    defaults.update(attrs)
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


@pytest.fixture(autouse=True)
def _tier_colour(monkeypatch):
    monkeypatch.setattr("rsc.ballchasing.ballchasing.utils.tier_color_by_name", AsyncMock(return_value=discord.Colour.orange()))


def _card(**overrides) -> ChampionsCard:
    fields = {
        "season": 23,
        "tier": "Elite",
        "winner": "Quantum",
        "runner_up": "Voltage",
        "winner_wins": 4,
        "runner_up_wins": 2,
        "colour": discord.Colour.orange(),
        "champions": ["<@101>", "<@102>", r"Sub\_In"],
        "gm_mentions": ["<@11>", "<@22>"],
        "banner": BANNER,
        "match_url": "https://www.rscna.com/matches/36901/?league=1&season=11&source=matches",
        "ballchasing_url": "https://ballchasing.com/group/abc",
        "bracket_url": "https://www.rscna.com/playoffs/?tier=Elite&league=1&season=11",
    }
    fields.update(overrides)
    return ChampionsCard(**fields)


def _container(view: ui.LayoutView) -> ui.Container:
    (container,) = view.children
    assert isinstance(container, ui.Container)
    return container


def _texts(view: ui.LayoutView) -> list[str]:
    return [c.content for c in _container(view).children if isinstance(c, ui.TextDisplay)]


def _galleries(view: ui.LayoutView) -> list[ui.MediaGallery]:
    return [c for c in _container(view).children if isinstance(c, ui.MediaGallery)]


def _buttons(view: ui.LayoutView) -> list[ui.Button]:
    return [b for row in _container(view).children if isinstance(row, ui.ActionRow) for b in row.children if isinstance(b, ui.Button)]


class TestFinalWin:
    def test_clinched_finals(self):
        match = _match()
        assert final_win(match, 4, 2) == FinalWin(match.home_team, match.away_team, 4, 2)

    def test_seen_from_the_away_winner(self):
        match = _match()
        assert final_win(match, 1, 4) == FinalWin(match.away_team, match.home_team, 4, 1)

    def test_postseason_finals_day_is_a_final(self):
        match = _match(match_type=MatchType.POSTSEASON, day=PostSeasonType.FINALS)
        assert is_final(match)
        assert final_win(match, 4, 3) is not None

    @pytest.mark.parametrize(
        ("match_type", "day"),
        [
            (MatchType.POSTSEASON, PostSeasonType.SEMIFINALS),
            (MatchType.REGULAR, PostSeasonType.FINALS),
            (MatchType.PRESEASON, 1),
        ],
    )
    def test_other_matches_are_not_finals(self, match_type, day):
        match = _match(match_type=match_type, day=day)
        assert not is_final(match)
        assert final_win(match, 4, 0) is None

    def test_unclinched_final(self):
        assert final_win(_match(), 3, 3) is None


class TestCardChoice:
    async def test_clinching_final_gets_the_champions_card(self):
        card = await _mixin().match_result_card(_guild(), _match(), _result(4, 2), link="https://ballchasing.com/group/abc")
        assert card == _card(
            champions=["<@101>", "<@102>", r"Sub\_In", "Benched", "Perm", "Hurt", "AgmHurt"],
            gm_mentions=["<@11>"],
        )

    async def test_away_winner_puts_their_gm_first(self):
        guild = _guild()
        guild.get_member.side_effect = lambda i: MagicMock(mention=f"<@{i}>") if i in IN_SERVER | {22} else None
        card = await _mixin().match_result_card(guild, _match(), _result(2, 4))
        assert isinstance(card, ChampionsCard)
        assert (card.winner, card.runner_up, card.winner_wins, card.runner_up_wins) == ("Voltage", "Quantum", 4, 2)
        assert card.gm_mentions == ["<@22>", "<@11>"]
        assert card.champions == ["Rival"]

    @pytest.mark.parametrize(
        ("match", "result"),
        [
            (_match(), _result(3, 2)),
            (_match(match_type=MatchType.POSTSEASON, day=PostSeasonType.SEMIFINALS), _result(4, 2)),
        ],
    )
    async def test_otherwise_the_match_result_card(self, match, result):
        banner = AsyncMock()
        card = await _mixin(champions_banner=banner).match_result_card(_guild(), match, result)
        assert isinstance(card, MatchResultCard)
        banner.assert_not_awaited()


class TestPrerenderedBanner:
    async def test_used_when_rendered_for_the_recorded_score(self):
        banner = AsyncMock()
        task = asyncio.create_task(AsyncMock(return_value=b"prerendered")())
        card = await _mixin(champions_banner=banner).match_result_card(
            _guild(), _match(), _result(4, 2), prerendered=PrerenderedBanner(submitted_score=(4, 2), task=task)
        )
        assert isinstance(card, ChampionsCard)
        assert card.banner == b"prerendered"
        banner.assert_not_awaited()

    async def test_rendered_again_when_the_api_recorded_another_score(self):
        banner = AsyncMock(return_value=b"recorded")
        task = asyncio.create_task(AsyncMock(return_value=b"submitted")())
        guild, match = _guild(), _match()
        card = await _mixin(champions_banner=banner).match_result_card(
            guild, match, _result(4, 3), prerendered=PrerenderedBanner(submitted_score=(4, 2), task=task)
        )
        assert isinstance(card, ChampionsCard)
        assert card.banner == b"recorded"
        banner.assert_awaited_once_with(guild, match, 4, 3)


class TestRender:
    def test_card(self):
        view, files = _card().render()
        assert _texts(view) == [
            "### Congratulations to the Season 23 Elite champions",
            "<@101>\n<@102>\nSub\\_In",
            "-# Runner-up Voltage · GMs <@11> · <@22>",
        ]
        assert _container(view).accent_colour == discord.Colour.orange()
        (gallery,) = _galleries(view)
        (item,) = gallery.items
        assert item.media.url == "attachment://champions.webp"
        assert item.description == "Quantum, Season 23 Elite champions, won the final 4\N{EN DASH}2 against Voltage"
        (file,) = files
        assert file.filename == "champions.webp"
        assert file.fp.read() == BANNER

    def test_banner_sits_above_the_text(self):
        children = _container(_card().render()[0]).children
        assert isinstance(children[0], ui.MediaGallery)

    def test_unknown_season(self):
        view, _ = _card(season=None).render()
        assert _texts(view)[0] == "### Congratulations to the Elite champions"
        (item,) = _galleries(view)[0].items
        assert item.description == "Quantum, Elite champions, won the final 4\N{EN DASH}2 against Voltage"

    def test_no_gms_in_the_server(self):
        view, _ = _card(gm_mentions=[], runner_up="Volt_age").render()
        assert _texts(view)[-1] == r"-# Runner-up Volt\_age"

    def test_no_banner_no_gallery_or_file(self):
        view, files = _card(banner=None).render()
        assert _galleries(view) == []
        assert files == []
        assert _texts(view)[0] == "### Congratulations to the Season 23 Elite champions"

    def test_each_render_gets_its_own_file(self):
        card = _card()
        first, second = card.render()[1][0], card.render()[1][0]
        assert first is not second
        assert second.fp.read() == BANNER

    def test_link_buttons_after_a_separator(self):
        view, _ = _card().render()
        assert [(b.label, b.url) for b in _buttons(view)] == [
            ("Match page", "https://www.rscna.com/matches/36901/?league=1&season=11&source=matches"),
            ("Ballchasing", "https://ballchasing.com/group/abc"),
            ("Bracket", "https://www.rscna.com/playoffs/?tier=Elite&league=1&season=11"),
        ]
        children = _container(view).children
        row = next(i for i, c in enumerate(children) if isinstance(c, ui.ActionRow))
        assert isinstance(children[row - 1], ui.Separator)

    def test_missing_links_are_left_out(self):
        view, _ = _card(match_url=None, bracket_url=None).render()
        assert [b.label for b in _buttons(view)] == ["Ballchasing"]
        view, _ = _card(match_url=None, ballchasing_url=None, bracket_url=None).render()
        assert not any(isinstance(c, (ui.ActionRow, ui.Separator)) for c in _container(view).children)

    def test_reporter_copy_adds_the_replays_line(self):
        assert "-# Replays: Uploaded **6**" not in _texts(_card().render()[0])
        assert _texts(_card().render(replays="Uploaded **6**")[0])[-1] == "-# Replays: Uploaded **6**"

    def test_within_component_limits(self):
        view, _ = _card().render(replays="Uploaded **6**")
        assert view.total_children_count <= 40


class TestChampionsBanner:
    async def test_renders_the_winner_with_their_logo(self, monkeypatch):
        fetch = AsyncMock(return_value=b"logo")
        render = AsyncMock(return_value=BANNER)
        monkeypatch.setattr(bc, "fetch_logo", fetch)
        monkeypatch.setattr(bc, "champions_banner_bytes", render)
        mixin = _mixin()
        del mixin.champions_banner

        assert await mixin.champions_banner(_guild(), _match(), 2, 4) == BANNER
        fetch.assert_awaited_once_with("https://cdn.example/logo.png")
        render.assert_awaited_once_with(
            ChampionsBanner(
                season=23,
                tier="Elite",
                tier_colour=discord.Colour.orange().to_rgb(),
                winner="Voltage",
                loser="Quantum",
                winner_wins=4,
                loser_wins=2,
                logo=b"logo",
            )
        )

    async def test_unfetchable_logo_still_gives_a_banner(self, monkeypatch):
        monkeypatch.setattr(bc, "fetch_logo", AsyncMock(side_effect=TimeoutError()))
        render = AsyncMock(return_value=BANNER)
        monkeypatch.setattr(bc, "champions_banner_bytes", render)
        mixin = _mixin()
        del mixin.champions_banner

        assert await mixin.champions_banner(_guild(), _match(), 4, 2) == BANNER
        (spec,) = render.await_args_list[0].args
        assert spec.logo is None

    async def test_render_failure_is_logged_and_gives_no_banner(self, monkeypatch):
        monkeypatch.setattr(bc, "fetch_logo", AsyncMock(return_value=b"logo"))
        monkeypatch.setattr(bc, "champions_banner_bytes", AsyncMock(side_effect=OSError("encoder")))
        mixin = _mixin()
        del mixin.champions_banner

        with patch.object(bc.log, "exception") as logged:
            assert await mixin.champions_banner(_guild(), _match(), 4, 2) is None
        logged.assert_called_once()


class _Report:
    def __init__(self, *, submitted: tuple[int, int], recorded: tuple[int, int] | Exception):
        self.match = _match()
        self.banner_calls: list[tuple[int, int]] = []
        self.banner_cancelled = False
        self.interaction = MagicMock()
        self.interaction.guild = _guild()
        self.interaction.user = MagicMock(spec=discord.Member)
        self.interaction.response.send_modal = AsyncMock()
        self.interaction.followup.send = AsyncMock()
        self.interaction.edit_original_response = AsyncMock()
        self.announce = AsyncMock()
        self.modal = MagicMock(wait=AsyncMock(return_value=False), valid=True, home_wins=submitted[0], away_wins=submitted[1])
        self.modal.replays = [MagicMock()]
        report = AsyncMock(side_effect=recorded) if isinstance(recorded, Exception) else AsyncMock(return_value=_result(*recorded))
        self.mixin = _mixin(
            _find_report_match=AsyncMock(return_value=self.match),
            discord_member_in_match=AsyncMock(return_value=True),
            is_match_franchise_gm=AsyncMock(return_value=False),
            has_bc_permissions=AsyncMock(return_value=False),
            _bc_match_locks={},
            process_match_replays=self._upload,
            report_match=report,
            report_upload_failures=AsyncMock(),
            announce_to_score_reporting=self.announce,
            champions_banner=self._banner,
        )

    async def _upload(self, guild, match, candidates) -> MagicMock:
        await asyncio.sleep(0.01)
        return MagicMock(group="abc", uploaded=6, skipped=0, failed=0)

    async def _banner(self, guild, match, home_wins, away_wins) -> bytes:
        self.banner_calls.append((home_wins, away_wins))
        try:
            await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            self.banner_cancelled = True
            raise
        return f"{home_wins}-{away_wins}".encode()

    async def run(self) -> None:
        with (
            patch.object(bc, "ReportMatchModal", return_value=self.modal),
            patch.object(bc.validation, "is_replay_file", AsyncMock(return_value=True)),
            patch.object(bc.process, "build_candidates", AsyncMock(return_value=[MagicMock()])),
            patch.object(bc.process, "duplicate_in_batch", return_value=None),
            patch.object(bc, "score_error", return_value=None),
        ):
            await command_callback(BallchasingMixIn._reportmatch_cmd)(self.mixin, self.interaction, "Quantum", "Voltage", None, False)
        # Let a cancelled banner task see its cancellation
        await asyncio.sleep(0)

    def posted(self) -> tuple[ui.LayoutView, list[discord.File]]:
        call = self.announce.await_args
        assert call is not None
        return call.kwargs["view"], call.kwargs["files"]


class TestReportFlow:
    async def test_posts_the_banner_rendered_during_the_upload(self):
        report = _Report(submitted=(4, 2), recorded=(4, 2))
        await report.run()
        assert report.banner_calls == [(4, 2)]
        view, files = report.posted()
        assert _texts(view)[0] == "### Congratulations to the Season 23 Elite champions"
        assert files[0].fp.read() == b"4-2"

    async def test_renders_for_the_recorded_score_when_it_differs(self):
        report = _Report(submitted=(4, 2), recorded=(4, 3))
        await report.run()
        assert report.banner_calls == [(4, 2), (4, 3)]
        _, files = report.posted()
        assert files[0].fp.read() == b"4-3"

    async def test_no_banner_for_a_score_that_doesnt_clinch(self):
        report = _Report(submitted=(3, 2), recorded=(3, 2))
        await report.run()
        assert report.banner_calls == []
        view, files = report.posted()
        texts = [i.content for i in view.walk_children() if isinstance(i, ui.TextDisplay)]
        assert texts[0] == "-# Elite · Finals · Final"
        assert files == []

    async def test_already_reported_cancels_the_banner(self):
        report = _Report(submitted=(4, 2), recorded=ApiError(500, "Match already reported"))
        await report.run()
        assert report.banner_calls == [(4, 2)]
        assert report.banner_cancelled
        report.announce.assert_not_awaited()
        call = report.interaction.edit_original_response.await_args
        assert call is not None
        assert call.kwargs["embed"].title == "Match Reported"
