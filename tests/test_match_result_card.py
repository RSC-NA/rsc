from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord import ui

from rsc.ballchasing.ballchasing import BallchasingMixIn
from rsc.ballchasing.views import FALLBACK_LOGO, MatchResultCard, match_label
from rsc.enums import MatchType, PostSeasonType

GUILD_ID = 1234
LEAGUE_ID = 1


def _team(name: str, *, tier: str | None = "Elite", franchise: str = "Hex Systems", gm_id: int | None = None) -> MagicMock:
    team = MagicMock()
    team.name = name
    team.tier = tier
    team.franchise = franchise
    team.gm = MagicMock(discord_id=gm_id) if gm_id else None
    return team


def _match(*, match_type=MatchType.REGULAR, day=7, season_number=24, match_id=36901, home_tier: str | None = "Elite") -> MagicMock:
    match = MagicMock()
    match.id = match_id
    match.day = day
    match.season_number = season_number
    match.match_type = match_type
    match.home_team = _team("Quantum", tier=home_tier, franchise="Hex Systems", gm_id=11)
    match.away_team = _team("Voltage", franchise="Solstice Esports", gm_id=22)
    return match


def _result(home: int | None, away: int | None) -> MagicMock:
    return MagicMock(home_wins=home, away_wins=away)


def _card(**overrides) -> MatchResultCard:
    fields = {
        "match": _match(),
        "result": _result(3, 1),
        "colour": discord.Colour.orange(),
        "logo_url": "https://cdn.example/logo.png",
        "gm_mentions": ["<@11>", "<@22>"],
        "match_url": "https://www.rscna.com/matches/36901/?league=1&season=11&source=matches",
        "ballchasing_url": "https://ballchasing.com/group/abc",
    }
    fields.update(overrides)
    return MatchResultCard(**fields)


def _container(view: ui.LayoutView) -> ui.Container:
    (container,) = view.children
    assert isinstance(container, ui.Container)
    return container


def _section(view: ui.LayoutView) -> ui.Section:
    section = _container(view).children[0]
    assert isinstance(section, ui.Section)
    return section


def _texts(item: ui.Container | ui.Section) -> list[str]:
    return [c.content for c in item.children if isinstance(c, ui.TextDisplay)]


def _buttons(view: ui.LayoutView) -> list[ui.Button]:
    return [b for row in _container(view).children if isinstance(row, ui.ActionRow) for b in row.children if isinstance(b, ui.Button)]


class TestMatchLabel:
    @pytest.mark.parametrize(
        ("match_type", "day", "label"),
        [
            (MatchType.REGULAR, 7, "Match Day 7"),
            (MatchType.PRESEASON, 2, "Preseason 2"),
            (MatchType.POSTSEASON, PostSeasonType.PLAYOFF, "Playoffs"),
            (MatchType.POSTSEASON, PostSeasonType.WILDCARD, "Wildcard"),
            (MatchType.POSTSEASON, PostSeasonType.QUARTERFINALS, "Quarterfinals"),
            (MatchType.POSTSEASON, PostSeasonType.SEMIFINALS, "Semifinals"),
            (MatchType.POSTSEASON, PostSeasonType.FINALS, "Finals"),
            (MatchType.POSTSEASON, 99, "Playoffs"),
            (MatchType.FINALS, 1, "Finals"),
            (MatchType.REGULAR, None, "Match Day 0"),
        ],
    )
    def test_labels(self, match_type, day, label):
        assert match_label(_match(match_type=match_type, day=day)) == label


class TestRender:
    def test_win(self):
        view, files = _card().render()
        section = _section(view)
        assert _texts(section) == [
            "-# Elite · Match Day 7 · Final\n## Quantum 3\N{NO-BREAK SPACE}\N{EN DASH}\N{WORD JOINER}\N{NO-BREAK SPACE}1 Voltage",
            # No winner line: the score already says it
            "GMs <@11> · <@22>",
        ]
        assert isinstance(section.accessory, ui.Thumbnail)
        assert section.accessory.media.url == "https://cdn.example/logo.png"
        assert files == []
        assert _container(view).accent_colour == discord.Colour.orange()

    def test_escaped_names(self):
        match = _match()
        match.away_team.name = "Under_score"
        view, _ = _card(match=match, result=_result(0, 3)).render()
        assert _texts(_section(view))[0].endswith(r"3 Under\_score")

    def test_link_buttons(self):
        view, _ = _card().render()
        assert [(b.label, b.url, b.style) for b in _buttons(view)] == [
            ("Match page", "https://www.rscna.com/matches/36901/?league=1&season=11&source=matches", discord.ButtonStyle.link),
            ("Ballchasing", "https://ballchasing.com/group/abc", discord.ButtonStyle.link),
        ]

    def test_no_links_no_row(self):
        view, _ = _card(match_url=None, ballchasing_url=None).render()
        assert not any(isinstance(c, ui.ActionRow) for c in _container(view).children)

    def test_no_gms_no_gm_line(self):
        view, _ = _card(gm_mentions=[]).render()
        assert len(_texts(_section(view))) == 1

    def test_no_tier_drops_it_from_the_label(self):
        view, _ = _card(match=_match(home_tier=None)).render()
        assert _texts(_section(view))[0].startswith("-# Match Day 7 · Final\n")

    def test_fallback_logo_is_attached(self):
        view, files = _card(logo_url=None).render()
        (logo,) = files
        assert logo.filename == FALLBACK_LOGO.name
        accessory = _section(view).accessory
        assert isinstance(accessory, ui.Thumbnail)
        assert accessory.media.url == f"attachment://{FALLBACK_LOGO.name}"

    def test_each_render_gets_its_own_file(self):
        card = _card(logo_url=None)
        assert card.render()[1][0] is not card.render()[1][0]

    def test_no_footer_and_reporter_replays_line(self):
        public, _ = _card().render()
        reporter, _ = _card().render(replays="Uploaded **4**")
        assert _texts(_container(public)) == []
        assert _texts(_container(reporter)) == ["-# Replays: Uploaded **4**"]

    def test_within_component_limits(self):
        view, _ = _card().render(replays="Uploaded **4**")
        assert view.total_children_count <= 40


def _guild() -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.name = "RSC"
    guild.icon = MagicMock(url="https://cdn.example/guild.png")
    guild.get_member.side_effect = lambda i: MagicMock(mention=f"<@{i}>") if i == 11 else None
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
    }
    defaults.update(attrs)
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


class TestMatchPageLink:
    async def test_full_link(self):
        url = await _mixin().match_page_link(_guild(), _match())
        assert url == "https://www.rscna.com/matches/36901/?league=1&season=11&source=matches"

    async def test_unknown_season_is_omitted(self):
        mixin = _mixin(season_id_for_number=AsyncMock(return_value=None))
        assert await mixin.match_page_link(_guild(), _match()) == "https://www.rscna.com/matches/36901/?league=1&source=matches"

    async def test_no_api_config_no_link(self):
        assert await _mixin(_api_conf={}).match_page_link(_guild(), _match()) is None


class TestMatchResultCard:
    async def test_gathers_inputs(self, monkeypatch):
        monkeypatch.setattr("rsc.ballchasing.ballchasing.utils.tier_color_by_name", AsyncMock(return_value=discord.Colour.orange()))
        franchises = AsyncMock(return_value=[MagicMock(id=5)])
        mixin = _mixin(franchises=franchises)
        guild = _guild()
        card = await mixin.match_result_card(guild, _match(), _result(3, 1), link="https://ballchasing.com/group/abc")
        franchises.assert_awaited_once_with(guild, name="Hex Systems")
        assert card.logo_url == "https://cdn.example/logo.png"
        # GM 22 isn't in the server, so only GM 11 is mentioned
        assert card.gm_mentions == ["<@11>"]
        assert card.match_url and card.match_url.endswith("season=11&source=matches")
        assert card.ballchasing_url == "https://ballchasing.com/group/abc"
        assert card.colour == discord.Colour.orange()

    async def test_tie_skips_the_franchise_lookup_and_uses_the_server_icon(self, monkeypatch):
        monkeypatch.setattr("rsc.ballchasing.ballchasing.utils.tier_color_by_name", AsyncMock(return_value=discord.Colour.orange()))
        franchises = AsyncMock()
        mixin = _mixin(franchises=franchises)
        card = await mixin.match_result_card(_guild(), _match(), _result(2, 2))
        franchises.assert_not_awaited()
        assert card.logo_url == "https://cdn.example/guild.png"


class TestAnnounceToScoreReporting:
    async def test_sends_only_the_view_and_lets_user_pings_through(self):
        channel = MagicMock(spec=discord.TextChannel)
        channel.name = "elite-score-reporting"
        channel.send = AsyncMock()
        category = MagicMock(channels=[channel])
        mixin = _mixin(_get_score_reporting_category=AsyncMock(return_value=category))
        view = ui.LayoutView()

        await mixin.announce_to_score_reporting(_guild(), tier="Elite", view=view, files=[])

        call = channel.send.await_args
        assert call is not None
        kwargs = call.kwargs
        assert kwargs["view"] is view
        assert "content" not in kwargs and "embed" not in kwargs
        mentions = kwargs["allowed_mentions"]
        assert (mentions.users, mentions.roles, mentions.everyone) == (True, False, False)

    async def test_no_tier_no_post(self):
        mixin = _mixin(_get_score_reporting_category=AsyncMock(return_value=MagicMock(channels=[])))
        assert await mixin.announce_to_score_reporting(_guild(), tier=None, view=ui.LayoutView()) is None
