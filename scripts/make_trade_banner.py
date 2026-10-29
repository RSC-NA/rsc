"""Generate rsc/resources/transactions/Trade.png, the "TRADE" banner for trade proposals.

The banners were made in Photoshop (RSC_Server_Banners.psd), and the PSD has
no "TRADE" group, only "TRADED". This re-renders the TRADED group's text the
way Photoshop draws it: Apotek Black, a faded ghost copy with a 1px white
outline behind, and the solid white word with a soft teal drop shadow on top.

"TRADE" and "TRADED" share a font, size and position, so T-R-A-D-E land on the
same pixels. Traded.png's original pixels are kept everywhere the two words
render the same; only the area the final "D" touched is repainted, blended in
over a soft edge.

    uv run python scripts/make_trade_banner.py

Then run scripts/make_card_banners.py for the padded copy in card/.
"""

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from psd_tools import PSDImage
from psd_tools.api.layers import Group

DEFAULT_PSD = Path("/mnt/d/rsc/rsc_eu/graphics/RSC_Server_Banners.psd")
DEFAULT_FONT = Path.home() / "fonts" / "Apotek_Black.otf"

TRANSACTIONS = Path(__file__).resolve().parent.parent / "rsc" / "resources" / "transactions"
REFERENCE = TRANSACTIONS / "Traded.png"
OUT = TRANSACTIONS / "Trade.png"

# The PSD group holding the transaction banners, and the one to borrow
TRANSACTIONS_GROUP = ("Banners", "Transactions")
SOURCE_GROUP = "TRADED"

WIDTH, HEIGHT = 1330, 160
# Glyphs are drawn this many times larger, then box-downsampled, for smooth edges
SUPERSAMPLE = 4

# From the TRADED type layers: point size x the layer's transform scale, and the
# baseline origin. The y origins are nudged to line up with Traded.png's pixels.
GHOST_SIZE = 47.0 * 3.618492411592282
GHOST_ORIGIN = (-22.796075885740038, 177.43648985031498 - 0.5)
GHOST_ALPHA = 64 / 255  # layer opacity
MAIN_SIZE = 95.05982 * 1.1361265953534252
MAIN_ORIGIN = (116.14535670777508, 114.64515284075779 + 0.25)

WHITE = (255, 255, 255)
SHADOW = (10, 70, 85)
SHADOW_ALPHA = 0.44
# Gaussian blur radius matching the PSD's drop shadow (size 7, distance 0)
SHADOW_SIGMA = 3.0


def find_group(root: Group | PSDImage, path: tuple[str, ...]) -> Group:
    """The nested group at path, by layer name."""
    node = root
    for name in path:
        match = next((layer for layer in node if layer.name == name), None)
        if not isinstance(match, Group):
            raise SystemExit(f"No group {'/'.join(path)!r} in the PSD")
        node = match
    if not isinstance(node, Group):
        raise SystemExit("Empty group path")
    return node


def background(psd_path: Path) -> np.ndarray:
    """The TRADED banner without its text: the BG group plus the group's bars."""
    psd = PSDImage.open(psd_path)
    transactions = find_group(psd, TRANSACTIONS_GROUP)
    for group in transactions:
        group.visible = group.name == SOURCE_GROUP
    for layer in find_group(transactions, (SOURCE_GROUP,)):
        if layer.kind == "type":
            layer.visible = False
        elif layer.kind == "shape":
            layer.visible = True
    composite = psd.composite(force=True)
    if composite is None:
        raise SystemExit("The PSD composited to nothing")
    return np.asarray(composite.convert("RGB"))


def glyph_mask(font_path: Path, text: str, size: float, origin: tuple[float, float], dilate: int = 0) -> np.ndarray:
    """Text coverage, 0 to 1 per pixel, at the banner's size.

    origin is the left end of the baseline. dilate grows the glyphs by that many
    pixels, for drawing an outline.
    """
    font = ImageFont.truetype(str(font_path), size * SUPERSAMPLE)
    # Room for glyphs that start left of the banner (the ghost text does)
    pad = 64 * SUPERSAMPLE
    big = Image.new("L", (WIDTH * SUPERSAMPLE + 2 * pad, HEIGHT * SUPERSAMPLE + 2 * pad), 0)
    xy = (origin[0] * SUPERSAMPLE + pad, origin[1] * SUPERSAMPLE + pad)
    ImageDraw.Draw(big).text(xy, text, font=font, fill=255, anchor="ls")
    if dilate:
        big = big.filter(ImageFilter.MaxFilter(2 * dilate * SUPERSAMPLE + 1))
    big = big.crop((pad, pad, pad + WIDTH * SUPERSAMPLE, pad + HEIGHT * SUPERSAMPLE))
    return np.asarray(big.resize((WIDTH, HEIGHT), Image.Resampling.BOX)).astype(float) / 255


def over(dst: np.ndarray, colour: tuple[int, int, int], alpha: np.ndarray) -> np.ndarray:
    """Paint a flat colour over dst with per-pixel alpha."""
    a = alpha[..., None]
    return dst * (1 - a) + np.asarray(colour, float) * a


def render(bg: np.ndarray, text: str, font_path: Path) -> np.ndarray:
    """The banner with text drawn over bg, layered as in the PSD."""
    out = bg.astype(float)

    # Ghost text: no fill, just a faded 1px outline outside the glyphs
    ghost = glyph_mask(font_path, text, GHOST_SIZE, GHOST_ORIGIN)
    grown = glyph_mask(font_path, text, GHOST_SIZE, GHOST_ORIGIN, dilate=1)
    out = over(out, WHITE, np.clip(grown - ghost, 0, 1) * GHOST_ALPHA)

    # Main text with its drop shadow underneath
    main = glyph_mask(font_path, text, MAIN_SIZE, MAIN_ORIGIN)
    blurred = Image.fromarray((main * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(SHADOW_SIGMA))
    out = over(out, SHADOW, np.asarray(blurred).astype(float) / 255 * SHADOW_ALPHA)
    out = over(out, WHITE, main)
    return np.clip(out.round(), 0, 255).astype(np.uint8)


def influence(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Where two renders differ, grown by 2px and feathered, as a 0 to 1 mask."""
    changed = (np.abs(a.astype(int) - b.astype(int)).max(axis=2) > 1).astype(np.uint8) * 255
    mask = Image.fromarray(changed).filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(1))
    return np.asarray(mask).astype(float)[..., None] / 255


def blend(original: np.ndarray, new: np.ndarray, mask: np.ndarray) -> Image.Image:
    """original, with new showing through where mask is set."""
    out = original.astype(float) * (1 - mask) + new.astype(float) * mask
    return Image.fromarray(np.clip(out.round(), 0, 255).astype(np.uint8))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--psd", type=Path, default=DEFAULT_PSD, help=f"source PSD (default: {DEFAULT_PSD})")
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT, help=f"Apotek Black (default: {DEFAULT_FONT})")
    args = parser.parse_args()

    bg = background(args.psd)
    traded = np.asarray(Image.open(REFERENCE).convert("RGB"))
    old = render(bg, "TRADED", args.font)
    new = render(bg, "TRADE", args.font)
    blend(traded, new, influence(old, new)).save(OUT, optimize=True)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
