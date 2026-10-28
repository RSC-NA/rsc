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
        "title": "Monty has been signed by Quantum (Elite)",
        "player_id": 111,
        "colour": discord.Colour.orange(),
        "banner": utils.transaction_banner(TransactionType.PICKUP),
        "created_at": CREATED,
        "franchise": "Hex Systems",
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
        section, gap, gallery, footer = _container(view).children
        assert isinstance(section, ui.Section)
        assert [t.content for t in section.children if isinstance(t, ui.TextDisplay)] == [
            "### Monty has been signed by Quantum (Elite)",
            "<@111> · Hex Systems · GM <@222>",
        ]
        assert isinstance(section.accessory, ui.Thumbnail)
        assert section.accessory.media.url == "https://cdn.example/hex.png"
        # One small blank gap above the banner
        assert isinstance(gap, ui.Separator)
        assert (gap.visible, gap.spacing) == (False, discord.SeparatorSpacing.small)
        assert isinstance(gallery, ui.MediaGallery)
        assert [item.media.url for item in gallery.items] == ["attachment://Signed.png"]
        # Today's footer wording, so a Discord ID search finds old and new posts
        assert isinstance(footer, ui.TextDisplay)
        assert footer.content == f"-# Discord ID: 111 · {discord.utils.format_dt(CREATED, 'f')}"
        assert [f.filename for f in files] == ["Signed.png"]
        assert _container(view).accent_colour == discord.Colour.orange()

    def test_bundled_logo_is_attached(self):
        badge = Path(__file__).parent.parent / "rsc" / "resources" / "FA" / "64x64" / "EliteFA_64x64.png"
        view, files = _card(logo=badge).render()
        section = _container(view).children[0]
        assert isinstance(section, ui.Section) and isinstance(section.accessory, ui.Thumbnail)
        assert section.accessory.media.url == "attachment://EliteFA_64x64.png"
        assert [f.filename for f in files] == ["EliteFA_64x64.png", "Signed.png"]

    def test_no_logo_no_section(self):
        view, _ = _card().render()
        title, facts = _container(view).children[:2]
        assert isinstance(title, ui.TextDisplay) and isinstance(facts, ui.TextDisplay)

    def test_banner_is_padded_to_seventy_percent(self):
        """Padding keeps the full-width gallery image at about the old embed's size."""
        with Image.open(utils.transaction_banner(TransactionType.PICKUP)) as image:
            assert image.size == (1900, 160)
            assert image.getchannel("A").getpixel((image.width - 1, 0)) == 0

    def test_substitution_names_both_players_on_their_own_line(self):
        view, _ = _card(player_out_id=333).render()
        assert _texts(view)[1] == "In <@111> · Out <@333>\nHex Systems · GM <@222>"

    def test_substitution_without_franchise_or_gm(self):
        view, _ = _card(player_out_id=333, franchise=None, gm_id=None).render()
        assert _texts(view)[1] == "In <@111> · Out <@333>"

    def test_retirement_without_franchise_names_only_the_player(self):
        view, _ = _card(franchise=None, gm_id=None).render()
        assert _texts(view)[1] == "<@111>"

    def test_franchise_name_is_escaped(self):
        view, _ = _card(franchise="Under_score").render()
        assert _texts(view)[1] == r"<@111> · Under\_score · GM <@222>"

    def test_each_render_gets_its_own_file(self):
        card = _card()
        assert card.render()[1][0] is not card.render()[1][0]

    def test_within_component_limits(self):
        view, _ = _card(player_out_id=333).render()
        assert view.total_children_count <= 40
