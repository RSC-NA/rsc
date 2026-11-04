import io
from dataclasses import replace

import pytest
from PIL import Image, WebPImagePlugin

from rsc.utils import champions_banner
from rsc.utils.champions_banner import RSC_LOGO, ChampionsBanner, champions_banner_bytes, render_champions_banner

FINAL = ChampionsBanner(
    season=23,
    tier="Master",
    tier_colour=(155, 89, 182),
    winner="Voltage Vanguard",
    loser="Quantum",
    winner_wins=4,
    loser_wins=0,
    logo=None,
)


def _png(size: tuple[int, int], mode: str, colour: tuple[int, ...]) -> bytes:
    with io.BytesIO() as buf:
        Image.new(mode, size, colour).save(buf, format="PNG")
        return buf.getvalue()


@pytest.fixture
def short_loop(monkeypatch):
    monkeypatch.setattr(champions_banner, "FRAMES", 2)


def test_renders_the_full_loop_as_an_animated_webp():
    data = render_champions_banner(FINAL)

    im = Image.open(io.BytesIO(data))
    assert isinstance(im, WebPImagePlugin.WebPImageFile)
    assert im.size == (1200, 600)
    assert im.is_animated
    assert im.n_frames == champions_banner.FRAMES == 40


@pytest.mark.usefixtures("short_loop")
class TestInputs:
    @pytest.mark.parametrize(
        "winner",
        [
            "Voltage Vanguard",
            "\N{TROPHY} Rocket Rats \N{TROPHY}",
            "\N{FIRE}\N{FIRE}",
        ],
    )
    def test_renders_any_winner_name(self, winner):
        data = render_champions_banner(replace(FINAL, winner=winner, loser=f"{winner} B"))

        assert Image.open(io.BytesIO(data)).size == (1200, 600)

    def test_renders_without_a_season(self):
        data = render_champions_banner(replace(FINAL, season=None))

        assert data != render_champions_banner(FINAL)
        assert Image.open(io.BytesIO(data)).size == (1200, 600)

    @pytest.mark.parametrize("logo", [None, b"not an image", _png((64, 64), "RGB", (200, 30, 30))[:40]])
    def test_missing_or_broken_logo_falls_back_to_the_rsc_logo(self, logo):
        with_rsc_logo = render_champions_banner(replace(FINAL, logo=RSC_LOGO.read_bytes()))

        assert render_champions_banner(replace(FINAL, logo=logo)) == with_rsc_logo

    @pytest.mark.parametrize(
        "logo",
        [_png((512, 512), "RGB", (200, 30, 30)), _png((90, 120), "RGBA", (30, 200, 30, 128)), _png((40, 40), "L", (90,))],
    )
    def test_draws_the_winners_logo(self, logo):
        data = render_champions_banner(replace(FINAL, logo=logo))

        assert data != render_champions_banner(FINAL)

    @pytest.mark.parametrize(("size", "inked"), [((600, 200), (196, 65)), ((100, 300), (65, 196))])
    def test_logo_keeps_its_proportions(self, size, inked):
        square = champions_banner._fit_logo(Image.new("RGBA", size, (200, 30, 30, 255)))
        bbox = square.getchannel("A").getbbox()

        assert square.size == (196, 196)
        assert bbox is not None
        assert (bbox[2] - bbox[0], bbox[3] - bbox[1]) == inked

    def test_same_final_renders_the_same_bytes(self):
        assert render_champions_banner(FINAL) == render_champions_banner(FINAL)

    async def test_async_render_matches(self):
        assert await champions_banner_bytes(FINAL) == render_champions_banner(FINAL)
