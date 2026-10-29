"""Tests for announcing trades performed outside Discord.

The builder tests are driven from realistic `TransactionResponseSerializer` payloads
parsed through `TransactionResponse.from_dict`, which is exactly what the handler
does with a `PTR` event payload.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from rscapi.models.transaction_response import TransactionResponse

from discord import ui
from rscapi.models.franchise_gm import FranchiseGM
from rscapi.models.team_franchise import TeamFranchise
from rscapi.models.team_list import TeamList

from rsc.events.models import LeagueEventData
from rsc.transactions.trade_announce import (
    TRADE_ANNOUNCE_MAX_AGE,
    FranchiseRef,
    announce_trade,
    apply_trade_role_updates,
    build_trade_card,
    process_trade_event,
)

GUILD_ID = 1
LEAGUE_ID = 7

WOLVES_GM = 100
FLARES_GM = 200
COMETS_GM = 300


def franchise(name: str, gm_id: int, gm_name: str = "GM", prefix: str = "XX", fid: int | None = None) -> dict:
    return {"gm": {"rsc_name": gm_name, "discord_id": gm_id}, "name": name, "id": fid, "prefix": prefix}


def player_update(
    discord_id: int | None,
    dest_name: str,
    dest_gm: int,
    team_name: str = "Comets",
    *,
    player_name: str = "SomePlayer",
    dest_id: int | None = 12,
    new_team: bool = True,
) -> dict:
    """A player move. `player.team` is the POST-trade team, matching the API."""
    return {
        "player": {
            "id": 4821,
            "league": {"id": LEAGUE_ID, "name": "RSC 3v3", "guild_id": GUILD_ID},
            "status": "RO",
            "season": 21,
            "captain": False,
            "contract_length": 2,
            "current_mmr": 1600,
            "base_mmr": 1600,
            "team": {
                "name": team_name,
                "franchise": {
                    "name": dest_name,
                    "id": dest_id,
                    "gm": {"rsc_name": "GM", "discord_id": dest_gm},
                    "prefix": "XX",
                },
                "id": 331,
            },
            "last_updated": "2026-08-04T18:22:11Z",
            "previous_teams": [],
            "player": {"name": player_name, "rsc_id": "RSC000123", "discord_id": discord_id},
            "tier": {"name": "Master", "id": 3, "color": 1, "position": 2},
            "sub_status": 0,
            "waiver_period_end_date": None,
            "signed_date": "2026-06-01T00:00:00Z",
        },
        "old_team": {"id": 208, "name": "Wolves", "tier": "Master"},
        "new_team": {"id": 331, "name": team_name, "tier": "Master"} if new_team else None,
    }


def pick_trade(
    dest_name: str,
    dest_gm: int,
    *,
    source_name: str | None = None,
    source_gm: int | None = None,
    round_no: int | None = 1,
    number: int | None = 4,
    tier: str = "Master",
    future: bool = False,
    season: int = 0,
    original: str | None = None,
) -> dict:
    return {
        "pick": {
            "id": 9931,
            "number": number,
            "round": round_no,
            "tier": tier,
            "future_pick": future,
            "future_season": season,
            "pick_from": None,
            "original_pick": original,
        },
        "source": franchise(source_name, source_gm) if source_name and source_gm else None,
        "destination": franchise(dest_name, dest_gm),
    }


def response(
    *,
    players: list[dict] | None = None,
    picks: list[dict] | None = None,
    first: dict | None = None,
    second: dict | None = None,
    ttype: str = "TRD",
    transaction_id: int = 55123,
) -> TransactionResponse:
    parsed = TransactionResponse.from_dict(
        {
            "player_updates": players,
            "pick_trades": picks,
            "date": "2026-08-04T18:22:11Z",
            "week": "REG",
            "week_no": 4,
            "match_day": 8,
            "type": ttype,
            "notes": "test trade",
            "first_franchise": first,
            "second_franchise": second,
            "executor": {"rsc_name": "Staff", "rsc_id": "RSC1", "discord_id": 999},
            "id": transaction_id,
        }
    )
    assert parsed is not None
    return parsed


@pytest.fixture
def guild() -> MagicMock:
    g = MagicMock(spec=discord.Guild)
    g.id = GUILD_ID
    g.name = "Test Guild"
    g.icon = None
    g.roles = []
    g.get_member = MagicMock(return_value=None)
    return g


def texts(view: ui.LayoutView) -> list[str]:
    return [c.content for c in view.walk_children() if isinstance(c, ui.TextDisplay)]


def containers(view: ui.LayoutView) -> list[ui.Container]:
    return [c for c in view.children if isinstance(c, ui.Container)]


def card_names(view: ui.LayoutView) -> list[str]:
    """Each card's franchise heading, in order."""
    names = []
    for container in containers(view):
        first = next(c for c in container.walk_children() if isinstance(c, ui.TextDisplay))
        names.append(first.content.split("\n")[0].removeprefix("### "))
    return names


def card(view: ui.LayoutView, name: str) -> ui.Container:
    return containers(view)[card_names(view).index(name)]


def bodies(container: ui.Container) -> list[str]:
    """Each block under a thin line, its heading and content rejoined: one per giver, without the RECEIVES line heading the first."""
    blocks: list[list[str]] = []
    for child in list(container.children)[1:]:
        if isinstance(child, ui.Separator) and child.visible:
            blocks.append([])
        elif isinstance(child, ui.TextDisplay):
            blocks[-1].append(child.content)
    texts = ["\n".join(block) for block in blocks]
    if texts:
        texts[0] = texts[0].removeprefix("-# RECEIVES\n")
    return texts


async def render(cog, guild, resp, **kwargs) -> ui.LayoutView:
    view, _ = (await build_trade_card(cog, guild, resp, **kwargs)).render()
    return view


@pytest.fixture
def cog() -> MagicMock:
    return make_cog(trade_settings())


class TestGrouping:
    async def test_one_card_per_receiving_franchise(self, cog, guild):
        resp = response(
            players=[player_update(111, "Thunder Wolves", WOLVES_GM)],
            picks=[pick_trade("Solar Flares", FLARES_GM)],
        )
        view = await render(cog, guild, resp)

        assert card_names(view) == ["Thunder Wolves", "Solar Flares"]

    async def test_interleaved_input_does_not_duplicate_a_franchise(self, cog, guild):
        """`itertools.groupby` only groups adjacent runs, so this ordering would
        emit the same franchise twice. Keying on a dict makes it impossible."""
        resp = response(
            players=[
                player_update(111, "Thunder Wolves", WOLVES_GM),
                player_update(222, "Solar Flares", FLARES_GM),
                player_update(333, "Thunder Wolves", WOLVES_GM),
            ],
        )
        view = await render(cog, guild, resp)

        assert card_names(view) == ["Thunder Wolves", "Solar Flares"]
        wolves = "\n".join(bodies(card(view, "Thunder Wolves")))
        assert "<@111>" in wolves
        assert "<@333>" in wolves

    async def test_franchise_as_both_pick_source_and_player_destination_collapses(self, cog, guild):
        resp = response(
            players=[player_update(111, "Thunder Wolves", WOLVES_GM)],
            picks=[pick_trade("Solar Flares", FLARES_GM, source_name="Thunder Wolves", source_gm=WOLVES_GM)],
        )
        view = await render(cog, guild, resp)

        assert len(containers(view)) == 2

    async def test_null_franchise_id_does_not_split_a_franchise(self, cog, guild):
        """`PlayerFranchise.id` is Optional while `TransactionFranchise.id` is not,
        so keying on id would split one franchise across two cards."""
        resp = response(
            players=[player_update(111, "Thunder Wolves", WOLVES_GM, dest_id=None)],
            picks=[pick_trade("Thunder Wolves", WOLVES_GM)],
        )
        view = await render(cog, guild, resp)

        assert len(containers(view)) == 1

    async def test_franchise_with_nothing_received_is_omitted(self, cog, guild):
        resp = response(
            players=[player_update(111, "Thunder Wolves", WOLVES_GM)],
            first=franchise("Thunder Wolves", WOLVES_GM),
            second=franchise("Solar Flares", FLARES_GM),
        )
        view = await render(cog, guild, resp)

        assert card_names(view) == ["Thunder Wolves"]

    async def test_cards_follow_first_and_second_franchise(self, cog, guild):
        resp = response(
            players=[player_update(111, "Thunder Wolves", WOLVES_GM), player_update(222, "Solar Flares", FLARES_GM)],
            first=franchise("Solar Flares", FLARES_GM),
            second=franchise("Thunder Wolves", WOLVES_GM),
        )
        view = await render(cog, guild, resp)

        assert card_names(view) == ["Solar Flares", "Thunder Wolves"]


class TestGivers:
    async def test_two_franchise_trade_labels_the_other_franchise(self, cog, guild):
        resp = response(
            players=[player_update(111, "Thunder Wolves", WOLVES_GM)],
            picks=[pick_trade("Solar Flares", FLARES_GM, source_name="Thunder Wolves", source_gm=WOLVES_GM)],
            first=franchise("Thunder Wolves", WOLVES_GM),
            second=franchise("Solar Flares", FLARES_GM),
        )
        view = await render(cog, guild, resp)

        # Labelled like a bigger trade, without pinging GMs who already have a card
        assert bodies(card(view, "Thunder Wolves"))[0].startswith("-# From Solar Flares\n")
        assert bodies(card(view, "Solar Flares"))[0].startswith("-# From Thunder Wolves\n")
        cog.teams.assert_not_awaited()

    async def test_three_franchises_label_each_giver_and_split_with_a_line(self, cog, guild):
        """Wolves receive from Flares and Comets: two groups, a thin line between them."""
        resp = response(
            picks=[
                pick_trade("Thunder Wolves", WOLVES_GM, source_name="Solar Flares", source_gm=FLARES_GM),
                pick_trade("Thunder Wolves", WOLVES_GM, source_name="Comets", source_gm=COMETS_GM, round_no=2),
                pick_trade("Solar Flares", FLARES_GM, source_name="Thunder Wolves", source_gm=WOLVES_GM),
            ],
        )
        view = await render(cog, guild, resp)

        wolves = card(view, "Thunder Wolves")
        header, line, first, _, _, between, second, _, _ = wolves.children
        assert isinstance(header, ui.TextDisplay)
        assert isinstance(line, ui.Separator) and line.visible
        assert isinstance(between, ui.Separator) and between.visible
        assert isinstance(first, ui.TextDisplay) and first.content == "-# RECEIVES\n-# From Solar Flares"
        # Comets receive nothing, so their GM is pinged by the label instead of a card of their own
        assert isinstance(second, ui.TextDisplay) and second.content == f"-# From Comets · **GM** <@{COMETS_GM}>"

    async def test_givers_with_a_card_of_their_own_are_not_pinged_by_the_label(self, cog, guild):
        resp = response(
            picks=[
                pick_trade("Thunder Wolves", WOLVES_GM, source_name="Solar Flares", source_gm=FLARES_GM),
                pick_trade("Solar Flares", FLARES_GM, source_name="Thunder Wolves", source_gm=WOLVES_GM),
                pick_trade("Solar Flares", FLARES_GM, source_name="Comets", source_gm=COMETS_GM),
            ],
        )
        view = await render(cog, guild, resp)

        assert bodies(card(view, "Thunder Wolves"))[0].startswith("-# From Solar Flares\n")
        assert bodies(card(view, "Solar Flares"))[0].startswith("-# From Thunder Wolves\n")
        assert bodies(card(view, "Solar Flares"))[1].startswith(f"-# From Comets · **GM** <@{COMETS_GM}>\n")

    async def test_pick_only_giver_in_a_two_franchise_trade_is_labelled_to_ping_its_gm(self, cog, guild):
        resp = response(
            picks=[pick_trade("Solar Flares", FLARES_GM, source_name="Thunder Wolves", source_gm=WOLVES_GM)],
            first=franchise("Thunder Wolves", WOLVES_GM),
            second=franchise("Solar Flares", FLARES_GM),
        )
        view = await render(cog, guild, resp)

        assert card_names(view) == ["Solar Flares"]
        assert bodies(card(view, "Solar Flares"))[0].startswith(f"-# From Thunder Wolves · **GM** <@{WOLVES_GM}>\n")

    async def test_player_giver_found_from_the_old_team(self, cog, guild):
        """The response names a player's old team only, so a 3-team trade looks it up."""
        cog.teams = AsyncMock(
            return_value=[
                TeamList.model_construct(
                    name="Wolves",
                    franchise=TeamFranchise.model_construct(name="Comets", gm=FranchiseGM.model_construct(discord_id=COMETS_GM)),
                )
            ]
        )
        resp = response(
            players=[player_update(111, "Thunder Wolves", WOLVES_GM)],
            picks=[
                pick_trade("Solar Flares", FLARES_GM, source_name="Thunder Wolves", source_gm=WOLVES_GM),
                pick_trade("Comets", COMETS_GM, source_name="Solar Flares", source_gm=FLARES_GM),
            ],
        )
        view = await render(cog, guild, resp)

        assert bodies(card(view, "Thunder Wolves")) == ["-# From Comets\n- **Player** <@111> → Comets"]
        cog.teams.assert_awaited_once_with(guild, name="Wolves", tier="Master")

    async def test_player_sources_skip_the_lookup(self, cog, guild):
        resp = response(
            players=[player_update(111, "Thunder Wolves", WOLVES_GM)],
            picks=[
                pick_trade("Solar Flares", FLARES_GM, source_name="Thunder Wolves", source_gm=WOLVES_GM),
                pick_trade("Comets", COMETS_GM, source_name="Solar Flares", source_gm=FLARES_GM),
            ],
        )
        view = await render(cog, guild, resp, player_sources={111: FranchiseRef(COMETS_GM, "Comets")})

        assert bodies(card(view, "Thunder Wolves"))[0].startswith("-# From Comets\n")
        cog.teams.assert_not_awaited()

    async def test_unknown_player_giver_still_shows_the_player(self, cog, guild):
        resp = response(
            players=[player_update(111, "Thunder Wolves", WOLVES_GM)],
            picks=[
                pick_trade("Solar Flares", FLARES_GM, source_name="Thunder Wolves", source_gm=WOLVES_GM),
                pick_trade("Comets", COMETS_GM, source_name="Solar Flares", source_gm=FLARES_GM),
            ],
        )
        view = await render(cog, guild, resp)

        assert bodies(card(view, "Thunder Wolves")) == ["- **Player** <@111> → Comets"]


class TestLines:
    async def test_player_line_includes_destination_team(self, cog, guild):
        resp = response(players=[player_update(111, "Thunder Wolves", WOLVES_GM, team_name="Comets")])
        view = await render(cog, guild, resp)

        assert bodies(card(view, "Thunder Wolves")) == ["- **Player** <@111> → Comets"]

    async def test_player_without_new_team_omits_the_destination(self, cog, guild):
        resp = response(players=[player_update(111, "Thunder Wolves", WOLVES_GM, new_team=False)])
        view = await render(cog, guild, resp)

        assert bodies(card(view, "Thunder Wolves")) == ["- **Player** <@111>"]

    async def test_player_without_discord_id_falls_back_to_name(self, cog, guild):
        resp = response(players=[player_update(None, "Thunder Wolves", WOLVES_GM, player_name="No_Discord")])
        view = await render(cog, guild, resp)

        # Escaped, so the underscore can't start italics
        assert "No\\_Discord" in bodies(card(view, "Thunder Wolves"))[0]

    @pytest.mark.parametrize(
        ("round_no", "expected"),
        [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th")],
    )
    async def test_pick_round_ordinals(self, cog, guild, round_no, expected):
        resp = response(picks=[pick_trade("Solar Flares", FLARES_GM, round_no=round_no)])
        view = await render(cog, guild, resp)

        assert bodies(card(view, "Solar Flares")) == [f"- **Pick** {expected} Round Master, pick 4"]

    async def test_null_round_does_not_render_noneth(self, cog, guild):
        """`TransactionPick.round` is Optional; the original builder produced `"Noneth"`."""
        resp = response(picks=[pick_trade("Solar Flares", FLARES_GM, round_no=None)])
        view = await render(cog, guild, resp)

        assert bodies(card(view, "Solar Flares")) == ["- **Pick** Unknown Round Master, pick 4"]

    async def test_null_pick_number_omits_the_pick(self, cog, guild):
        resp = response(picks=[pick_trade("Solar Flares", FLARES_GM, number=None)])
        view = await render(cog, guild, resp)

        assert bodies(card(view, "Solar Flares")) == ["- **Pick** 1st Round Master"]

    async def test_future_pick_shows_its_season(self, cog, guild):
        resp = response(picks=[pick_trade("Solar Flares", FLARES_GM, future=True, season=25)])
        view = await render(cog, guild, resp)

        assert bodies(card(view, "Solar Flares")) == ["- **Future Pick** S25 1st Round Master"]

    async def test_future_pick_without_a_season(self, cog, guild):
        """The API sends 0 when a future pick has no season."""
        resp = response(picks=[pick_trade("Solar Flares", FLARES_GM, future=True, season=0)])
        view = await render(cog, guild, resp)

        assert bodies(card(view, "Solar Flares")) == ["- **Future Pick** 1st Round Master"]

    async def test_via_tag_when_the_original_owner_is_not_the_giver(self, cog, guild):
        resp = response(
            picks=[pick_trade("Solar Flares", FLARES_GM, source_name="Thunder Wolves", source_gm=WOLVES_GM, original="CMT")],
        )
        view = await render(cog, guild, resp)

        assert bodies(card(view, "Solar Flares")) == [
            f"-# From Thunder Wolves · **GM** <@{WOLVES_GM}>\n- **Pick** 1st Round Master, pick 4 · via CMT"
        ]

    async def test_no_via_tag_for_the_givers_own_pick(self, cog, guild):
        resp = response(
            picks=[pick_trade("Solar Flares", FLARES_GM, source_name="Thunder Wolves", source_gm=WOLVES_GM, original="XX")],
        )
        view = await render(cog, guild, resp)

        assert "via" not in bodies(card(view, "Solar Flares"))[0]

    async def test_pick_from_its_own_destination_is_unlabelled(self, cog, guild):
        resp = response(
            picks=[
                pick_trade("Solar Flares", FLARES_GM, source_name="Solar Flares", source_gm=FLARES_GM),
                pick_trade("Comets", COMETS_GM, source_name="Thunder Wolves", source_gm=WOLVES_GM),
            ]
        )
        view = await render(cog, guild, resp)

        assert bodies(card(view, "Solar Flares")) == ["- **Pick** 1st Round Master, pick 4"]

    async def test_future_picks_each_get_their_own_line_in_order(self, cog, guild):
        picks = [
            pick_trade(
                "Solar Flares", FLARES_GM, source_name="Thunder Wolves", source_gm=WOLVES_GM, future=True, season=s, round_no=r, number=None
            )
            for s in (25, 26)
            for r in (2, 1)
        ]
        view = await render(cog, guild, response(picks=picks))

        assert bodies(card(view, "Solar Flares"))[0].split("\n") == [
            f"-# From Thunder Wolves · **GM** <@{WOLVES_GM}>",
            "- **Future Pick** S26 1st Round Master",
            "- **Future Pick** S26 2nd Round Master",
            "- **Future Pick** S25 1st Round Master",
            "- **Future Pick** S25 2nd Round Master",
        ]


class TestHeaderAndPings:
    async def test_header_is_the_franchise_and_gm_with_receives_under_the_line(self, cog, guild):
        resp = response(players=[player_update(111, "Thunder Wolves", WOLVES_GM)])
        view = await render(cog, guild, resp)

        header, line, heading, space, body = card(view, "Thunder Wolves").children
        assert isinstance(header, ui.TextDisplay)
        assert header.content == f"### Thunder Wolves\n**GM** <@{WOLVES_GM}>"
        assert isinstance(line, ui.Separator) and line.visible
        assert isinstance(heading, ui.TextDisplay) and heading.content == "-# RECEIVES"
        assert isinstance(space, ui.Separator) and not space.visible
        assert isinstance(body, ui.TextDisplay) and body.content.startswith("- **Player** <@111>")

    async def test_logo_sits_beside_the_header(self, cog, guild):
        cog.franchise_logo = AsyncMock(return_value="https://cdn.example/wolves.png")
        resp = response(players=[player_update(111, "Thunder Wolves", WOLVES_GM, dest_id=12)])
        view = await render(cog, guild, resp)

        section = card(view, "Thunder Wolves").children[0]
        assert isinstance(section, ui.Section)
        assert [t.content for t in section.children if isinstance(t, ui.TextDisplay)] == [
            "### Thunder Wolves",
            f"**GM** <@{WOLVES_GM}>",
        ]
        assert isinstance(section.accessory, ui.Thumbnail)
        cog.franchise_logo.assert_awaited_once_with(guild, 12)

    async def test_every_gm_and_player_is_mentioned_in_a_text_display(self, cog, guild):
        resp = response(
            players=[player_update(111, "Thunder Wolves", WOLVES_GM), player_update(222, "Solar Flares", FLARES_GM)],
            picks=[pick_trade("Comets", COMETS_GM, source_name="Thunder Wolves", source_gm=WOLVES_GM)],
        )
        view = await render(cog, guild, resp, player_sources={})
        text = "\n".join(texts(view))

        for discord_id in (WOLVES_GM, FLARES_GM, COMETS_GM, 111, 222):
            assert f"<@{discord_id}>" in text

    async def test_accent_is_the_franchise_role_colour(self, cog, guild):
        role = MagicMock(spec=discord.Role)
        role.name = "Thunder Wolves"
        role.colour = discord.Colour(0xE67E22)
        guild.roles = [role]
        resp = response(players=[player_update(111, "Thunder Wolves", WOLVES_GM)])
        view = await render(cog, guild, resp)

        assert card(view, "Thunder Wolves").accent_colour == discord.Colour(0xE67E22)

    async def test_accent_falls_back_to_the_tier_colour(self, cog, guild):
        tier_role = MagicMock(spec=discord.Role)
        tier_role.name = "Master"
        tier_role.color = discord.Colour(0x9B59B6)
        tier_role.colour = tier_role.color
        guild.roles = [tier_role]
        resp = response(players=[player_update(111, "Thunder Wolves", WOLVES_GM)])
        view = await render(cog, guild, resp)

        assert card(view, "Thunder Wolves").accent_colour == discord.Colour(0x9B59B6)

    async def test_footer_carries_the_transaction_id(self, cog, guild):
        resp = response(players=[player_update(111, "Thunder Wolves", WOLVES_GM)], transaction_id=48214)
        view = await render(cog, guild, resp)

        footer = view.children[-1]
        assert isinstance(footer, ui.TextDisplay)
        assert footer.content.startswith("-# Transaction ID: 48214 · <t:")

    async def test_banner_is_the_header(self, cog, guild):
        resp = response(players=[player_update(111, "Thunder Wolves", WOLVES_GM)])
        view, files = (await build_trade_card(cog, guild, resp)).render()

        gallery = view.children[0]
        assert isinstance(gallery, ui.MediaGallery)
        assert [item.media.url for item in gallery.items] == ["attachment://Trade.png"]
        assert [f.filename for f in files] == ["Trade.png"]


class TestLimits:
    async def test_large_pick_dump_stays_within_message_limits(self, cog, guild):
        picks = [
            pick_trade("Solar Flares", FLARES_GM, source_name="Thunder Wolves", source_gm=WOLVES_GM, number=n, original="CMT")
            for n in range(400)
        ]
        view = await render(cog, guild, response(picks=picks))

        assert view.total_children_count <= 40
        assert sum(len(t) for t in texts(view)) <= 4000
        # Truncation is disclosed
        assert any("more picks" in t for t in texts(view))


class TestPickOnlyTrade:
    async def test_pick_only_trade_still_renders(self, cog, guild):
        """`player_updates` is Optional and empty for a pure futures trade."""
        resp = response(players=None, picks=[pick_trade("Solar Flares", FLARES_GM)])
        view = await render(cog, guild, resp)

        assert len(containers(view)) == 1


class FakeValue:
    def __init__(self, store: dict, key: str):
        self._store, self._key = store, key

    async def __call__(self):
        return self._store[self._key]

    async def set(self, value):
        self._store[self._key] = value


class FakeGroup:
    def __init__(self, store: dict):
        self._store = store

    def __getattr__(self, name: str) -> FakeValue:
        return FakeValue(self._store, name)

    async def all(self) -> dict:
        return dict(self._store)


class FakeConfig:
    def __init__(self, store: dict):
        self._store = store

    def custom(self, *_args) -> FakeGroup:
        return FakeGroup(self._store)


def make_cog(store: dict, *, channel: MagicMock | None = None) -> MagicMock:
    cog = MagicMock()
    cog.config = FakeConfig(store)
    cog._league = {GUILD_ID: LEAGUE_ID}
    cog._trans_channel = AsyncMock(return_value=channel)
    cog.tiers = AsyncMock(return_value=[])
    cog.teams = AsyncMock(return_value=[])
    cog.franchise_logo = AsyncMock(return_value=None)
    cog._try_post_embeds = AsyncMock()
    cog.transaction_history_by_id = AsyncMock()
    return cog


def trade_settings(**overrides) -> dict:
    store = {"TradeAnnouncements": True, "TradeRoleUpdates": True, "AnnouncedTrades": []}
    store.update(overrides)
    return store


def make_channel() -> MagicMock:
    channel = MagicMock()
    sent = []
    msg = MagicMock()
    msg.edit = AsyncMock()
    msg.jump_url = "https://discord.com/x"

    async def send(**kwargs):
        sent.append(kwargs)
        return msg

    channel.send = send
    channel.sent = sent
    return channel


def trade_event(created_at: datetime | None = None, league: int | None = LEAGUE_ID, **kw) -> LeagueEventData:
    resp = response(**kw)
    return LeagueEventData(
        id=9012,
        league=league,
        category="TRN",
        action="PTR",
        severity="INF",
        object_id=55123,
        # model_dump, never to_dict: every field on these generated models is
        # marked readOnly, so to_dict drops all of them.
        payload={"transaction": resp.model_dump(mode="json")},
        is_public=True,
        created_at=created_at or datetime.now(UTC),
    )


class TestProcessTradeEvent:
    async def test_announces_and_records_the_transaction(self, guild):
        store = trade_settings()
        channel = make_channel()
        cog = make_cog(store, channel=channel)

        await process_trade_event(cog, guild, trade_event(players=[player_update(111, "Wolves", WOLVES_GM)]))

        assert len(channel.sent) == 1
        assert store["AnnouncedTrades"] == [55123]

    async def test_replayed_transaction_is_not_announced_twice(self, guild):
        store = trade_settings(AnnouncedTrades=[55123])
        channel = make_channel()
        cog = make_cog(store, channel=channel)

        await process_trade_event(cog, guild, trade_event(players=[player_update(111, "Wolves", WOLVES_GM)]))

        assert channel.sent == []

    async def test_event_from_another_league_is_ignored(self, guild):
        """`IncludeGlobal` scopes by guild, so foreign-league events can arrive."""
        store = trade_settings()
        channel = make_channel()
        cog = make_cog(store, channel=channel)

        await process_trade_event(cog, guild, trade_event(league=999, players=[player_update(111, "W", WOLVES_GM)]))

        assert channel.sent == []
        assert store["AnnouncedTrades"] == []

    async def test_stale_event_is_not_announced(self, guild):
        store = trade_settings()
        channel = make_channel()
        cog = make_cog(store, channel=channel)
        old = datetime.now(UTC) - TRADE_ANNOUNCE_MAX_AGE - timedelta(minutes=1)

        await process_trade_event(cog, guild, trade_event(created_at=old, players=[player_update(111, "W", WOLVES_GM)]))

        assert channel.sent == []

    async def test_announcements_disabled_skips_the_send(self, guild):
        store = trade_settings(TradeAnnouncements=False)
        channel = make_channel()
        cog = make_cog(store, channel=channel)

        await process_trade_event(cog, guild, trade_event(players=[player_update(111, "W", WOLVES_GM)]))

        assert channel.sent == []
        assert store["AnnouncedTrades"] == []

    async def test_non_trade_transaction_is_ignored(self, guild):
        store = trade_settings()
        channel = make_channel()
        cog = make_cog(store, channel=channel)

        await process_trade_event(cog, guild, trade_event(ttype="CUT", players=[player_update(111, "W", WOLVES_GM)]))

        assert channel.sent == []

    async def test_unparseable_payload_reports_and_refetches(self, guild):
        store = trade_settings()
        cog = make_cog(store, channel=make_channel())
        cog.transaction_history_by_id = AsyncMock(side_effect=Exception("boom"))

        event = LeagueEventData(
            id=1,
            league=LEAGUE_ID,
            category="TRN",
            action="PTR",
            object_id=55123,
            payload={"transaction": "not a dict"},
            created_at=datetime.now(UTC),
        )
        # Must not raise - the poller relies on handlers failing quietly.
        await process_trade_event(cog, guild, event)

        assert cog._try_post_embeds.await_count == 1

    async def test_mentions_are_restricted_to_users(self, guild):
        store = trade_settings()
        channel = make_channel()
        cog = make_cog(store, channel=channel)

        await process_trade_event(cog, guild, trade_event(players=[player_update(111, "W", WOLVES_GM)]))

        mentions = channel.sent[0]["allowed_mentions"]
        assert mentions.users is True
        assert mentions.everyone is False
        assert mentions.roles is False


class TestApplyTradeRoleUpdates:
    async def test_missing_member_is_reported_not_raised(self, guild):
        cog = make_cog(trade_settings())
        resp = response(players=[player_update(111, "Wolves", WOLVES_GM)])

        errors = await apply_trade_role_updates(cog, guild, resp)

        assert len(errors) == 1
        assert "not in the server" in errors[0]

    async def test_player_without_discord_id_is_reported(self, guild):
        cog = make_cog(trade_settings())
        resp = response(players=[player_update(None, "Wolves", WOLVES_GM)])

        errors = await apply_trade_role_updates(cog, guild, resp)

        assert len(errors) == 1
        assert "Discord ID" in errors[0]

    async def test_pick_only_trade_needs_no_role_work(self, guild):
        cog = make_cog(trade_settings())
        resp = response(picks=[pick_trade("Solar Flares", FLARES_GM)])

        assert await apply_trade_role_updates(cog, guild, resp) == []


class TestAnnounceTrade:
    async def test_returns_none_when_channel_is_unconfigured(self, guild):
        cog = make_cog(trade_settings(), channel=None)
        resp = response(players=[player_update(111, "Wolves", WOLVES_GM)])

        assert await announce_trade(cog, guild, resp) is None

    async def test_sends_one_v2_message_without_editing_it(self, guild):
        """The pings come from the card's TextDisplays, so the old send-then-edit trick is gone."""
        channel = make_channel()
        cog = make_cog(trade_settings(), channel=channel)
        resp = response(players=[player_update(111, "Wolves", WOLVES_GM)])

        msg = await announce_trade(cog, guild, resp)

        assert msg is not None
        (sent,) = channel.sent
        assert isinstance(sent["view"], ui.LayoutView)
        assert "content" not in sent
        assert "embed" not in sent
        assert [f.filename for f in sent["files"]] == ["Trade.png"]
        mentions = sent["allowed_mentions"]
        assert (mentions.users, mentions.everyone, mentions.roles) == (True, False, False)
        edit = msg.edit
        assert isinstance(edit, AsyncMock)
        edit.assert_not_awaited()
