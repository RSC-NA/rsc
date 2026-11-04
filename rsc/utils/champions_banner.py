import asyncio
import io
import math
import random
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from rsc.utils.images import ROOT_PATH, RSC_FONT, RSC_FONT_BOLD, _diagonal_gradient, _fit_font, _slant, _spaced_text, drawable

CHAMPIONS_BANNER_FILENAME = "champions.webp"

RSC_FONT_SEMIBOLD = ROOT_PATH / "resources/fonts/ApotekSemibold.otf"
RSC_LOGO = ROOT_PATH / "resources/rsc_logo.png"

W, H = 1200, 600
FRAMES = 40
FRAME_MS = 70
LOGO_SIZE = 196
LOGO_CENTRE = (W // 2, 128)
GOLD = (241, 196, 15)
GOLD_LIGHT = (255, 226, 120)
GOLD_DEEP = (196, 138, 8)

Colour = tuple[int, int, int]


@dataclass(frozen=True)
class ChampionsBanner:
    season: int | None
    tier: str
    tier_colour: Colour
    winner: str
    loser: str
    winner_wins: int
    loser_wins: int
    logo: bytes | None


@dataclass(frozen=True)
class Depth:
    count: int
    size: tuple[float, float]
    wraps: int
    ribbons: bool
    alpha: int
    scale: float
    blur: float


FAR = Depth(count=60, size=(7, 12), wraps=1, ribbons=True, alpha=150, scale=0.5, blur=1.2)
MID = Depth(count=84, size=(12, 22), wraps=1, ribbons=True, alpha=245, scale=2, blur=0)
NEAR = Depth(count=9, size=(30, 46), wraps=2, ribbons=False, alpha=200, scale=0.5, blur=3)
DEPTHS = (FAR, MID, NEAR)


def _mix(a: Colour, b: Colour, t: float) -> Colour:
    return (round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t), round(a[2] + (b[2] - a[2]) * t))


@dataclass(frozen=True)
class Piece:
    ribbon: bool
    x: float
    y: float
    length: float
    width: float
    colour: Colour
    angle: float
    spins: int
    flip: float
    flips: int
    sway: float
    sway_phase: float
    wraps: int

    def outline(self, t: float, scale: float) -> tuple[list[tuple[float, float]], Colour]:
        span = H + 120
        y = (self.y + self.wraps * span * t) % span - 60
        x = self.x + self.sway * math.sin(2 * math.pi * t + self.sway_phase)
        theta = self.angle + 2 * math.pi * self.spins * t
        face = math.cos(self.flip + 2 * math.pi * self.flips * t)
        shade = 0.55 + 0.45 * abs(face)
        colour = (round(self.colour[0] * shade), round(self.colour[1] * shade), round(self.colour[2] * shade))
        c, s = math.cos(theta), math.sin(theta)
        if self.ribbon:
            pts_top, pts_bottom = [], []
            steps = 12
            roll = self.flip + 2 * math.pi * self.flips * t
            for i in range(steps + 1):
                f = i / steps
                u = (f - 0.5) * self.length
                v = 0.16 * self.length * math.sin(f * 1.4 * math.pi + roll)
                half = max(self.width * abs(math.cos(f * 2.2 + roll)), 1.0) / 2
                pts_top.append((u, v - half))
                pts_bottom.append((u, v + half))
            local = pts_top + pts_bottom[::-1]
        else:
            hl, hw = self.length / 2, max(self.width * abs(face), 1.2) / 2
            local = [(-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw)]
        return [((x + u * c - v * s) * scale, (y + u * s + v * c) * scale) for u, v in local], colour


def _make_pieces(banner: ChampionsBanner, seed: str) -> dict[Depth, list[Piece]]:
    rng = random.Random(seed)  # noqa: S311
    tier = banner.tier_colour
    palette = [GOLD] * 4 + [GOLD_LIGHT] * 3 + [GOLD_DEEP] * 2 + [tier] * 3 + [_mix(tier, (255, 255, 255), 0.45)] * 2 + [(255, 248, 230)]
    pieces: dict[Depth, list[Piece]] = {}
    for depth in DEPTHS:
        pieces[depth] = []
        for _ in range(depth.count):
            length = rng.uniform(*depth.size)
            ribbon = depth.ribbons and rng.random() < 0.22
            pieces[depth].append(
                Piece(
                    ribbon=ribbon,
                    x=rng.uniform(-20, W + 20),
                    y=rng.uniform(0, H + 120),
                    length=length * (2.2 if ribbon else 1),
                    width=length * (0.28 if ribbon else rng.uniform(0.45, 0.65)),
                    colour=rng.choice(palette),
                    angle=rng.uniform(0, 2 * math.pi),
                    spins=rng.choice((-1, 1)),
                    flip=rng.uniform(0, 2 * math.pi),
                    flips=rng.choice((1, 2, 2, 3)),
                    sway=rng.uniform(10, 34),
                    sway_phase=rng.uniform(0, 2 * math.pi),
                    wraps=depth.wraps,
                )
            )
    return pieces


def _blur_reach(radius: float) -> int:
    """How far GaussianBlur(radius) spreads a pixel. It is three box blurs, each no wider than the whole-pixel box
    with the same variance, so a layer that is clear this far around its ink blurs the same cropped or whole."""
    return 3 * math.ceil((math.sqrt(1 + 4 * radius**2) - 1) / 2)


def _fit_logo(image: Image.Image) -> Image.Image:
    fitted = ImageOps.contain(image.convert("RGBA"), (LOGO_SIZE, LOGO_SIZE), Image.Resampling.LANCZOS)
    square = Image.new("RGBA", (LOGO_SIZE, LOGO_SIZE), (0, 0, 0, 0))
    square.paste(fitted, ((LOGO_SIZE - fitted.width) // 2, (LOGO_SIZE - fitted.height) // 2))
    return square


def _logo(data: bytes | None) -> Image.Image:
    if data is not None:
        try:
            return _fit_logo(Image.open(io.BytesIO(data)))
        except (OSError, ValueError, Image.DecompressionBombError):
            pass
    return _fit_logo(Image.open(RSC_LOGO))


def _stage(banner: ChampionsBanner) -> Image.Image:
    tier_dark = _mix(banner.tier_colour, (0, 0, 0), 0.82)
    img = _diagonal_gradient((W, H), 0, [(0.0, (8, 7, 12)), (0.55, (14, 11, 20)), (1.0, tier_dark)]).convert("RGBA")

    vignette = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vignette).ellipse((-260, -200, W + 260, H + 240), fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(120)).point(lambda v: 255 - v)
    img.paste((0, 0, 0), (0, 0), vignette.point(lambda v: round(v * 0.75)))

    haze = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(haze).ellipse((80, 430, W - 80, 760), fill=(*banner.tier_colour, 90))
    img.alpha_composite(haze.filter(ImageFilter.GaussianBlur(70)))

    cx, cy = LOGO_CENTRE
    lamps = (-640, -330, 0, 330, 640)

    def cones(spread: float, alpha: int, blur: float) -> Image.Image:
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for offset in lamps:
            sx, sy = cx + offset, -220
            dx, dy = cx - sx, cy - sy
            length = math.hypot(dx, dy)
            ux, uy, nx, ny = dx / length, dy / length, -dy / length, dx / length
            reach = length + 90
            ex, ey = sx + ux * reach, sy + uy * reach
            half = spread * reach
            draw.polygon(
                [
                    (sx - nx * 10, sy - ny * 10),
                    (sx + nx * 10, sy + ny * 10),
                    (ex + nx * half, ey + ny * half),
                    (ex - nx * half, ey - ny * half),
                ],
                fill=(255, 232, 170, alpha),
            )
        return layer.filter(ImageFilter.GaussianBlur(blur))

    beams = cones(0.13, 34, 24)
    beams.alpha_composite(cones(0.055, 62, 5))
    fade = Image.new("L", (1, H))
    fade.putdata([round(255 * min(1.0, max(0.0, (cy + 150 - y) / 110))) for y in range(H)])
    beams.putalpha(ImageChops.multiply(beams.getchannel("A"), fade.resize((W, H))))
    img.alpha_composite(beams)

    pool = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    r = LOGO_SIZE * 0.78
    ImageDraw.Draw(pool).ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 214, 110, 120))
    img.alpha_composite(pool.filter(ImageFilter.GaussianBlur(46)))

    mark = _logo(banner.logo)
    rounded = Image.new("L", mark.size, 0)
    ImageDraw.Draw(rounded).rounded_rectangle((0, 0, LOGO_SIZE - 1, LOGO_SIZE - 1), radius=LOGO_SIZE // 7, fill=255)
    mark.putalpha(ImageChops.multiply(mark.getchannel("A"), rounded))
    pad = _blur_reach(12)
    shadow = Image.new("RGBA", (LOGO_SIZE + 2 * pad, LOGO_SIZE + 2 * pad), (0, 0, 0, 0))
    lx, ly = cx - LOGO_SIZE // 2, cy - LOGO_SIZE // 2
    shadow.paste((0, 0, 0, 150), (pad, pad), mark.getchannel("A"))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(12)), (lx + 6 - pad, ly + 12 - pad))
    img.alpha_composite(mark, (lx, ly))
    return img


def _slanted_line(text: str, font: ImageFont.FreeTypeFont, fill: Image.Image | Colour, shear: float = 0.2) -> Image.Image:
    left, top, right, bottom = font.getbbox(text)
    tw, th = right - left, bottom - top
    pad = 12
    lw, lh = int(tw + shear * th + pad * 2 + 8), int(th + pad * 2 + 8)
    mask = Image.new("L", (lw, lh), 0)
    ImageDraw.Draw(mask).text((pad - left, pad - top), text, font=font, fill=255)
    layer = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    layer.paste((0, 0, 0, 110), (4, 6), mask)
    layer = layer.filter(ImageFilter.GaussianBlur(3))
    face = fill.resize((lw, lh)) if isinstance(fill, Image.Image) else Image.new("RGBA", (lw, lh), (*fill, 255))
    layer.paste(face, (0, 0), mask)
    return _slant(layer, shear)


def _text_layer(banner: ChampionsBanner) -> Image.Image:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx = W // 2
    winner, loser = drawable(banner.winner.upper()), drawable(banner.loser.upper())

    kicker_font = ImageFont.truetype(str(RSC_FONT_BOLD), 36)
    tier = banner.tier.upper()
    tier_fill = (*_mix(banner.tier_colour, (255, 255, 255), 0.35), 255)
    y = 240
    if banner.season is None:
        tw = _spaced_text(draw, (0, -500), tier, kicker_font, 0, 9)
        _spaced_text(draw, (cx - tw / 2, y), tier, kicker_font, tier_fill, 9)
    else:
        season, gap = f"SEASON {banner.season}", 30
        sw = _spaced_text(draw, (0, -500), season, kicker_font, 0, 9)
        tw = _spaced_text(draw, (0, -500), tier, kicker_font, 0, 9)
        x = cx - (sw + gap + tw) / 2
        _spaced_text(draw, (x, y), season, kicker_font, (255, 255, 255, 220), 9)
        _spaced_text(draw, (x + sw + gap, y), tier, kicker_font, tier_fill, 9)

    head_font = ImageFont.truetype(str(RSC_FONT), 128)
    gold = _diagonal_gradient((64, 64), 0, [(0.0, (255, 240, 170)), (0.45, GOLD), (1.0, GOLD_DEEP)]).convert("RGBA")
    head = _slanted_line("CHAMPIONS", head_font, gold)
    layer.alpha_composite(head, (cx - head.width // 2 + 6, 276))

    name_font = _fit_font(RSC_FONT, winner, 70, 820, minimum=48)
    name = _slanted_line(winner, name_font, (255, 255, 255))
    layer.alpha_composite(name, (cx - name.width // 2 + 4, 392))

    # Apotek has no en dash, so the score takes a hyphen.
    small = ImageFont.truetype(str(RSC_FONT_SEMIBOLD), 38)
    score_font = ImageFont.truetype(str(RSC_FONT), 44)
    lead, score = f"DEFEATED {loser}", f"{banner.winner_wins}-{banner.loser_wins}"
    lw = _spaced_text(draw, (0, -500), lead, small, 0, 5)
    sw = draw.textlength(score, font=score_font)
    x = cx - (lw + 26 + sw) / 2
    y = 500
    _spaced_text(draw, (x, y), lead, small, (225, 222, 235, 235), 5)
    s_top = small.getbbox("D")[1]
    sc_top = score_font.getbbox("4")[1]
    draw.text((x + lw + 26, y + s_top - sc_top - 3), score, font=score_font, fill=(*GOLD, 255))
    return layer


def _keep_clear(text: Image.Image) -> Image.Image:
    ink = text.getchannel("A").point(lambda v: 255 if v > 40 else 0)
    x0, y0, x1, y1 = ink.getbbox() or (0, 0, W, H)
    box = (max(x0 - 4, 0), max(y0 - 4, 0), min(x1 + 4, W), min(y1 + 4, H))
    near = Image.new("L", (W, H), 0)
    near.paste(ink.crop(box).filter(ImageFilter.MaxFilter(9)), box[:2])
    cx, cy = LOGO_CENTRE
    r = LOGO_SIZE // 2 + 6
    ImageDraw.Draw(near).rounded_rectangle((cx - r, cy - r, cx + r, cy + r), radius=LOGO_SIZE // 6, fill=255)
    near = near.resize((W // 4, H // 4)).filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(3)).resize((W, H))
    return near.point(lambda v: 255 - round(v * 0.82))


def _depth_layer(depth: Depth, pieces: list[Piece], t: float) -> Image.Image:
    canvas = Image.new("RGBA", (round(W * depth.scale), round(H * depth.scale)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    boxes = []
    for piece in pieces:
        poly, colour = piece.outline(t, depth.scale)
        draw.polygon(poly, fill=(*colour, depth.alpha))
        xs, ys = [x for x, _ in poly], [y for _, y in poly]
        boxes.append((math.floor(min(xs)) - 1, math.floor(min(ys)) - 1, math.floor(max(xs)) + 2, math.floor(max(ys)) + 2))

    # The blur, upscale and reduce run only around each piece, giving the same pixels as running them over the
    # whole canvas: a blur crop keeps a margin twice the filters' reach and pastes back only the inner half, and a
    # reduce crop starts on even pixels so it averages the same 2x2 blocks.
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cw, ch = canvas.size
    if depth.blur:
        # The bilinear upscale reads one pixel past the blur
        reach = _blur_reach(depth.blur) + 1
        for x0, y0, x1, y1 in boxes:
            crop = (max(x0 - 2 * reach, 0), max(y0 - 2 * reach, 0), min(x1 + 2 * reach, cw), min(y1 + 2 * reach, ch))
            keep = (max(x0 - reach, 0), max(y0 - reach, 0), min(x1 + reach, cw), min(y1 + reach, ch))
            if keep[0] >= keep[2] or keep[1] >= keep[3]:
                continue
            region = canvas.crop(crop).filter(ImageFilter.GaussianBlur(depth.blur))
            region = region.resize((region.width * 2, region.height * 2), Image.Resampling.BILINEAR)
            inner = region.crop((2 * (keep[0] - crop[0]), 2 * (keep[1] - crop[1]), 2 * (keep[2] - crop[0]), 2 * (keep[3] - crop[1])))
            layer.paste(inner, (2 * keep[0], 2 * keep[1]))
    else:
        for x0, y0, x1, y1 in boxes:
            crop = (max(x0 & ~1, 0), max(y0 & ~1, 0), min((x1 + 1) & ~1, cw), min((y1 + 1) & ~1, ch))
            if crop[0] >= crop[2] or crop[1] >= crop[3]:
                continue
            layer.paste(canvas.crop(crop).reduce(2), (crop[0] // 2, crop[1] // 2))
    return layer


def _render_frames(banner: ChampionsBanner, seed: str) -> list[Image.Image]:
    base = _stage(banner)
    text = _text_layer(banner)
    clear = _keep_clear(text)
    pieces = _make_pieces(banner, seed)
    frames = []
    for i in range(FRAMES):
        t = i / FRAMES
        far, mid, near = (_depth_layer(depth, pieces[depth], t) for depth in DEPTHS)
        frame = base.copy()
        for layer in (far, mid):
            layer.putalpha(ImageChops.multiply(layer.getchannel("A"), clear))
            frame.alpha_composite(layer)
        frame.alpha_composite(text)
        near.putalpha(ImageChops.multiply(near.getchannel("A"), clear))
        frame.alpha_composite(near)
        frames.append(frame.convert("RGB"))
    return frames


def _encode(frames: list[Image.Image]) -> bytes:
    # Method 3 gives the same size and quality as 4 here, a little faster; 2 and below make a bigger file
    buf = io.BytesIO()
    frames[0].save(buf, format="WEBP", save_all=True, append_images=frames[1:], duration=FRAME_MS, loop=0, quality=82, method=3)
    return buf.getvalue()


def render_champions_banner(banner: ChampionsBanner) -> bytes:
    """Render the finals champions banner as an animated WebP: the winner's logo under spotlights, confetti falling in a loop"""
    seed = f"confetti-{banner.season}-{banner.tier}-{banner.winner}"
    return _encode(_render_frames(banner, seed))


async def champions_banner_bytes(banner: ChampionsBanner) -> bytes:
    return await asyncio.to_thread(render_champions_banner, banner)
