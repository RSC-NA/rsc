from datetime import UTC, datetime
from typing import Any

import discord
from discord import ui

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
        view, files = _card().render()
        title, gap1, facts, gap2, gallery, gap3, footer = _container(view).children
        # Invisible gaps between the parts, so the card isn't one stacked block
        for gap in (gap1, gap2, gap3):
            assert isinstance(gap, ui.Separator)
            assert (gap.visible, gap.spacing) == (False, discord.SeparatorSpacing.large)
        assert isinstance(title, ui.TextDisplay) and title.content == "### Monty has been signed by Quantum (Elite)"
        assert isinstance(facts, ui.TextDisplay) and facts.content == "<@111> · Hex Systems · GM <@222>"
        assert isinstance(gallery, ui.MediaGallery)
        assert [item.media.url for item in gallery.items] == ["attachment://Signed.png"]
        # Today's footer wording, so a Discord ID search finds old and new posts
        assert isinstance(footer, ui.TextDisplay)
        assert footer.content == f"-# Discord ID: 111 · {discord.utils.format_dt(CREATED, 'f')}"
        assert [f.filename for f in files] == ["Signed.png"]
        assert _container(view).accent_colour == discord.Colour.orange()

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
