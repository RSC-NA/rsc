import re
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import discord
from discord import ui
from rscapi.exceptions import ApiException
from rscapi.models.season import Season
from rscapi.models.season_league import SeasonLeague
from rscapi.models.season_schedule import SeasonSchedule
from rscapi.models.season_tier_data import SeasonTierData
from rscapi.models.tier import Tier

from rsc.exceptions import RscException
from rsc.tiers.tiers import TierMixIn
from rsc.tiers.views import TierRow, TiersCard

from .utils import command_callback

TZ = ZoneInfo("America/New_York")
ICON = "https://example.com/icon.png"
# Highest tier first, as `tiers()` returns them
NAMES = ["Premier", "Master", "Elite", "Veteran", "Rival", "Challenger", "Prospect", "Contender", "Amateur", "Novice"]


def _season(*, schedules: list[SeasonSchedule | None] | None = None, names: list[str] = NAMES) -> Season:
    weekly = SeasonSchedule.model_construct(match_nights=["Monday", "Wednesday"], match_start_time="22:00:00")
    schedules = schedules if schedules is not None else [weekly] * len(names)
    data = [
        SeasonTierData.model_construct(
            tier=name, mmr_min=2000 - 100 * i, mmr_max=2100 - 100 * i, team_number=8, team_cap=7400 - 400 * i, schedule=schedule
        )
        for i, (name, schedule) in enumerate(zip(names, schedules, strict=True))
    ]
    return Season.model_construct(league=SeasonLeague.model_construct(name="RSC", id=1), number=27, season_tier_data=data)


def _mixin(*, names: list[str] = NAMES, season: Season | Exception | None = None) -> TierMixIn:
    saved = TierMixIn.__abstractmethods__
    TierMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(TierMixIn)
    finally:
        TierMixIn.__abstractmethods__ = saved
    attrs = {
        "tiers": AsyncMock(return_value=[Tier.model_construct(name=n, position=len(names) - i) for i, n in enumerate(names)]),
        "current_season": AsyncMock(side_effect=season) if isinstance(season, Exception) else AsyncMock(return_value=season),
        "timezone": AsyncMock(return_value=TZ),
    }
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _with_roles(guild, *names: str):
    guild.roles = [SimpleNamespace(name=n, id=1000 + i) for i, n in enumerate(names)]
    return guild


def _interaction(guild) -> MagicMock:
    interaction = MagicMock()
    interaction.guild = guild
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


async def _send(mixin: TierMixIn, guild) -> dict:
    interaction = _interaction(guild)
    await command_callback(TierMixIn._tiers)(mixin, interaction)
    interaction.response.defer.assert_awaited_once()
    send = interaction.followup.send.await_args
    assert send is not None
    return send.kwargs


def _container(view: ui.LayoutView) -> ui.Container:
    (container,) = view.children
    assert isinstance(container, ui.Container)
    return container


def _texts(view: ui.LayoutView) -> list[str]:
    return [c.content for c in _container(view).walk_children() if isinstance(c, ui.TextDisplay)]


def _component_count(view: ui.LayoutView) -> int:
    return 1 + len(list(_container(view).walk_children()))


class TestTiersCommand:
    async def test_sends_publicly_without_pinging_any_role(self, mock_guild):
        guild = _with_roles(mock_guild, *NAMES)

        sent = await _send(_mixin(season=_season()), guild)

        mentions = sent["allowed_mentions"]
        assert isinstance(mentions, discord.AllowedMentions)
        assert (mentions.roles, mentions.users, mentions.everyone, mentions.replied_user) == (False, False, False, False)
        # What Discord receives: parse nothing, and no role id is allow-listed
        assert mentions.to_dict() == {"parse": []}
        assert sent.get("ephemeral", False) is False
        # The card does carry live role mentions, which is why the above matters
        assert all(f"<@&{1000 + i}>" in _texts(sent["view"])[3] for i in range(len(NAMES)))

    async def test_full_season_card(self, mock_guild):
        guild = _with_roles(mock_guild, *NAMES)

        texts = _texts((await _send(_mixin(season=_season()), guild))["view"])

        assert texts[:3] == ["-# RSC · Season 27", "## Tiers", "10 tiers · 80 teams"]
        assert texts[3].splitlines()[:4] == [
            "<@&1000>",
            "-# 2000\N{EN DASH}2100 MMR · 8 teams · 7400 team cap",
            "<@&1001>",
            "-# 1900\N{EN DASH}2000 MMR · 8 teams · 7000 team cap",
        ]
        assert len(texts[3].splitlines()) == 20
        footer = re.fullmatch(r"-# Match nights Monday and Wednesday at <t:(\d+):t>", texts[4])
        assert footer is not None
        start = datetime.fromtimestamp(int(footer[1]), TZ)
        assert (start.date(), start.hour, start.minute) == (datetime.now(TZ).date(), 22, 0)

    async def test_missing_role_falls_back_to_the_bold_name(self, mock_guild):
        guild = _with_roles(mock_guild, "Premier")

        texts = _texts((await _send(_mixin(names=["Premier", "Mas_ter"], season=None), guild))["view"])

        assert texts[3] == "<@&1000>\n**Mas\\_ter**"

    async def test_season_fetch_failure_still_lists_the_tiers(self, mock_guild):
        guild = _with_roles(mock_guild, *NAMES)
        failure = RscException(ApiException(status=503, reason="Service Unavailable"))

        texts = _texts((await _send(_mixin(season=failure), guild))["view"])

        assert texts[:3] == ["-# RSC 3v3", "## Tiers", "10 tiers"]
        assert texts[3].splitlines() == [f"<@&{1000 + i}>" for i in range(10)]
        assert not any(t.startswith("-# Match nights") for t in texts)

    async def test_differing_schedules_leave_off_the_footer(self, mock_guild):
        other = SeasonSchedule.model_construct(match_nights=["Tuesday", "Thursday"], match_start_time="22:00:00")
        weekly = SeasonSchedule.model_construct(match_nights=["Monday", "Wednesday"], match_start_time="22:00:00")
        season = _season(names=["Premier", "Master"], schedules=[weekly, other])

        texts = _texts((await _send(_mixin(names=["Premier", "Master"], season=season), mock_guild))["view"])

        assert not any(t.startswith("-# Match nights") for t in texts)

    async def test_unparseable_start_time_drops_the_time(self, mock_guild):
        odd = SeasonSchedule.model_construct(match_nights=["Monday"], match_start_time="late")
        season = _season(names=["Premier"], schedules=[odd])

        texts = _texts((await _send(_mixin(names=["Premier"], season=season), mock_guild))["view"])

        assert texts[-1] == "-# Match nights Monday"


class TestTiersCardRender:
    def test_small_line_shows_only_known_parts(self):
        rows = (
            TierRow("Premier", role_id=1, mmr_min=1800, mmr_max=2040, teams=1, team_cap=7385),
            TierRow("Master", role_id=2, mmr_min=1700),
            TierRow("Elite", role_id=3, team_cap=6000),
            TierRow("Rival", teams=4),
        )
        texts = _texts(TiersCard(heading="RSC · Season 27", rows=rows).render())
        assert texts[2] == "4 tiers · 5 teams"
        assert texts[3].split("\n") == [
            "<@&1>",
            "-# 1800\N{EN DASH}2040 MMR · 1 team · 7385 team cap",
            "<@&2>",
            "<@&3>",
            "-# 6000 team cap",
            "**Rival**",
            "-# 4 teams",
        ]

    def test_singular_counts(self):
        texts = _texts(TiersCard(heading="RSC", rows=(TierRow("Premier", teams=1),)).render())
        assert texts[2] == "1 tier · 1 team"

    def test_icon_sits_beside_the_header(self):
        header = _container(TiersCard(heading="RSC", rows=(TierRow("Premier"),), icon_url=ICON).render()).children[0]
        assert isinstance(header, ui.Section)
        assert isinstance(header.accessory, ui.Thumbnail) and header.accessory.media.url == ICON

    def test_without_icon_the_header_is_plain_text(self):
        container = _container(TiersCard(heading="RSC", rows=(TierRow("Premier"),)).render())
        assert container.accent_colour == discord.Colour.blue()
        first = container.children[0]
        assert isinstance(first, ui.TextDisplay) and first.content == "-# RSC"

    def test_three_nights(self):
        card = TiersCard(heading="RSC", rows=(TierRow("Premier"),), match_nights=("Monday", "Wednesday", "Friday"))
        assert _texts(card.render())[-1] == "-# Match nights Monday, Wednesday and Friday"

    def test_no_nights_no_footer(self):
        card = TiersCard(heading="RSC", rows=(TierRow("Premier"),), match_time=datetime(2026, 11, 4, 22, tzinfo=TZ))
        view = card.render()
        assert not any(t.startswith("-# Match nights") for t in _texts(view))
        assert not isinstance(_container(view).children[-1], ui.Separator)

    def test_ten_tiers_fit_the_component_limit(self):
        rows = tuple(TierRow(n, role_id=i, mmr_min=1, mmr_max=2, teams=8, team_cap=7000) for i, n in enumerate(NAMES))
        card = TiersCard(
            heading="RSC · Season 27",
            rows=rows,
            icon_url=ICON,
            match_nights=("Monday", "Wednesday"),
            match_time=datetime(2026, 11, 4, 22, tzinfo=TZ),
        )
        assert _component_count(card.render()) <= 40
