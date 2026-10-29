import asyncio
import functools
import io
import itertools
import logging
import math
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import discord
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

log = logging.getLogger("red.rsc.utils.images")

ROOT_PATH = Path(__file__).parent.parent
RSC_FONT = ROOT_PATH / "resources/fonts/Apotek_Black.otf"
RSC_FONT_BOLD = ROOT_PATH / "resources/fonts/ApotekBold.otf"

FONT_12 = ImageFont.truetype(str(RSC_FONT), 12)
FONT_14 = ImageFont.truetype(str(RSC_FONT), 14)
FONT_16 = ImageFont.truetype(str(RSC_FONT), 16)
FONT_18 = ImageFont.truetype(str(RSC_FONT), 18)
FONT_20 = ImageFont.truetype(str(RSC_FONT), 20)
FONT_22 = ImageFont.truetype(str(RSC_FONT), 22)
FONT_32 = ImageFont.truetype(str(RSC_FONT), 32)


def drawProgressBar(  # noqa: N802
    d: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    progress: float,
    progress_bounds: tuple[int, int] | None = None,
    bg: tuple[int, int, int] = (17, 17, 17),
    fg: tuple[int, int, int] = (0, 102, 153),
) -> ImageDraw.ImageDraw:
    # draw background
    d.ellipse((x + w, y, x + h + w, y + h), fill=bg)
    d.ellipse((x, y, x + h, y + h), fill=bg)
    d.rectangle((x + (h / 2), y, x + w + (h / 2), y + h), fill=bg)

    # draw progress bar

    pw = w * progress
    d.ellipse((x + pw, y, x + h + pw, y + h), fill=fg)
    d.ellipse((x, y, x + h, y + h), fill=fg)
    d.rectangle((x + (h / 2), y, x + pw + (h / 2), y + h), fill=fg)

    # draw progress
    if progress_bounds:
        message = f"{progress_bounds[0]} / {progress_bounds[1]} ({int(progress * 100)}%)"
        d.text(((w / 2) + (x * 2), (h / 2) + y), message, font=FONT_16, anchor="mm")
    else:
        message = f"{progress * 100}%"
        d.text(((w / 2) + (x * 2), (h / 2) + y), message, font=FONT_16, anchor="mm")

    return d


def getProgressBar(  # noqa: N802
    x: int,
    y: int,
    w: int,
    h: int,
    progress: float = 0.0,
    progress_bounds: tuple[int, int] | None = None,
    bg: tuple[int, int, int] = (17, 17, 17),
    fg: tuple[int, int, int] = (0, 102, 153),
) -> discord.File:
    progress_bar = Image.new("RGBA", (275, 50), (255, 255, 255))
    progress_bar.putalpha(1)
    base_image = ImageDraw.Draw(progress_bar)

    drawProgressBar(
        base_image,
        x=x,
        y=y,
        w=w,
        h=h,
        progress=progress,
        progress_bounds=progress_bounds,
        bg=bg,
        fg=fg,
    )

    with io.BytesIO() as buf:
        progress_bar.save(buf, format="PNG")
        # byte_arr = buf.getvalue()
        buf.seek(0)
        dFile = discord.File(filename="progress.jpeg", fp=buf)

    return dFile


# Sign-up success banner

SIGNUP_BANNER_SIZE = (1200, 600)
SIGNUP_BANNER_FILENAME = "signup.webp"


@dataclass(frozen=True)
class BannerPalette:
    dark: tuple[int, int, int]
    mid: tuple[int, int, int]
    bright: tuple[int, int, int]
    name: tuple[int, int, int]
    glow: tuple[int, int, int]


SIGNUP_PALETTE = BannerPalette(dark=(18, 5, 26), mid=(58, 11, 44), bright=(216, 27, 96), name=(255, 194, 214), glow=(255, 92, 147))
PERMFA_PALETTE = BannerPalette(dark=(20, 13, 2), mid=(74, 49, 8), bright=(224, 162, 31), name=(255, 225, 163), glow=(255, 196, 64))


def _gradient_lut(stops: list[tuple[float, tuple[int, int, int]]]) -> list[list[int]]:
    """Per channel lookup tables mapping 0-255 onto a list of colour stops"""
    luts: list[list[int]] = [[], [], []]
    for i in range(256):
        t = i / 255
        for (t0, c0), (t1, c1) in itertools.pairwise(stops):
            if t0 <= t <= t1:
                f = (t - t0) / (t1 - t0) if t1 > t0 else 0
                for ch in range(3):
                    luts[ch].append(round(c0[ch] + (c1[ch] - c0[ch]) * f))
                break
    return luts


def _diagonal_gradient(size: tuple[int, int], angle: float, stops: list[tuple[float, tuple[int, int, int]]]) -> Image.Image:
    """CSS style linear gradient. `angle` turns the top-to-bottom gradient counterclockwise."""
    w, h = size
    d = int((w**2 + h**2) ** 0.5) + 2
    ramp = Image.linear_gradient("L").resize((d, d)).rotate(angle, resample=Image.Resampling.BICUBIC)
    ramp = ramp.crop(((d - w) // 2, (d - h) // 2, (d - w) // 2 + w, (d - h) // 2 + h))
    r, g, b = _gradient_lut(stops)
    return Image.merge("RGB", (ramp.point(r), ramp.point(g), ramp.point(b)))


def _horizontal_fade(size: tuple[int, int], start: float, end: float, invert: bool = False) -> Image.Image:
    """L mask that fades from opaque at `start` to clear at `end` (fractions of the width)"""
    w, h = size
    row = []
    for x in range(w):
        t = min(max((x / w - start) / (end - start), 0.0), 1.0)
        row.append(round(255 * (t if invert else 1 - t)))
    line = Image.new("L", (w, 1))
    line.putdata(row)
    return line.resize((w, h))


def _hexagon(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    """Pointy-top hexagon with circumradius `r`"""
    return [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in range(-90, 270, 60)]


def _slant(layer: Image.Image, shear: float = 0.2) -> Image.Image:
    """Lean a layer to the right, keeping its bottom edge in place"""
    w, h = layer.size
    return layer.transform((w, h), Image.Transform.AFFINE, (1, shear, -shear * h, 0, 1, 0), resample=Image.Resampling.BICUBIC)


def _spaced_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: int | tuple[int, ...],
    spacing: float,
) -> float:
    """Draw letter-spaced text. Returns the width drawn."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + spacing
    return x - xy[0] - spacing


def _fit_font(path: Path, text: str, start: int, max_width: float, minimum: int = 28) -> ImageFont.FreeTypeFont:
    size = start
    font = ImageFont.truetype(str(path), size)
    while size > minimum and font.getlength(text) > max_width:
        size -= 2
        font = ImageFont.truetype(str(path), size)
    return font


def _signup_banner_base(kicker: str, headline: str, name: str, chips: list[str], palette: BannerPalette) -> Image.Image:
    w, h = SIGNUP_BANNER_SIZE
    img = _diagonal_gradient((w, h), 65, [(0.0, palette.dark), (0.48, palette.mid), (1.0, palette.bright)]).convert("RGBA")

    # Glow behind the badge
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-60, 20, 460, 580), fill=(*palette.glow, 105))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(90)))

    # Hex grid, fading out to the right
    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    r = 48
    dx, dy = r * math.sqrt(3), r * 1.5
    for row in range(-1, int(h / dy) + 2):
        for col in range(-1, int(w / dx) + 2):
            cx = col * dx + (dx / 2 if row % 2 else 0)
            gd.polygon(_hexagon(cx, row * dy, r), outline=(255, 255, 255, 20), width=2)
    grid.putalpha(ImageChops.multiply(grid.getchannel("A"), _horizontal_fade((w, h), 0.1, 0.75)))
    img.alpha_composite(grid)

    # Speed streaks on the right
    streaks = Image.new("RGBA", (w + 400, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(streaks)
    for x in range(0, w + 400, 108):
        sd.rectangle((x + 60, 0, x + 64, h), fill=(255, 255, 255, 18))
        sd.rectangle((x + 104, 0, x + 106, h), fill=(255, 255, 255, 30))
    streaks = streaks.transform((w, h), Image.Transform.AFFINE, (1, 0.45, 0, 0, 1, 0), resample=Image.Resampling.BICUBIC)
    streaks.putalpha(ImageChops.multiply(streaks.getchannel("A"), _horizontal_fade((w, h), 0.3, 0.85, invert=True)))
    img.alpha_composite(streaks)

    # Outlined RSC watermark
    mark = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(mark).text(
        (w + 30, h + 120),
        "RSC",
        font=ImageFont.truetype(str(RSC_FONT), 470),
        fill=(255, 255, 255, 0),
        stroke_width=4,
        stroke_fill=(255, 255, 255, 34),
        anchor="rs",
    )
    img.alpha_composite(_slant(mark, 0.18))

    # Hexagon badge with a check mark
    cx, cy, br = 198, h / 2, 146
    halo = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(halo).polygon(_hexagon(cx, cy, br + 10), fill=(*palette.glow, 170))
    img.alpha_composite(halo.filter(ImageFilter.GaussianBlur(28)))
    rim_fill = _diagonal_gradient((w, h), 20, [(0.0, (255, 255, 255)), (0.45, palette.name), (1.0, palette.bright)]).convert("RGBA")
    rim_mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(rim_mask).polygon(_hexagon(cx, cy, br), fill=255)
    img.paste(rim_fill, (0, 0), rim_mask)
    bd = ImageDraw.Draw(img)
    bd.polygon(_hexagon(cx, cy, br - 15), fill=(*palette.dark, 255))
    bd.line([(cx - 50, cy + 2), (cx - 14, cy + 40), (cx + 56, cy - 46)], fill=(*palette.name, 255), width=22, joint="curve")

    # Text: kicker, headline, name, chips. Drawn on their own layers so the alpha blends.
    left, right = 384, w - 60
    kicker_font = ImageFont.truetype(str(RSC_FONT_BOLD), 32)
    headline_font = _fit_font(RSC_FONT, headline, 112, right - left - 70)
    name_font = _fit_font(RSC_FONT, name, 70 if len(name) <= 12 else 58 if len(name) <= 18 else 46, right - left - 70)
    chip_font = ImageFont.truetype(str(RSC_FONT_BOLD), 26)

    def box(font: ImageFont.FreeTypeFont, text: str) -> tuple[int, int]:
        """Top offset and height of the inked text"""
        _, top, _, bottom = font.getbbox(text)
        return round(top), round(bottom - top)

    kicker_top, kicker_h = box(kicker_font, kicker)
    headline_top, headline_h = box(headline_font, headline)
    name_top, name_h = box(name_font, name) if name else (0, 0)
    chip_h = 48
    # With nothing left of the name to draw, the chips move up under the headline
    gaps = (22, 18, 26) if name else (22, 0, 26)
    y = cy - (kicker_h + headline_h + name_h + chip_h + sum(gaps)) / 2

    flat = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fd = ImageDraw.Draw(flat)
    _spaced_text(fd, (left, y - kicker_top), kicker, kicker_font, (255, 255, 255, 215), 8)
    y += kicker_h + gaps[0]

    words = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    wd = ImageDraw.Draw(words)
    wd.text((left + 4, y - headline_top + 6), headline, font=headline_font, fill=(0, 0, 0, 80))
    wd.text((left, y - headline_top), headline, font=headline_font, fill=(255, 255, 255, 255))
    y += headline_h + gaps[1]
    if name:
        wd.text((left, y - name_top), name, font=name_font, fill=(*palette.name, 255))
    y += name_h + gaps[2]

    x = left
    chip_top, chip_text_h = box(chip_font, "A")
    measure = ImageDraw.Draw(Image.new("L", (1, 1)))
    for chip in chips:
        text_w = _spaced_text(measure, (0, 0), chip, chip_font, 0, 3)
        rect = (x, y, x + text_w + 36, y + chip_h)
        fd.rounded_rectangle(rect, radius=chip_h // 2, fill=(0, 0, 0, 50), outline=(255, 255, 255, 125), width=3)
        _spaced_text(fd, (x + 18, y + (chip_h - chip_text_h) / 2 - chip_top), chip, chip_font, (255, 255, 255, 255), 3)
        x = rect[2] + 12

    img.alpha_composite(_slant(words, 0.2))
    img.alpha_composite(flat)

    return img


# Apotek covers Latin letters, with accents, but no emoji, Greek, Cyrillic or CJK. A character it lacks
# renders as the font's placeholder glyph, so compare a character's ink with that.
_GLYPH_PROBE = ImageFont.truetype(str(RSC_FONT), 40)
# Invisible format and combining marks, e.g. the joiners and variation selectors inside emoji
_DROP_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Mn", "Me"})


def _ink(char: str) -> bytes:
    canvas = Image.new("L", (96, 96))
    ImageDraw.Draw(canvas).text((8, 8), char, font=_GLYPH_PROBE, fill=255)
    return canvas.tobytes()


_PLACEHOLDER_INK = _ink("\ue000")


@functools.lru_cache(maxsize=4096)
def _has_glyph(char: str) -> bool:
    if char.isspace():
        return True
    if unicodedata.category(char) in _DROP_CATEGORIES:
        return False
    return _ink(char) != _PLACEHOLDER_INK


def drawable(text: str) -> str:
    """`text` with every character the banner font can't draw (emoji, other scripts) removed, spaces tidied."""
    # Composed first, so an accent typed as a separate mark becomes one letter Apotek has
    text = unicodedata.normalize("NFC", text)
    return " ".join("".join(c for c in text if _has_glyph(c)).split())


def render_signup_banner(*, kicker: str, headline: str, name: str, chips: list[str], permfa: bool) -> bytes:
    """Render the sign-up success banner as an animated WebP with a light sweeping across it"""
    palette = PERMFA_PALETTE if permfa else SIGNUP_PALETTE
    base = _signup_banner_base(kicker, headline, drawable(name.upper()), [c.upper() for c in chips], palette)
    w, h = base.size

    # A soft white band, slanted, cropped at a different offset for each frame
    band_w = 300
    band = Image.new("L", (band_w, 1))
    band.putdata([round(60 * (1 - abs(x - band_w / 2) / (band_w / 2))) for x in range(band_w)])
    band = band.resize((band_w, h * 2))
    sweep = Image.new("L", (w * 3, h * 2), 0)
    sweep.paste(band, (w + w // 2 - band_w // 2, 0))
    sweep = sweep.transform(sweep.size, Image.Transform.AFFINE, (1, 0.27, -0.27 * h, 0, 1, 0)).crop((0, h // 2, w * 3, h // 2 + h))
    white = Image.new("RGBA", (w, h), (255, 255, 255, 255))

    frames: list[Image.Image] = []
    steps = 14
    for i in range(steps):
        offset = round((w * 2.2) * i / (steps - 1) - w * 0.1)
        mask = sweep.crop((w * 2 - offset, 0, w * 3 - offset, h))
        frames.append(Image.composite(white, base, mask).convert("RGB"))
    frames.append(base.convert("RGB"))
    durations = [70] * steps + [2600]

    buf = io.BytesIO()
    frames[0].save(buf, format="WEBP", save_all=True, append_images=frames[1:], duration=durations, loop=0, quality=82, method=4)
    return buf.getvalue()


async def signup_banner_file(*, kicker: str, headline: str, name: str, chips: list[str], permfa: bool) -> discord.File:
    data = await asyncio.to_thread(render_signup_banner, kicker=kicker, headline=headline, name=name, chips=chips, permfa=permfa)
    return discord.File(io.BytesIO(data), filename=SIGNUP_BANNER_FILENAME)
