"""The /playoffs standings graphic: one image per playoff group, drawn with Pillow.

Laid out in 640 "units" so the text keeps a usable size when a phone shrinks the image to ~280px,
then drawn at 2x (1280px) so it stays sharp on desktop and high-density screens.
"""

import asyncio
import hashlib
import io
import threading
from collections import OrderedDict
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
from rscapi.models.tier_playoff_hunt import TierPlayoffHunt

from rsc.stats.playoffs import Race, RaceStatus, RaceTeam, chase, games_left, route, spots

FONTS = Path(__file__).parent.parent / "resources" / "fonts"
BLACK = FONTS / "Apotek_Black.otf"
BOLD = FONTS / "ApotekBold.otf"
SEMI = FONTS / "ApotekSemibold.otf"

# PNG rather than WebP: lossless keeps the small coloured text and the pill outlines crisp, where
# lossy WebP's colour subsampling smudges them, and at 150-250 KB an image is still small
GRAPHIC_FORMAT = "png"

GREEN = (35, 165, 90)
AMBER = (240, 178, 50)
GREY = (148, 155, 164)
DIM = (109, 111, 120)
WHITE = (242, 243, 245)
INK = (24, 25, 30)

U = 640  # image width in units
X = 2  # pixels per unit
PAD = 24
ROW = 64
COL_RANK = 38
PILL_W, PILL_H = 172, 38
REC_RIGHT = U - PAD - PILL_W - 16
HEAD_H, COLS_H, CUT_H = 132, 32, 30
ELIM_LINE_H = 36

# Fonts are shared by every render, and a FreeType face isn't safe to use from two threads at once
_RENDER_LOCK = threading.Lock()

Colour = tuple[int, int, int]


class Pill(StrEnum):
    SOLID_GREEN = "solid-green"
    SOLID_AMBER = "solid-amber"
    RING_GREEN = "ring-green"
    RING_AMBER = "ring-amber"
    RING_GREY = "ring-grey"
    DIM = "dim"


def pill(team: RaceTeam) -> tuple[str, Pill]:
    """The status pill's text and style: green when in, amber on the bubble, grey when chasing."""
    if team.status is RaceStatus.CLINCHED:
        return "CLINCHED", Pill.SOLID_GREEN
    if team.qualified:
        magic = team.team.playoff_magic_number
        label = f"{magic} TO CLINCH" if magic else "HOLDING"
        return label, Pill.SOLID_AMBER if team.status is RaceStatus.BUBBLE else Pill.RING_GREEN
    if team.status is RaceStatus.ELIMINATED:
        return "ELIMINATED", Pill.DIM
    # "Random draw (provisional)" doesn't fit a pill; the text summary keeps the detail
    label = chase(team).split(" (")[0].upper()
    return label, Pill.RING_AMBER if team.status is RaceStatus.BUBBLE else Pill.RING_GREY


def px(v: float) -> int:
    return round(v * X)


@lru_cache(maxsize=128)
def _font(path: Path, size_px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size_px)


def font(path: Path, size: float) -> ImageFont.FreeTypeFont:
    """A font `size` units tall."""
    return _font(path, px(size))


def fit(path: Path, text: str, size: float, minimum: float, width: float) -> ImageFont.FreeTypeFont:
    """The largest font from `size` down to `minimum` that fits `text` in `width` units."""
    f = font(path, size)
    while size > minimum and f.getlength(text) > px(width):
        size -= 0.5
        f = font(path, size)
    return f


def clip(f: ImageFont.FreeTypeFont, text: str, width: float) -> str:
    """`text`, cut short with dots if it's wider than `width` units. Apotek has no "…" glyph."""
    if f.getlength(text) <= px(width):
        return text
    while text and f.getlength(text + "...") > px(width):
        text = text[:-1]
    return text.rstrip() + "..."


def mix(a: Colour, b: Colour, t: float) -> Colour:
    return (round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t), round(a[2] + (b[2] - a[2]) * t))


def text_box(f: ImageFont.FreeTypeFont, text: str) -> tuple[float, float]:
    """Top offset and height of the inked text, in pixels."""
    _, top, _, bottom = f.getbbox(text)
    return top, bottom - top


def spaced_width(f: ImageFont.FreeTypeFont, text: str, spacing: float) -> float:
    """The width in units of letter-spaced text."""
    return (sum(f.getlength(c) for c in text) + px(spacing) * (len(text) - 1)) / X


def blend(
    img: Image.Image,
    box: tuple[int, int, int, int],
    *,
    radius: int,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None = None,
    width: int = 1,
) -> None:
    """Draw a translucent rounded rectangle over an RGBA image (ImageDraw doesn't blend on RGBA images).

    Drawn on a layer the size of the box, since compositing a full-size layer per row is slow.
    """
    x0, y0, x1, y1 = box
    layer = Image.new("RGBA", (x1 - x0 + 1, y1 - y0 + 1), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((0, 0, x1 - x0, y1 - y0), radius=radius, fill=fill, outline=outline, width=width)
    img.alpha_composite(layer, dest=(x0, y0))


def background(w: int, h: int, tier: Colour) -> Image.Image:
    """Dark gradient, a glow of the tier colour top left, and slanted streaks fading down."""
    grad = Image.linear_gradient("L").resize((w, h))
    top, bottom = Image.new("RGB", (w, h), (28, 30, 36)), Image.new("RGB", (w, h), (16, 17, 21))
    img = Image.composite(bottom, top, grad).convert("RGBA")
    # The glow is blurred at a quarter of the size, and only over the top of the image it reaches:
    # blurring the full image was the slowest step of a render, and a soft blob scales up unchanged
    glow_h = min(h, px(400))
    glow = Image.new("RGBA", (w // 4, glow_h // 4), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((px(-50), px(-60), px(95), px(47.5)), fill=(*tier, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(px(17.5))).resize((w, glow_h), Image.Resampling.BICUBIC)
    img.alpha_composite(glow)
    band = px(170)
    streaks = Image.new("RGBA", (w + px(300), band), (0, 0, 0, 0))
    sd = ImageDraw.Draw(streaks)
    for x in range(0, w + px(300), px(40)):
        sd.rectangle((x, 0, x + px(2.5), band), fill=(255, 255, 255, 13))
    streaks = streaks.transform((w, band), Image.Transform.AFFINE, (1, 0.5, 0, 0, 1, 0), resample=Image.Resampling.BICUBIC)
    fade = ImageChops.invert(Image.linear_gradient("L").rotate(90).resize((w, band)))
    streaks.putalpha(ImageChops.multiply(streaks.getchannel("A"), fade))
    img.alpha_composite(streaks)
    return img


def _elim_lines(teams: tuple[RaceTeam, ...], f: ImageFont.FreeTypeFont, width: float) -> list[list[str]]:
    """The ELIMINATED strip's entries, wrapped onto as many lines as they need."""
    lines: list[list[str]] = [[]]
    used = 0.0
    for team in teams:
        entry = f"{team.name}  {team.record}"
        w = f.getlength(entry) / X + 26
        if lines[-1] and used + w > width:
            lines.append([])
            used = 0.0
        lines[-1].append(entry)
        used += w
    return lines


def _games_caption(race: Race) -> str:
    fewest, most = race.remaining_games
    text = games_left(race).upper()
    return f"{text} EACH" if not race.complete and fewest == most > 0 else text


def render_race(race: Race, *, tier: str, season: int, colour: Colour, whole_tier: bool) -> Image.Image:
    """One playoff group's standings: header, a row per team with its status pill, the cut line and the eliminated strip."""
    shown = [*race.above, *race.below]
    folded = race.folded
    cut_drawn = bool(race.cut)

    elim_label_f = font(BOLD, 13)
    elim_label_w = spaced_width(elim_label_f, "ELIMINATED", 2.2)
    elim_f = font(BLACK, 21)
    elim_x = PAD + 4 + elim_label_w + 18
    elim_lines = _elim_lines(folded, elim_f, U - PAD - elim_x) if folded else []
    strip_h = 8 + ELIM_LINE_H * len(elim_lines)
    elim_h = strip_h + 12 if folded else 0

    h_units = HEAD_H + COLS_H + ROW * len(shown) + (CUT_H if cut_drawn else 0) + elim_h + 22
    w, h = px(U), px(h_units)
    img = background(w, h, colour)
    d = ImageDraw.Draw(img)

    def text(xy: tuple[float, float], s: str, f: ImageFont.FreeTypeFont, fill: tuple[int, ...]) -> None:
        d.text((px(xy[0]), px(xy[1])), s, font=f, fill=fill)

    def sp(xy: tuple[float, float], s: str, f: ImageFont.FreeTypeFont, fill: tuple[int, ...], spacing: float, right: bool = False) -> float:
        """Letter-spaced text; returns its width in units. With `right`, x is the right edge."""
        width = spaced_width(f, s, spacing)
        x = xy[0] - width if right else xy[0]
        x_px = px(x)
        for c in s:
            d.text((x_px, px(xy[1])), c, font=f, fill=fill)
            x_px += f.getlength(c) + px(spacing)
        return width

    def mid_y(f: ImageFont.FreeTypeFont, sample: str, top: float, height: float) -> float:
        """The y (units) that centres `sample`'s ink in a band."""
        t, hh = text_box(f, sample)
        return top + (height - hh / X) / 2 - t / X

    # Header: the label, the slanted title, the spot count and how the spots are filled
    stage = "FINAL STANDINGS" if race.complete else "PLAYOFF RACE"
    sp((PAD, 26), f"S{season} · {tier.upper()} · {stage}", font(BOLD, 17), (*mix(colour, (255, 255, 255), 0.25), 255), 3)

    big = font(BLACK, 50)
    n = str(race.cutoff)
    nw = big.getlength(n) / X
    n_top, _ = text_box(big, n)
    d.text((px(U - PAD - nw), px(52) - n_top), n, font=big, fill=(*colour, 255))
    label_f = font(BOLD, 16)
    sp((U - PAD - nw - 10, 56), "PLAYOFF", label_f, (*WHITE, 230), 2, right=True)
    sp((U - PAD - nw - 10, 76), "SPOTS", label_f, (*WHITE, 230), 2, right=True)

    title = "THE FIELD" if whole_tier else race.label.upper()
    title_room = U - PAD - nw - 10 - spaced_width(label_f, "PLAYOFF", 2) - 24 - PAD
    title_f = fit(BLACK, title, 64, 36, title_room)
    title = clip(title_f, title, title_room)
    t_top, _ = text_box(title_f, title)
    words = Image.new("RGBA", (w, px(HEAD_H)), (0, 0, 0, 0))
    wd = ImageDraw.Draw(words)
    wd.text((px(PAD + 3), px(52) - t_top + px(4)), title, font=title_f, fill=(0, 0, 0, 90))
    wd.text((px(PAD), px(52) - t_top), title, font=title_f, fill=(*WHITE, 255))
    words = words.transform(words.size, Image.Transform.AFFINE, (1, 0.18, -0.18 * px(100), 0, 1, 0), resample=Image.Resampling.BICUBIC)
    img.alpha_composite(words)

    sub = _games_caption(race)
    if race.divisions:
        sub = f"{spots(race).upper()} · {sub}"
    sp((U - PAD, 108), sub, font(SEMI, 13), (*GREY, 255), 1.6, right=True)
    d.rectangle((px(PAD), px(HEAD_H - 4), px(U - PAD), px(HEAD_H - 2)), fill=(*colour, 255))

    # Column heads
    y = HEAD_H + 10
    cf = font(BOLD, 13)
    sp((PAD, y), "#", cf, (*GREY, 255), 2)
    sp((PAD + COL_RANK + 10, y), "TEAM", cf, (*GREY, 255), 2)
    sp((REC_RIGHT, y), "W-L", cf, (*GREY, 255), 2, right=True)
    sp((U - PAD - PILL_W, y), "STATUS", cf, (*GREY, 255), 2)
    y = HEAD_H + COLS_H

    rank_f = font(BLACK, 34)
    rec_f = font(BLACK, 30)
    sub_f = font(BOLD, 12.5)
    pill_f = font(BOLD, 19)
    # The name takes the room a logo had in the mockup
    name_x = PAD + COL_RANK + 14
    name_w = REC_RIGHT - rec_f.getlength("10-10") / X - 14 - name_x

    for i, team in enumerate(shown):
        if cut_drawn and team.rank == race.cut + 1:
            mid = y + CUT_H / 2
            x = PAD + 92
            while x < U - PAD:
                d.rectangle((px(x), px(mid) - 2, px(min(x + 12, U - PAD)), px(mid) + 2), fill=(*colour, 255))
                x += 19
            cl = font(BLACK, 15)
            sp((PAD, mid_y(cl, "C", mid - 10, 20)), "CUT LINE", cl, (*colour, 255), 2.2)
            y += CUT_H

        inside = team.qualified
        if inside:
            blend(img, (px(PAD - 8), px(y + 3), px(U - PAD + 8), px(y + ROW - 3)), radius=0, fill=(255, 255, 255, 9 if i % 2 else 15))
        name_col = (*mix((40, 40, 46), WHITE, 1.0 if inside else 0.72), 255)

        r = str(team.rank)
        text((PAD + COL_RANK - rank_f.getlength(r) / X - 4, mid_y(rank_f, r, y, ROW)), r, rank_f, (*(colour if inside else GREY), 255))

        nf = fit(BLACK, team.name, 30, 20, name_w)
        name = clip(nf, team.name, name_w)
        sub_line = ""
        if team.team.division_label in race.divisions:
            sub_line = team.team.division_label.upper()
            role = route(team)
            if role:
                # "Leads Mountain" is already half said by the division name
                sub_line += " · " + {"Leads": "LEADER", "Won": "WINNER"}.get(role.split()[0], role.upper())
        if sub_line:
            n_top, _ = text_box(nf, "Hg")
            d.text((px(name_x), px(y + 11) - n_top), name, font=nf, fill=name_col)
            sp((name_x, y + ROW - 22), sub_line, sub_f, (*GREY, 255), 1.6)
        else:
            text((name_x, mid_y(nf, "Hg", y, ROW)), name, nf, name_col)
        text((REC_RIGHT - rec_f.getlength(team.record) / X, mid_y(rec_f, "10-8", y, ROW)), team.record, rec_f, name_col)

        label, style = pill(team)
        x0, y0 = U - PAD - PILL_W, y + (ROW - PILL_H) / 2
        box = (px(x0), px(y0), px(x0 + PILL_W), px(y0 + PILL_H))
        radius = px(PILL_H / 2)
        match style:
            case Pill.SOLID_GREEN:
                d.rounded_rectangle(box, radius=radius, fill=(*GREEN, 255))
                ink = (*WHITE, 255)
            case Pill.SOLID_AMBER:
                d.rounded_rectangle(box, radius=radius, fill=(*AMBER, 255))
                ink = (*INK, 255)
            case Pill.RING_GREEN:
                blend(img, box, radius=radius, outline=(*GREEN, 255), width=px(2.5), fill=(*GREEN, 30))
                ink = (126, 226, 166, 255)
            case Pill.RING_AMBER:
                blend(img, box, radius=radius, outline=(*AMBER, 255), width=px(2.5), fill=(*AMBER, 26))
                ink = (248, 210, 130, 255)
            case Pill.RING_GREY:
                d.rounded_rectangle(box, radius=radius, outline=(*DIM, 255), width=px(2.5))
                ink = (*GREY, 255)
            case Pill.DIM:
                # Like the grey ring, with the words dimmed too
                d.rounded_rectangle(box, radius=radius, outline=(*DIM, 255), width=px(2.5))
                ink = (*DIM, 255)
        pf = pill_f
        size = 19.0
        while size > 13 and spaced_width(pf, label, 1.5) > PILL_W - 20:
            size -= 0.5
            pf = font(BOLD, size)
        lw = spaced_width(pf, label, 1.5)
        sp((x0 + (PILL_W - lw) / 2, mid_y(pf, "A", y0, PILL_H)), label, pf, ink, 1.5)
        y += ROW

    if cut_drawn and not race.below:
        # Everyone below the line is eliminated, so the line sits right above the strip
        mid = y + CUT_H / 2
        x = PAD + 92
        while x < U - PAD:
            d.rectangle((px(x), px(mid) - 2, px(min(x + 12, U - PAD)), px(mid) + 2), fill=(*colour, 255))
            x += 19
        cl = font(BLACK, 15)
        sp((PAD, mid_y(cl, "C", mid - 10, 20)), "CUT LINE", cl, (*colour, 255), 2.2)
        y += CUT_H

    if folded:
        y += 8
        blend(img, (px(PAD - 8), px(y), px(U - PAD + 8), px(y + strip_h)), radius=px(9), fill=(0, 0, 0, 80))
        sp((PAD + 4, mid_y(elim_label_f, "E", y + 4, ELIM_LINE_H)), "ELIMINATED", elim_label_f, (*DIM, 255), 2.2)
        for n_line, entries in enumerate(elim_lines):
            line_top = y + 4 + n_line * ELIM_LINE_H
            x = elim_x
            for entry in entries:
                text((x, mid_y(elim_f, "Hg", line_top, ELIM_LINE_H)), entry, elim_f, (*GREY, 255))
                x += elim_f.getlength(entry) / X + 26

    return img.convert("RGB")


def encode(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_graphics(races: list[Race], *, tier: str, season: int, colour: Colour, whole_tier: bool) -> tuple[bytes, ...]:
    """Every group's graphic, encoded. CPU heavy: run it in a worker thread."""
    with _RENDER_LOCK:
        return tuple(encode(render_race(race, tier=tier, season=season, colour=colour, whole_tier=whole_tier)) for race in races)


# Caching

CacheKey = tuple[int, int, int]  # guild ID, tier ID, season number


class GraphicCache:
    """The last graphics rendered for each (guild, tier, season), reused until the standings change.

    Each entry keeps a digest of the hunt it was drawn from, so a changed hunt misses and replaces
    it. Bounded: once full, the least recently used entry goes.
    """

    def __init__(self, maxsize: int = 32) -> None:
        self.maxsize = maxsize
        self._entries: OrderedDict[CacheKey, tuple[str, tuple[bytes, ...]]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: CacheKey, digest: str) -> tuple[bytes, ...] | None:
        entry = self._entries.get(key)
        if entry is None or entry[0] != digest:
            return None
        self._entries.move_to_end(key)
        return entry[1]

    def put(self, key: CacheKey, digest: str, images: tuple[bytes, ...]) -> None:
        self._entries[key] = (digest, images)
        self._entries.move_to_end(key)
        while len(self._entries) > self.maxsize:
            self._entries.popitem(last=False)


GRAPHIC_CACHE = GraphicCache()


def hunt_digest(hunt: TierPlayoffHunt, colour: Colour) -> str:
    """Changes whenever anything drawn changes: the hunt itself, or the tier role's colour."""
    return hashlib.sha256(f"{hunt.model_dump_json()}|{colour}".encode()).hexdigest()


async def race_graphics(
    hunt: TierPlayoffHunt,
    races: list[Race],
    *,
    season: int,
    colour: Colour,
    key: CacheKey,
    whole_tier: bool,
    cache: GraphicCache = GRAPHIC_CACHE,
) -> tuple[bytes, ...]:
    """One encoded graphic per race, from the cache when the hunt hasn't changed. Renders off the event loop."""
    digest = hunt_digest(hunt, colour)
    cached = cache.get(key, digest)
    if cached is not None:
        return cached
    images = await asyncio.to_thread(render_graphics, races, tier=hunt.tier_name, season=season, colour=colour, whole_tier=whole_tier)
    cache.put(key, digest, images)
    return images
