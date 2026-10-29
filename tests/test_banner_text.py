import pytest

from rsc.utils.images import drawable, render_signup_banner


class TestDrawable:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("RF | nickm \N{TROPHY}", "RF | nickm"),
            # Accented Latin is in the font, typed precomposed or as letter plus combining mark
            ("J\N{LATIN SMALL LETTER O WITH DIAERESIS}hn", "J\N{LATIN SMALL LETTER O WITH DIAERESIS}hn"),
            ("Jo\N{COMBINING DIAERESIS}hn", "J\N{LATIN SMALL LETTER O WITH DIAERESIS}hn"),
            ("\N{LATIN CAPITAL LETTER L WITH STROKE}ukasz_99", "\N{LATIN CAPITAL LETTER L WITH STROKE}ukasz_99"),
            # Joined emoji leave no invisible joiners or variation selectors behind
            ("\N{MAN}\N{ZERO WIDTH JOINER}\N{WOMAN}\N{ZERO WIDTH JOINER}\N{GIRL} Fam\N{VARIATION SELECTOR-16}", "Fam"),
            # Scripts the font doesn't have are dropped, and the spaces tidied
            ("\N{CJK UNIFIED IDEOGRAPH-6771}\N{CJK UNIFIED IDEOGRAPH-4EAC} Tokyo", "Tokyo"),
            ("\N{CYRILLIC CAPITAL LETTER DE}\N{CYRILLIC SMALL LETTER EM}", ""),
        ],
    )
    def test_keeps_only_what_the_font_can_draw(self, name, expected):
        assert drawable(name) == expected


class TestBannerWithoutName:
    def test_renders_when_nothing_of_the_name_is_drawable(self):
        data = render_signup_banner(
            kicker="S24 SIGN-UP", headline="YOU'RE IN", name="\N{CYRILLIC CAPITAL LETTER DE}", chips=["New player"], permfa=False
        )
        assert data[:4] == b"RIFF"
