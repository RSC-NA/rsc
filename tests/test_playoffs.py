"""Tests for /playoffs: the race statuses, both message layouts, the graphic and its cache, and the command."""

import io
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import ui
from PIL import Image
from rscapi.exceptions import ApiException
from rscapi.models.tier_playoff_hunt import TierPlayoffHunt

from rsc.exceptions import RscException
from rsc.stats import graphic
from rsc.stats.graphic import GraphicCache, pill, race_graphics, render_graphics
from rsc.stats.playoffs import RaceStatus, RaceTeam, build_races, is_eliminated, race_statuses
from rsc.stats.stats import StatsMixIn
from rsc.stats.views import NBSP, WJ, PlayoffRaceCard, alt_text, board_row

from . import playoff_samples as samples
from .playoff_samples import group, hunt, team
from .utils import command_callback

ORANGE = (230, 126, 34)


def _statuses(h: TierPlayoffHunt, index: int = 0) -> dict[str, RaceStatus]:
    race = build_races(h)[index]
    return {t.name: t.status for t in race.teams}


def _race_team(h: TierPlayoffHunt, name: str) -> RaceTeam:
    return next(t for race in build_races(h) for t in race.teams if t.name == name)


def _card(h: TierPlayoffHunt, *, graphics: bool = False, url: str | None = "https://www.rscna.com/standings/") -> PlayoffRaceCard:
    races = tuple(build_races(h))
    return PlayoffRaceCard(
        tier=h.tier_name,
        season=24,
        colour=discord.Colour.orange(),
        races=races,
        whole_tier=h.playoff_format == "TIER",
        standings_url=url,
        graphics=tuple(b"image" for _ in races) if graphics else (),
    )


def _texts(view: ui.LayoutView) -> list[str]:
    return [item.content for item in view.walk_children() if isinstance(item, ui.TextDisplay)]


# Statuses


class TestRaceStatuses:
    def test_division_tier(self):
        assert _statuses(samples.elite_hunt()) == {
            "Quantum": RaceStatus.CLINCHED,
            "Voltage": RaceStatus.IN,
            "Kestrel": RaceStatus.IN,
            # The last wildcard, level with Hydra
            "Orbit": RaceStatus.BUBBLE,
            "Hydra": RaceStatus.BUBBLE,
            # Two wins back is still on the bubble
            "Wandering Nomads": RaceStatus.BUBBLE,
            "Glacier": RaceStatus.ELIMINATED,
            "Lantern": RaceStatus.ELIMINATED,
        }

    def test_whole_tier(self):
        statuses = _statuses(samples.master_hunt())
        assert [name for name, s in statuses.items() if s is RaceStatus.CLINCHED] == ["Pulsar", "Sentinels", "Comets"]
        # Spartans hold the last spot a win clear of Vipers
        assert statuses["Spartans"] is RaceStatus.BUBBLE
        assert statuses["Vipers"] is RaceStatus.BUBBLE
        # Two wins behind the last spot is still on the bubble
        assert statuses["Cyclones"] is RaceStatus.BUBBLE
        # 5 wins + 4 left = 9, level with Spartans: a tiebreaker could still go its way
        assert statuses["Neon Desert Outlaws"] is RaceStatus.OUT
        assert statuses["Bandits"] is RaceStatus.ELIMINATED
        assert statuses["Rogues"] is RaceStatus.ELIMINATED

    def test_only_the_threatened_qualifier_is_on_the_bubble(self):
        assert _statuses(samples.master_hunt())["Titans"] is RaceStatus.IN

    def test_random_draw_is_on_the_bubble(self):
        teams = [
            team(1, "Alpha", 10, 2, reason="cut", draw="provisional", delta="Random draw (provisional)"),
            team(2, "Bravo", 6, 6, delta="Random draw (provisional)", draw="provisional"),
            team(3, "Charlie", 3, 9, delta="4 wins back", remaining=8),
        ]
        statuses = _statuses(hunt([group("Lunar", 1, teams)], fmt="CONF"))
        assert statuses["Alpha"] is RaceStatus.BUBBLE
        assert statuses["Bravo"] is RaceStatus.BUBBLE
        assert statuses["Charlie"] is RaceStatus.OUT

    def test_complete_season_is_final(self):
        statuses = _statuses(samples.master_hunt(complete=True))
        assert statuses["Spartans"] is RaceStatus.CLINCHED
        assert statuses["Vipers"] is RaceStatus.ELIMINATED
        assert set(statuses.values()) == {RaceStatus.CLINCHED, RaceStatus.ELIMINATED}

    def test_every_team_gets_a_status(self):
        g = samples.elite_hunt().groups[0]
        assert set(race_statuses(g)) == {t.team_id for t in g.teams}


class TestIsEliminated:
    def _group(self, *teams: dict, cutoff: int = 2, divisions: tuple[str, ...] = (), cutline_rank: int | None = None):
        h = hunt([group("Lunar", cutoff, list(teams), divisions=divisions, cutline_rank=cutline_rank)], fmt="DIV" if divisions else "CONF")
        return h.groups[0]

    def _ocean_leader_below_the_line(self, *, leader_wins: int, chaser: dict):
        """Mountain fills the top three; Ocean's leader qualifies from below the line."""
        return self._group(
            team(1, "A", 15, 3, reason="division", division="M"),
            team(2, "B", 13, 5, reason="wildcard", division="M"),
            team(3, "C", 12, 6, reason="wildcard", division="M"),
            team(4, "D", 11, 7, division="M"),
            team(5, "E", leader_wins, 18 - leader_wins, reason="division", division="O"),
            chaser,
            cutoff=4,
            divisions=("M", "O"),
            cutline_rank=3,
        )

    def test_max_wins_below_the_last_team_in(self):
        g = self._group(team(1, "A", 12, 0, reason="cut"), team(2, "B", 10, 2, reason="cut"), team(3, "C", 5, 7))
        assert is_eliminated(g.teams[2], g)

    def test_level_max_wins_stay_alive(self):
        g = self._group(team(1, "A", 12, 0, reason="cut"), team(2, "B", 10, 2, reason="cut"), team(3, "C", 6, 6))
        assert not is_eliminated(g.teams[2], g)

    def test_qualified_teams_are_never_eliminated(self):
        g = self._group(team(1, "A", 12, 0, reason="cut"), team(2, "B", 1, 11, reason="cut"), team(3, "C", 0, 12, remaining=0))
        assert not is_eliminated(g.teams[1], g)

    def test_no_cut_line_means_nobody_is_out(self):
        g = self._group(team(1, "A", 12, 0), team(2, "B", 0, 12, remaining=0), cutoff=0, cutline_rank=0)
        assert not is_eliminated(g.teams[1], g)

    def test_division_tier_alive_while_it_can_catch_its_leader(self):
        g = self._ocean_leader_below_the_line(leader_wins=5, chaser=team(6, "Delta", 3, 15, division="O"))
        assert not is_eliminated(g.teams[5], g)

    def test_division_tier_out_once_it_cant_catch_its_leader(self):
        # Max 8: under C's 12 for a wildcard, and under E's 9 for the division
        g = self._ocean_leader_below_the_line(leader_wins=9, chaser=team(6, "Delta", 4, 14, division="O"))
        assert is_eliminated(g.teams[5], g)

    def test_division_tier_out_below_a_line_above_the_last_spot(self):
        # Max 11 ties D, outside the line, but every wildcard is above the line on 12 or more
        g = self._ocean_leader_below_the_line(leader_wins=6, chaser=team(6, "Mike", 7, 11, division="M"))
        assert is_eliminated(g.teams[5], g)


# The race board


class TestBoardRow:
    def test_clinched(self):
        row = board_row(_race_team(samples.master_hunt(), "Pulsar"), divisions=False)
        assert row == f"1. **Pulsar**{NBSP}16-{WJ}2{NBSP}·{NBSP}Clinched"

    def test_division_leader_with_magic_number(self):
        row = board_row(_race_team(samples.elite_hunt(), "Voltage"), divisions=True)
        assert row == f"2. **Voltage**{NBSP}13-{WJ}5{NBSP}·{NBSP}Leads{NBSP}Ocean{NBSP}·{NBSP}2{NBSP}to{NBSP}clinch"

    def test_division_won(self):
        row = board_row(_race_team(samples.elite_hunt(), "Tempest"), divisions=True)
        assert row == f"2. **Tempest**{NBSP}14-{WJ}4{NBSP}·{NBSP}Won{NBSP}Cloud{NBSP}·{NBSP}Clinched"

    def test_wildcard_that_cant_clinch_yet(self):
        teams = [
            team(1, "Leader", 15, 3, reason="division", delta="Leads Mountain", division="M"),
            team(2, "Cyclone", 10, 8, reason="wildcard", delta="Wildcard", division="O"),
        ]
        h = hunt([group("Lunar", 2, teams, divisions=("M", "O"))])
        assert board_row(_race_team(h, "Cyclone"), divisions=True) == f"2. **Cyclone**{NBSP}10-{WJ}8{NBSP}·{NBSP}Wildcard"

    def test_holding_without_a_magic_number(self):
        h = hunt([group("Master", 1, [team(1, "Alpha", 10, 8, reason="cut")])], fmt="TIER")
        assert board_row(_race_team(h, "Alpha"), divisions=False) == f"1. **Alpha**{NBSP}10-{WJ}8{NBSP}·{NBSP}Holding"

    def test_outside(self):
        assert board_row(_race_team(samples.elite_hunt(), "Hydra"), divisions=True) == f"5. **Hydra**{NBSP}10-{WJ}8{NBSP}·{NBSP}Tiebreaker"
        assert (
            board_row(_race_team(samples.master_hunt(), "Vipers"), divisions=False)
            == f"9. **Vipers**{NBSP}8-{WJ}10{NBSP}·{NBSP}1{NBSP}back"
        )

    def test_no_division_in_a_whole_tier(self):
        row = board_row(_race_team(samples.master_hunt(), "Raptors"), divisions=False)
        assert row == f"4. **Raptors**{NBSP}12-{WJ}6{NBSP}·{NBSP}1{NBSP}to{NBSP}clinch"

    def test_escapes_markdown(self):
        h = hunt([group("Master", 1, [team(1, "Under_Score*", 10, 8, reason="cut", magic=0)])], fmt="TIER")
        assert board_row(_race_team(h, "Under_Score*"), divisions=False).startswith("1. **Under\\_Score\\***")

    def test_one_line_with_no_plain_spaces_after_the_name(self):
        row = board_row(_race_team(samples.master_hunt(), "Neon Desert Outlaws"), divisions=False)
        _, name, tail = row.split("**")
        assert "\n" not in row
        assert name == "Neon Desert Outlaws"
        assert " " not in tail

    def test_complete_season_never_says_to_clinch(self):
        rows = [board_row(t, divisions=False) for t in build_races(samples.master_hunt(complete=True))[0].teams]
        assert not any("to clinch" in row for row in rows)
        assert rows[7].endswith("Clinched")


class TestRaceBoard:
    def test_one_container_per_group_with_the_cut_line(self):
        view, files = _card(samples.elite_hunt()).render()
        assert files == []
        containers = [c for c in view.children if isinstance(c, ui.Container)]
        assert len(containers) == 2
        kinds = [type(item).__name__ for item in containers[0].children]
        assert kinds == ["TextDisplay", "TextDisplay", "Separator", "TextDisplay", "Separator", "TextDisplay", "TextDisplay"]
        separators = [item for item in containers[0].children if isinstance(item, ui.Separator)]
        assert [s.visible for s in separators] == [False, True]
        assert _texts(view)[:2] == [
            "-# SEASON 24 · ELITE · PLAYOFF RACE",
            "## Lunar\n-# 2 division winners + 2 wildcards · 4 games left",
        ]

    def test_whole_tier_title(self):
        texts = _texts(_card(samples.master_hunt()).render()[0])
        assert texts[1] == "## Master playoff race\n-# Top 8 make it · 4 games left"

    def test_rows_number_from_their_rank(self):
        texts = _texts(_card(samples.master_hunt()).render()[0])
        above = next(t for t in texts if t.startswith("-# IN"))
        below = next(t for t in texts if t.startswith("-# BELOW THE CUT"))
        assert above.split("\n")[0] == "-# IN · SEEDS 1 TO 8"
        assert [line.split(".")[0] for line in above.split("\n")[1:]] == [str(n) for n in range(1, 9)]
        # A list that starts below 1 must start with that number
        assert below.split("\n")[1].startswith("9. **Vipers**")
        assert [line.split(".")[0] for line in below.split("\n")[1:]] == ["9", "10", "11", "12"]

    def test_eliminated_fold_into_one_line(self):
        texts = _texts(_card(samples.master_hunt()).render()[0])
        assert f"-# Eliminated: Bandits{NBSP}3-{WJ}15, Rogues{NBSP}2-{WJ}16" in texts

    def test_an_eliminated_team_above_a_live_one_keeps_its_row(self):
        # Charlie can't catch anyone. Delta can still win its weak division, so it's alive below Charlie.
        teams = [
            team(1, "Alpha", 15, 3, reason="division", delta="Leads Mountain", division="M"),
            team(2, "Bravo", 14, 4, reason="wildcard", delta="Wildcard", division="M"),
            team(3, "Charlie", 4, 14, delta="10 wins back", division="M"),
            team(4, "Delta", 3, 15, delta="11 wins back", division="O"),
            team(5, "Echo", 4, 14, reason="division", delta="Leads Ocean", division="O"),
        ]
        race = build_races(hunt([group("Lunar", 3, teams, divisions=("M", "O"), cutline_rank=2)]))[0]
        assert race.folded == ()
        assert [t.rank for t in race.below] == [3, 4, 5]
        assert race.below[0].status is RaceStatus.ELIMINATED
        assert board_row(race.below[0], divisions=True).endswith("Eliminated")

    def test_link_button_is_grey_and_last(self):
        view, _ = _card(samples.elite_hunt(), url="https://www.rscna.com/standings/?tier=Elite").render()
        buttons = [item for item in view.walk_children() if isinstance(item, ui.Button)]
        assert len(buttons) == 1
        assert buttons[0].label == "Full standings"
        assert buttons[0].url == "https://www.rscna.com/standings/?tier=Elite"
        assert buttons[0].style is discord.ButtonStyle.link
        assert isinstance(view.children[-1], ui.Container)
        assert isinstance(view.children[-1].children[-1], ui.ActionRow)

    def test_no_link_without_a_site(self):
        view, _ = _card(samples.elite_hunt(), url=None).render()
        assert not [item for item in view.walk_children() if isinstance(item, ui.Button)]

    def test_no_status_emoji_or_code_chips(self):
        text = "\n".join(_texts(_card(samples.elite_hunt()).render()[0]))
        assert "`" not in text
        assert all(ord(c) < 0x2600 for c in text)


# The graphic message


class TestGraphicMessage:
    def test_a_card_per_conference(self):
        view, files = _card(samples.elite_hunt(), graphics=True).render()
        lunar, solar = view.children
        assert isinstance(lunar, ui.Container) and isinstance(solar, ui.Container)
        kinds = [type(item).__name__ for item in lunar.children]
        assert kinds == ["TextDisplay", "TextDisplay", "MediaGallery"]
        # The standings link closes the message, under the last card only
        assert [type(item).__name__ for item in solar.children][-1] == "ActionRow"
        assert [f.filename for f in files] == ["playoffs-1.png", "playoffs-2.png"]
        texts = _texts(view)
        assert texts[0] == "-# SEASON 24 · PLAYOFF RACE"
        assert texts[1] == "## Elite · Lunar\n-# 2 division winners + 2 wildcards · 4 games left"
        assert "## Elite · Solar\n-# 2 division winners + 2 wildcards · 4 games left" in texts

    def test_whole_tier_is_one_card(self):
        view, files = _card(samples.master_hunt(), graphics=True).render()
        (card,) = view.children
        assert isinstance(card, ui.Container)
        assert [type(item).__name__ for item in card.children][-1] == "ActionRow"
        assert _texts(view)[1].startswith("## Master\n")
        assert len(files) == 1

    def test_no_text_summary_under_the_graphic(self):
        # The graphic already shows the statuses; only the image and, on the last card, the link remain
        lunar, solar = _card(samples.elite_hunt(), graphics=True).render()[0].children
        assert isinstance(lunar, ui.Container) and isinstance(solar, ui.Container)
        assert not any(isinstance(item, ui.Separator) for item in [*lunar.children, *solar.children])
        assert not any("On the bubble" in t or "Clinched" in t for t in _texts(_card(samples.elite_hunt(), graphics=True).render()[0]))

    def test_fresh_files_each_render(self):
        card = _card(samples.master_hunt(), graphics=True)
        first, second = card.render()[1], card.render()[1]
        assert first[0] is not second[0]
        assert first[0].fp.read() == second[0].fp.read() == b"image"

    def test_alt_text_on_every_image(self):
        view, _ = _card(samples.master_hunt(), graphics=True).render()
        gallery = next(item for item in view.walk_children() if isinstance(item, ui.MediaGallery))
        description = gallery.items[0].description or ""
        assert description.startswith("Standings, 8 playoff spots: Pulsar 16-2")
        assert "Below the cut: Vipers 8-10" in description
        assert description.endswith("Eliminated: Bandits, Rogues.")

    def test_final_standings(self):
        texts = _texts(_card(samples.master_hunt(complete=True), graphics=True).render()[0])
        assert texts[0] == "-# SEASON 24 · FINAL STANDINGS"
        assert texts[1].endswith("Regular season complete")
        assert "On the bubble" not in texts[-1]


class TestLimits:
    @pytest.mark.parametrize("graphics", [False, True], ids=["text", "graphic"])
    def test_large_tier_fits(self, graphics):
        view, _ = _card(samples.large_hunt(), graphics=graphics).render()
        assert view.total_children_count <= 40
        assert view.content_length() <= 4000

    def test_alt_text_fits(self):
        for race in build_races(samples.large_hunt()):
            assert len(alt_text(race, whole_tier=False)) <= 256


# The graphic


def _decode(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


class TestRender:
    @pytest.mark.parametrize("whole_tier", [False, True], ids=["conferences", "whole-tier"])
    def test_renders_a_valid_image_per_group(self, whole_tier):
        h = samples.master_hunt() if whole_tier else samples.elite_hunt()
        images = render_graphics(build_races(h), tier=h.tier_name, season=24, colour=ORANGE, whole_tier=whole_tier)
        assert len(images) == len(h.groups)
        for data in images:
            img = _decode(data)
            assert img.format == "PNG"
            assert img.width == 1280
            assert len(data) < 400_000

    def test_long_names_and_a_final_season_render(self):
        for h in (samples.large_hunt(), samples.elite_hunt(complete=True)):
            for data in render_graphics(build_races(h), tier=h.tier_name, season=24, colour=ORANGE, whole_tier=False):
                assert _decode(data).width == 1280

    def test_more_rows_make_a_taller_image(self):
        elite = render_graphics(build_races(samples.elite_hunt()), tier="Elite", season=24, colour=ORANGE, whole_tier=False)
        master = render_graphics(build_races(samples.master_hunt()), tier="Master", season=24, colour=ORANGE, whole_tier=True)
        assert _decode(master[0]).height > _decode(elite[0]).height

    @pytest.mark.parametrize("text", [False, True], ids=["graphic", "text"])
    def test_both_message_layouts_render(self, text):
        h = samples.master_hunt()
        images = () if text else render_graphics(build_races(h), tier="Master", season=24, colour=ORANGE, whole_tier=True)
        view, files = replace(_card(h), graphics=images).render()
        assert view.total_children_count <= 40
        assert len(files) == (0 if text else 1)


class TestPills:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Pulsar", ("CLINCHED", graphic.Pill.SOLID_GREEN)),
            ("Raptors", ("1 TO CLINCH", graphic.Pill.RING_GREEN)),
            ("Spartans", ("4 TO CLINCH", graphic.Pill.SOLID_AMBER)),
            ("Vipers", ("1 BACK", graphic.Pill.RING_AMBER)),
            ("Cyclones", ("2 BACK", graphic.Pill.RING_AMBER)),
            ("Bandits", ("ELIMINATED", graphic.Pill.DIM)),
        ],
    )
    def test_pill(self, name, expected):
        assert pill(_race_team(samples.master_hunt(), name)) == expected

    def test_holding_and_draws(self):
        teams = [
            team(1, "Alpha", 10, 2, reason="cut", draw="provisional", delta="Random draw (provisional)"),
            team(2, "Bravo", 6, 6, delta="Random draw (provisional)", draw="provisional"),
        ]
        h = hunt([group("Lunar", 1, teams)], fmt="CONF")
        assert pill(_race_team(h, "Alpha")) == ("HOLDING", graphic.Pill.SOLID_AMBER)
        assert pill(_race_team(h, "Bravo")) == ("RANDOM DRAW", graphic.Pill.RING_AMBER)


# The cache


async def _graphics(h: TierPlayoffHunt, cache: GraphicCache, colour: tuple[int, int, int] = ORANGE) -> tuple[bytes, ...]:
    return await race_graphics(h, build_races(h), season=24, colour=colour, key=(1, 7, 24), whole_tier=True, cache=cache)


class TestGraphicCache:
    async def test_hit_reuses_the_render(self):
        cache = GraphicCache()
        with patch.object(graphic, "render_graphics", MagicMock(return_value=(b"png",))) as render:
            first = await _graphics(samples.master_hunt(), cache)
            second = await _graphics(samples.master_hunt(), cache)
        assert first == second == (b"png",)
        render.assert_called_once()

    async def test_changed_standings_miss_and_replace(self):
        cache = GraphicCache()
        with patch.object(graphic, "render_graphics", MagicMock(side_effect=[(b"before",), (b"after",)])) as render:
            await _graphics(samples.master_hunt(), cache)
            images = await _graphics(samples.master_hunt(complete=True), cache)
        assert images == (b"after",)
        assert render.call_count == 2
        assert len(cache) == 1

    async def test_changed_colour_misses(self):
        cache = GraphicCache()
        with patch.object(graphic, "render_graphics", MagicMock(return_value=(b"png",))) as render:
            await _graphics(samples.master_hunt(), cache)
            await _graphics(samples.master_hunt(), cache, colour=(0, 0, 255))
        assert render.call_count == 2

    async def test_renders_off_the_event_loop(self):
        with patch.object(graphic.asyncio, "to_thread", AsyncMock(return_value=(b"png",))) as to_thread:
            await _graphics(samples.master_hunt(), GraphicCache())
        to_thread.assert_awaited_once()
        assert to_thread.await_args_list[0].args[0] is graphic.render_graphics

    def test_bounded_least_recently_used_goes_first(self):
        cache = GraphicCache(maxsize=2)
        cache.put((1, 1, 24), "a", (b"1",))
        cache.put((1, 2, 24), "b", (b"2",))
        assert cache.get((1, 1, 24), "a") == (b"1",)
        cache.put((1, 3, 24), "c", (b"3",))
        assert len(cache) == 2
        assert cache.get((1, 2, 24), "b") is None
        assert cache.get((1, 1, 24), "a") == (b"1",)
        assert cache.get((1, 3, 24), "c") == (b"3",)

    def test_keys_are_per_guild_tier_and_season(self):
        cache = GraphicCache()
        cache.put((1, 7, 24), "a", (b"1",))
        assert cache.get((2, 7, 24), "a") is None
        assert cache.get((1, 7, 23), "a") is None
        assert cache.get((1, 7, 24), "other") is None


def test_build_races_skips_empty_groups():
    races = build_races(hunt([group("Solar", 2, []), samples.lunar()]))
    assert [race.label for race in races] == ["Lunar"]
    assert len(races[0].teams) == 8


# /playoffs command

playoffs_cmd = command_callback(StatsMixIn._playoffs_cmd)


def _interaction(user_id: int = 42) -> MagicMock:
    interaction = MagicMock()
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = 1
    interaction.user.id = user_id
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _cmd_cog(players=None, h: TierPlayoffHunt | None = None) -> MagicMock:
    cog = MagicMock()
    cog.players = AsyncMock(return_value=players if players is not None else [])
    cog.tier_id_by_name = AsyncMock(return_value=7)
    cog.current_season = AsyncMock(return_value=SimpleNamespace(number=28, id=11))
    cog.tier_playoff_hunt = AsyncMock(return_value=h or samples.elite_hunt())
    cog.standings_link = AsyncMock(return_value="https://www.rscna.com/standings/")
    return cog


def _league_player(tier_id: int | None, tier_name: str = "Elite") -> SimpleNamespace:
    tier = SimpleNamespace(id=tier_id, name=tier_name) if tier_id is not None else None
    return SimpleNamespace(tier=tier)


@pytest.fixture(autouse=True)
def _no_tier_color():
    with patch("rsc.stats.stats.tier_color_by_name", AsyncMock(return_value=discord.Color.orange())):
        yield


@pytest.fixture(autouse=True)
def graphics():
    async def fake(hunt, races, **kwargs):
        return tuple(b"image" for _ in races)

    with patch("rsc.stats.stats.race_graphics", AsyncMock(side_effect=fake)) as mock:
        yield mock


class TestPlayoffsCommandOutput:
    async def test_graphic_by_default(self, graphics):
        interaction = _interaction()

        await playoffs_cmd(_cmd_cog(), interaction, tier="Elite")

        graphics.assert_awaited_once()
        assert graphics.await_args.kwargs["key"] == (1, 7, 28)
        kwargs = interaction.followup.send.await_args.kwargs
        assert [f.filename for f in kwargs["files"]] == ["playoffs-1.png", "playoffs-2.png"]
        assert any(isinstance(item, ui.MediaGallery) for item in kwargs["view"].walk_children())

    async def test_text_shows_the_race_board(self, graphics):
        interaction = _interaction()

        await playoffs_cmd(_cmd_cog(), interaction, tier="Elite", text=True)

        graphics.assert_not_called()
        kwargs = interaction.followup.send.await_args.kwargs
        assert kwargs["files"] == []
        view = kwargs["view"]
        assert not any(isinstance(item, ui.MediaGallery) for item in view.walk_children())
        assert any(t.startswith("-# BELOW THE CUT") for t in _texts(view))

    async def test_text_option_is_described(self):
        param = next(p for p in StatsMixIn._playoffs_cmd.parameters if p.name == "text")
        assert param.description == "Show the text race board instead of the graphic"
        assert param.required is False

    async def test_link_uses_the_current_season_id(self):
        cog = _cmd_cog()

        await playoffs_cmd(cog, _interaction(), tier="Elite")

        assert cog.standings_link.await_args.kwargs == {"tier": "Elite", "season": 28, "season_id": 11}

    async def test_empty_hunt_keeps_the_waiting_message(self, graphics):
        interaction = _interaction()

        await playoffs_cmd(_cmd_cog(h=hunt([group("Lunar", 0, [])])), interaction, tier="Elite")

        embed = interaction.followup.send.await_args.kwargs["embed"]
        assert "No playoff hunt yet" in embed.description
        graphics.assert_not_called()


class TestPlayoffsCommandTier:
    async def test_explicit_tier_skips_player_lookup(self):
        cog = _cmd_cog()

        await playoffs_cmd(cog, _interaction(), tier="Elite")

        cog.players.assert_not_called()
        cog.tier_id_by_name.assert_awaited_once()
        assert cog.tier_playoff_hunt.await_args.kwargs["tier_id"] == 7

    async def test_no_tier_uses_callers_tier(self):
        cog = _cmd_cog(players=[_league_player(3)])

        await playoffs_cmd(cog, _interaction(user_id=42))

        cog.players.assert_awaited_once()
        kwargs = cog.players.await_args.kwargs
        assert kwargs["discord_id"] == 42
        assert kwargs["season_number"] is None
        cog.tier_id_by_name.assert_not_called()
        assert cog.tier_playoff_hunt.await_args.kwargs["tier_id"] == 3

    async def test_no_tier_with_season_uses_tier_from_that_season(self):
        cog = _cmd_cog(players=[_league_player(5)])

        await playoffs_cmd(cog, _interaction(), season=26)

        assert cog.players.await_args.kwargs["season_number"] == 26
        assert cog.tier_playoff_hunt.await_args.kwargs == {"tier_id": 5, "season": 26}
        # standings_link looks the season ID up from the number
        assert cog.standings_link.await_args.kwargs["season_id"] is None

    @pytest.mark.parametrize("players", [[], [_league_player(None)]], ids=["not-a-league-player", "no-tier"])
    async def test_no_tier_and_none_found_errors(self, players):
        cog = _cmd_cog(players=players)
        interaction = _interaction()

        await playoffs_cmd(cog, interaction)

        embed = interaction.followup.send.await_args.kwargs["embed"]
        assert "can't determine your tier" in embed.description
        assert "`tier`" in embed.description
        cog.tier_playoff_hunt.assert_not_called()

    async def test_player_lookup_api_error_is_reported(self):
        cog = _cmd_cog()
        cog.players.side_effect = RscException(ApiException(status=500, reason="Server Error"))
        interaction = _interaction()

        await playoffs_cmd(cog, interaction)

        interaction.followup.send.assert_awaited_once()
        cog.tier_playoff_hunt.assert_not_called()


class TestStandingsLink:
    def _cog(self, host: str | None) -> MagicMock:
        cog = MagicMock()
        cog._api_conf = {1: SimpleNamespace(host=host)} if host else {}
        cog._league = {1: 1}
        cog.season_id_for_number = AsyncMock(return_value=11)
        return cog

    async def test_link(self):
        url = await StatsMixIn.standings_link(self._cog("https://www.rscna.com/api/v1"), MagicMock(id=1), tier="Elite", season=24)
        assert url == "https://www.rscna.com/standings/?league=1&season=11&tier=Elite&mode=playoffs"

    async def test_known_season_id_skips_the_lookup(self):
        cog = self._cog("https://www.rscna.com/api/v1")
        url = await StatsMixIn.standings_link(cog, MagicMock(id=1), tier="Elite", season=24, season_id=9)
        assert url == "https://www.rscna.com/standings/?league=1&season=9&tier=Elite&mode=playoffs"
        cog.season_id_for_number.assert_not_called()

    async def test_no_site_no_link(self):
        assert await StatsMixIn.standings_link(self._cog(None), MagicMock(id=1), tier="Elite", season=24) is None
