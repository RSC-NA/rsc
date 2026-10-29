"""The trade card: layout, pick order and the overflow rules, from plain card data."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import discord
import pytest
from discord import ui
from PIL import Image

from rsc.enums import TransactionType
from rsc.transactions.views import (
    TRADE_MAX_COMPONENTS,
    TradeCard,
    TradeGiver,
    TradePick,
    TradePlayer,
    TradeReceiver,
    ordinal,
)
from rsc.utils import utils

CREATED = datetime(2026, 10, 28, 21, 14, tzinfo=UTC)
TIERS = ("Premier", "Master", "Elite", "Veteran")
RESOURCES = Path(utils.__file__).parent.parent / "resources" / "transactions"


def receiver(name: str, gm_id: int, *givers: TradeGiver, logo: str | None = "https://cdn.example/logo.png") -> TradeReceiver:
    return TradeReceiver(name=name, colour=discord.Colour.orange(), givers=givers, gm_id=gm_id, logo=logo)


def trade(*receivers: TradeReceiver, transaction_id: int | None = 48214) -> TradeCard:
    return TradeCard(
        receivers=receivers,
        banner=utils.TRADE_BANNER,
        created_at=CREATED,
        transaction_id=transaction_id,
        tier_order=TIERS,
    )


def futures(*, tiers=TIERS, seasons=(25, 26), rounds=(1, 2, 3, 4)) -> tuple[TradePick, ...]:
    return tuple(TradePick(tier=t, round=r, future=True, season=s) for t in tiers for s in seasons for r in rounds)


def texts(view: ui.LayoutView) -> list[str]:
    return [c.content for c in view.walk_children() if isinstance(c, ui.TextDisplay)]


def containers(view: ui.LayoutView) -> list[ui.Container]:
    return [c for c in view.children if isinstance(c, ui.Container)]


def blocks(container: ui.Container) -> list[str]:
    """Each block under a thin line, its heading and content rejoined."""
    found: list[list[str]] = []
    for child in list(container.children)[1:]:
        if isinstance(child, ui.Separator) and child.visible:
            found.append([])
        elif isinstance(child, ui.TextDisplay):
            found[-1].append(child.content)
    return ["\n".join(block) for block in found]


def within_limits(view: ui.LayoutView) -> bool:
    return view.total_children_count <= 40 and sum(len(t) for t in texts(view)) <= 4000


def two_team() -> TradeCard:
    return trade(
        receiver(
            "Hex Systems",
            1,
            TradeGiver("Nova Syndicate", players=(TradePlayer("<@11>", "Quantum"),), picks=(TradePick("Elite", 2, number=14),)),
        ),
        receiver("Nova Syndicate", 2, TradeGiver("Hex Systems", players=(TradePlayer("<@12>", "Voltage"),))),
    )


def three_team_big() -> TradeCard:
    """The mockup's big dump: Ironclad trades two starters for 29 future picks, with two "via" picks."""
    return trade(
        receiver(
            "Hex Systems",
            1,
            TradeGiver("Ironclad", players=(TradePlayer("<@11>", "Quantum"), TradePlayer("<@12>", "Circuit"))),
            TradeGiver("Nova Syndicate", picks=(TradePick("Master", 2, number=9, via="IRN"),)),
        ),
        receiver(
            "Nova Syndicate",
            2,
            TradeGiver(
                "Hex Systems", players=(TradePlayer("<@13>", "Pulsar"),), picks=(TradePick("Elite", 1, future=True, season=25, via="IRN"),)
            ),
        ),
        receiver(
            "Ironclad",
            3,
            TradeGiver(
                "Nova Syndicate",
                players=(TradePlayer("<@14>", "Anvil"),),
                picks=(
                    TradePick("Master", 1, future=True, season=25),
                    TradePick("Master", 2, future=True, season=25),
                    TradePick("Master", 1, future=True, season=26),
                ),
            ),
            TradeGiver(
                "Hex Systems",
                picks=futures(tiers=("Premier",), rounds=(1, 2))
                + futures(tiers=("Master", "Elite"))
                + futures(tiers=("Veteran",), rounds=(1, 2, 3)),
            ),
        ),
    )


class TestLayout:
    def test_banner_on_top_then_cards_then_footer(self):
        view, files = two_team().render()

        gallery, hex_card, nova_card, footer = view.children
        assert isinstance(gallery, ui.MediaGallery)
        assert [item.media.url for item in gallery.items] == ["attachment://Trade.png"]
        assert isinstance(hex_card, ui.Container) and isinstance(nova_card, ui.Container)
        assert isinstance(footer, ui.TextDisplay)
        assert footer.content == f"-# Transaction ID: 48214 · {discord.utils.format_dt(CREATED, 'f')}"
        assert [f.filename for f in files] == ["Trade.png"]

    def test_no_label_above_the_cards(self):
        view, _ = two_team().render()

        assert not any(t.startswith("-# TRADE") for t in texts(view))

    def test_franchise_name_on_top_then_gm(self):
        view, _ = two_team().render()

        section = containers(view)[0].children[0]
        assert isinstance(section, ui.Section)
        assert [t.content for t in section.children if isinstance(t, ui.TextDisplay)] == ["### Hex Systems", "**GM** <@1>"]
        assert isinstance(section.accessory, ui.Thumbnail)
        assert section.accessory.media.url == "https://cdn.example/logo.png"

    def test_without_a_logo_the_header_is_one_block_starting_with_the_heading(self):
        card = trade(receiver("Hex Systems", 1, TradeGiver("Nova", players=(TradePlayer("<@11>"),)), logo=None))
        view, _ = card.render()

        header = containers(view)[0].children[0]
        assert isinstance(header, ui.TextDisplay)
        assert header.content == "### Hex Systems\n**GM** <@1>"

    def test_two_team_lines(self):
        view, _ = two_team().render()

        hex_card = containers(view)[0]
        _, line, heading, space, body = hex_card.children
        assert isinstance(line, ui.Separator) and line.visible
        # RECEIVES heads the first group, under the line rather than beside the GM, with a little space under it
        assert isinstance(heading, ui.TextDisplay) and heading.content == "-# RECEIVES\n-# From Nova Syndicate"
        assert isinstance(space, ui.Separator) and not space.visible
        assert space.spacing is discord.SeparatorSpacing.small
        assert isinstance(body, ui.TextDisplay)
        assert body.content == "- **Player** <@11> → Quantum\n- **Pick** 2nd Round Elite, pick 14"

    def test_accent_is_the_receivers_colour(self):
        view, _ = two_team().render()

        assert containers(view)[0].accent_colour == discord.Colour.orange()

    def test_footer_without_a_transaction_id(self):
        view, _ = replace(two_team(), transaction_id=None).render()

        assert texts(view)[-1] == f"-# {discord.utils.format_dt(CREATED, 'f')}"

    def test_each_render_has_fresh_files(self):
        card = two_team()
        _, first = card.render()
        _, second = card.render()

        assert first[0] is not second[0]


class TestGivers:
    def test_more_than_one_giver_split_by_a_thin_line(self):
        view, _ = three_team_big().render()

        ironclad = containers(view)[2]
        section, line, nova_heading, nova_space, nova, between, hex_heading, hex_space, hex_group = ironclad.children
        assert isinstance(section, ui.Section)
        assert isinstance(line, ui.Separator) and line.visible
        assert isinstance(between, ui.Separator) and between.visible
        assert between.spacing is discord.SeparatorSpacing.small
        assert isinstance(nova_heading, ui.TextDisplay) and nova_heading.content == "-# RECEIVES\n-# From Nova Syndicate"
        assert isinstance(hex_heading, ui.TextDisplay) and hex_heading.content == "-# From Hex Systems"
        # A little space under each heading
        assert isinstance(nova_space, ui.Separator) and not nova_space.visible
        assert isinstance(hex_space, ui.Separator) and not hex_space.visible
        assert isinstance(nova, ui.TextDisplay) and nova.content.startswith("- **Player** <@14> → Anvil")
        assert isinstance(hex_group, ui.TextDisplay) and hex_group.content.startswith("- **Future Pick** S26 1st Round Premier")

    def test_two_team_trade_is_labelled_like_a_bigger_one(self):
        view, _ = two_team().render()

        assert [blocks(c)[0].split("\n")[:2] for c in containers(view)] == [
            ["-# RECEIVES", "-# From Nova Syndicate"],
            ["-# RECEIVES", "-# From Hex Systems"],
        ]

    def test_giver_with_no_card_is_labelled_with_its_gm_in_a_two_team_trade(self):
        view, _ = trade(receiver("Hex Systems", 1, TradeGiver("Nova", picks=(TradePick("Elite", 1),), gm_id=2))).render()

        assert blocks(containers(view)[0]) == ["-# RECEIVES\n-# From Nova · **GM** <@2>\n- **Pick** 1st Round Elite"]

    def test_one_giver_in_a_three_team_trade_is_still_labelled(self):
        view, _ = three_team_big().render()

        assert blocks(containers(view)[1]) == [
            "-# RECEIVES\n-# From Hex Systems\n- **Player** <@13> → Pulsar\n- **Future Pick** S25 1st Round Elite · via IRN"
        ]


class TestPickOrder:
    def test_every_future_pick_gets_its_own_line(self):
        view, _ = three_team_big().render()

        lines = blocks(containers(view)[2])[-1].split("\n")
        assert lines[0] == "-# From Hex Systems"
        assert len(lines[1:]) == 26
        assert all(line.startswith("- **Future Pick** S2") for line in lines[1:])
        # The latest season first, then the highest tier down, then by round
        assert lines[1:5] == [
            "- **Future Pick** S26 1st Round Premier",
            "- **Future Pick** S26 2nd Round Premier",
            "- **Future Pick** S26 1st Round Master",
            "- **Future Pick** S26 2nd Round Master",
        ]
        assert lines[14] == "- **Future Pick** S25 1st Round Premier"

    def test_players_then_picks_then_future_picks(self):
        picks = (
            TradePick("Elite", 1, future=True, season=25),
            TradePick("Elite", 3, number=7),
            TradePick("Master", 2, future=True, season=25, via="IRN"),
        )
        view, _ = trade(receiver("Hex Systems", 1, TradeGiver("Nova", players=(TradePlayer("<@11>", "Quantum"),), picks=picks))).render()

        assert texts(view)[-2].split("\n") == [
            "- **Player** <@11> → Quantum",
            "- **Pick** 3rd Round Elite, pick 7",
            "- **Future Pick** S25 2nd Round Master · via IRN",
            "- **Future Pick** S25 1st Round Elite",
        ]

    def test_future_picks_by_latest_season_then_picks_by_tier_round_and_number(self):
        picks = (
            TradePick("Veteran", 1, number=2),
            TradePick("Premier", 2, number=5),
            TradePick("Premier", 1, number=9),
            TradePick("Premier", 1, number=3),
            TradePick("Master", 2, future=True, season=26),
            TradePick("Master", 3, future=True, season=25),
            TradePick("Premier", 4, future=True, season=26),
        )
        view, _ = trade(receiver("Hex Systems", 1, TradeGiver("Nova", picks=picks))).render()

        assert texts(view)[-2].split("\n") == [
            "- **Pick** 1st Round Premier, pick 3",
            "- **Pick** 1st Round Premier, pick 9",
            "- **Pick** 2nd Round Premier, pick 5",
            "- **Pick** 1st Round Veteran, pick 2",
            "- **Future Pick** S26 4th Round Premier",
            "- **Future Pick** S26 2nd Round Master",
            "- **Future Pick** S25 3rd Round Master",
        ]

    def test_unknown_seasons_and_rounds_sort_last(self):
        picks = (
            TradePick("Master", None, future=True, season=25),
            TradePick("Master", 1, future=True),
            TradePick("Master", 2, future=True, season=25),
        )
        view, _ = trade(receiver("Hex Systems", 1, TradeGiver("Nova", picks=picks))).render()

        assert texts(view)[-2].split("\n") == [
            "- **Future Pick** S25 2nd Round Master",
            "- **Future Pick** S25 Unknown Round Master",
            "- **Future Pick** 1st Round Master",
        ]

    @pytest.mark.parametrize(
        ("number", "expected"), [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (12, "12th"), (21, "21st")]
    )
    def test_ordinal(self, number, expected):
        assert ordinal(number) == expected


class TestLimits:
    def test_three_team_big_dump_fits_with_every_logo(self):
        view, _ = three_team_big().render()

        assert within_limits(view)
        assert all(isinstance(c.children[0], ui.Section) for c in containers(view))
        text = "\n".join(texts(view))
        for discord_id in (1, 2, 3, 11, 12, 13, 14):
            assert f"<@{discord_id}>" in text

    def test_five_franchises_drop_heading_space_before_any_logo(self):
        """Nine components a card: five cards and the banner and footer would be 47, and each dropped space saves 2."""
        receivers = [
            receiver(f"Franchise {n}", n, TradeGiver(f"Franchise {n + 1}", players=(TradePlayer(f"<@{100 + n}>", "Team"),)))
            for n in range(1, 6)
        ]
        view, _ = trade(*receivers).render()

        assert within_limits(view)
        cards = containers(view)
        assert all(isinstance(c.children[0], ui.Section) for c in cards)
        spaced = [any(isinstance(x, ui.Separator) and not x.visible for x in c.children) for c in cards]
        assert spaced == [True, False, False, False, False]
        # Without its space, the heading sits at the top of the block
        assert blocks(cards[-1]) == ["-# RECEIVES\n-# From Franchise 6\n- **Player** <@105> → Team"]

    def test_six_franchises_drop_the_last_logos(self):
        """Seven components a card: six cards and the banner and footer would be 44, and each dropped logo saves 3."""
        receivers = [
            receiver(f"Franchise {n}", n, TradeGiver(f"Franchise {n + 1}", players=(TradePlayer(f"<@{100 + n}>", "Team"),)))
            for n in range(1, 7)
        ]
        view, _ = trade(*receivers).render()

        assert within_limits(view)
        headers = [c.children[0] for c in containers(view)]
        assert [isinstance(h, ui.Section) for h in headers] == [True, True, True, True, False, False]
        text = "\n".join(texts(view))
        for n in range(1, 7):
            assert f"<@{n}>" in text
            assert f"<@{100 + n}>" in text

    def test_many_givers_share_one_block_before_cards_are_dropped(self):
        givers = tuple(TradeGiver(f"Giver {g}", players=(TradePlayer(f"<@{200 + g}>"),)) for g in range(20))
        view, _ = trade(
            receiver("Hex Systems", 1, *givers), receiver("Nova", 2, TradeGiver("Hex Systems", picks=(TradePick("Elite", 1),)))
        ).render()

        assert within_limits(view)
        hex_card, nova = containers(view)
        # No logos left, and Hex Systems' givers share one TextDisplay, still labelled
        assert [type(c) for c in hex_card.children] == [ui.TextDisplay, ui.Separator, ui.TextDisplay]
        assert isinstance(nova.children[0], ui.TextDisplay)
        text = "\n".join(texts(view))
        assert all(f"-# From Giver {g}" in text and f"<@{200 + g}>" in text for g in range(20))

    def test_too_many_franchises_list_the_rest_and_still_ping_them(self):
        receivers = [
            receiver(f"Franchise {n}", n, TradeGiver(f"Franchise {n + 1}", players=(TradePlayer(f"<@{100 + n}>"),))) for n in range(1, 13)
        ]
        view, _ = trade(*receivers).render()

        assert view.total_children_count <= TRADE_MAX_COMPONENTS
        assert within_limits(view)
        overflow = texts(view)[-2]
        assert overflow.startswith("-# …and ")
        text = "\n".join(texts(view))
        for n in range(1, 13):
            assert f"<@{n}>" in text
            assert f"<@{100 + n}>" in text

    def test_overflow_lines_still_ping_givers_with_no_card(self):
        receivers = [
            receiver(f"Franchise {n}", n, TradeGiver("Pick Giver", picks=(TradePick("Elite", 1),), gm_id=99)) for n in range(1, 13)
        ]
        view, _ = trade(*receivers).render()

        assert within_limits(view)
        assert "**From** Pick Giver · **GM** <@99>" in texts(view)[-2]

    def test_too_much_text_cuts_picks_and_says_how_many(self):
        picks = tuple(TradePick("Elite", 1, number=n, via="IRN") for n in range(300))
        players = tuple(TradePlayer(f"<@{500 + n}>", "Quantum") for n in range(3))
        view, _ = trade(receiver("Hex Systems", 1, TradeGiver("Nova", players=players, picks=picks))).render()

        assert within_limits(view)
        body = texts(view)[-2]
        shown = body.count("**Pick**")
        assert body.endswith(f"…and {300 - shown} more picks")
        # Players carry pings, so they are never cut
        assert all(f"<@{500 + n}>" in body for n in range(3))


class TestBanners:
    def test_trade_banner_matches_the_set(self):
        trade_png = Image.open(RESOURCES / "Trade.png")
        assert trade_png.size == Image.open(RESOURCES / "Traded.png").size == (1330, 160)

    def test_card_copy_is_padded_like_the_others(self):
        card = Image.open(utils.transaction_banner(TransactionType.TRADE))
        assert utils.transaction_banner(TransactionType.TRADE).name == "Trade.png"
        assert card.size == Image.open(RESOURCES / "card" / "Traded.png").size == (1900, 160)
        # The padding is transparent
        assert card.convert("RGBA").getchannel("A").getpixel((1899, 80)) == 0

    def test_resigned_banner_differs_from_signed(self):
        resigned = Image.open(RESOURCES / "Resigned.png")
        assert resigned.size == (1330, 160)
        assert resigned.convert("RGB").tobytes() != Image.open(RESOURCES / "Signed.png").convert("RGB").tobytes()
