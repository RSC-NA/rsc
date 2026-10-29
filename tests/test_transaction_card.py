from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import discord
from discord import ui
from PIL import Image

from rsc.enums import TransactionType
from rsc.transactions.views import TransactionCard
from rsc.utils import utils

CREATED = datetime(2026, 10, 28, 22, 47, tzinfo=UTC)


def _card(**overrides) -> TransactionCard:
    fields: dict[str, Any] = {
        "move": "SIGNED · Elite",
        "name": "Monty",
        "summary": "joins **Quantum** · Hex Systems",
        "player_id": 111,
        "colour": discord.Colour.orange(),
        "banner": utils.transaction_banner(TransactionType.PICKUP),
        "created_at": CREATED,
        "gm_id": 222,
    }
    fields.update(overrides)
    return TransactionCard(**fields)


def _container(view: ui.LayoutView) -> ui.Container:
    (container,) = view.children
    assert isinstance(container, ui.Container)
    return container


def _texts(view: ui.LayoutView) -> list[str]:
    return [c.content for c in _container(view).children if isinstance(c, ui.TextDisplay)]


class TestRender:
    def test_layout(self):
        view, files = _card(logo="https://cdn.example/hex.png").render()
        section, line, people, gap, gallery, footer = _container(view).children
        # Built like the match result: label, name headline, then where they went, beside the logo
        assert isinstance(section, ui.Section)
        assert [t.content for t in section.children if isinstance(t, ui.TextDisplay)] == [
            "-# SIGNED · Elite",
            "## Monty",
            "joins **Quantum** · Hex Systems",
        ]
        assert isinstance(section.accessory, ui.Thumbnail)
        assert section.accessory.media.url == "https://cdn.example/hex.png"
        assert isinstance(line, ui.Separator) and line.visible
        assert isinstance(people, ui.TextDisplay) and people.content == "**Player** <@111> · **GM** <@222>"
        assert isinstance(gap, ui.Separator) and not gap.visible
        assert isinstance(gallery, ui.MediaGallery)
        assert [item.media.url for item in gallery.items] == ["attachment://Signed.png"]
        # Today's footer wording, so a Discord ID search finds old and new posts
        assert isinstance(footer, ui.TextDisplay)
        assert footer.content == f"-# Discord ID: 111 · {discord.utils.format_dt(CREATED, 'f')}"
        assert [f.filename for f in files] == ["Signed.png"]
        assert _container(view).accent_colour == discord.Colour.orange()

    def test_substitution_names_both_players_then_the_gm(self):
        view, _ = _card(player_out_id=333).render()
        assert _texts(view)[3] == "**In** <@111> · **Out** <@333>\n**GM** <@222>"

    def test_substitution_without_gm(self):
        view, _ = _card(player_out_id=333, gm_id=None).render()
        assert _texts(view)[3] == "**In** <@111> · **Out** <@333>"

    def test_no_gm_names_only_the_player(self):
        view, _ = _card(gm_id=None).render()
        assert _texts(view)[3] == "**Player** <@111>"

    def test_bundled_logo_is_attached(self):
        badge = Path(__file__).parent.parent / "rsc" / "resources" / "FA" / "64x64" / "EliteFA_64x64.png"
        view, files = _card(logo=badge).render()
        section = _container(view).children[0]
        assert isinstance(section, ui.Section) and isinstance(section.accessory, ui.Thumbnail)
        assert section.accessory.media.url == "attachment://EliteFA_64x64.png"
        assert [f.filename for f in files] == ["EliteFA_64x64.png", "Signed.png"]

    def test_no_logo_no_section(self):
        view, _ = _card().render()
        assert _texts(view)[:3] == ["-# SIGNED · Elite", "## Monty", "joins **Quantum** · Hex Systems"]

    def test_banner_is_padded_to_seventy_percent(self):
        """Padding keeps the full-width gallery image at about the old embed's size."""
        with Image.open(utils.transaction_banner(TransactionType.PICKUP)) as image:
            assert image.size == (1900, 160)
            assert image.getchannel("A").getpixel((image.width - 1, 0)) == 0

    def test_each_render_gets_its_own_file(self):
        card = _card()
        assert card.render()[1][0] is not card.render()[1][0]

    def test_within_component_limits(self):
        view, _ = _card(player_out_id=333, logo="https://cdn.example/hex.png").render()
        assert view.total_children_count <= 40


class TestContractExpired:
    def test_sub_leaves_and_the_starter_comes_back(self):
        view, _ = _card(move="CONTRACT EXPIRED · Elite", summary="leaves **Quantum** · Hex Systems", starter_back_id=444).render()
        assert _texts(view)[:3] == ["-# CONTRACT EXPIRED · Elite", "## Monty", "leaves **Quantum** · Hex Systems"]
        assert _texts(view)[3] == "**Out** <@111> · **In** <@444>\n**GM** <@222>"

    def test_banner_is_padded_like_the_others(self):
        with Image.open(utils.CONTRACT_EXPIRED_BANNER) as image:
            assert image.size == (1900, 160)
