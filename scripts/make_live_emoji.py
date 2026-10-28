"""Generate rsc/resources/emoji/live.gif, the animated "live" application emoji.

A green dot that pulses: it grows and brightens, then settles, on a loop. GIF
transparency is all-or-nothing, so the edge is drawn hard (no anti-aliasing)
to avoid a fringe on light themes. Discord shows emoji at 22-48px, where a
hard edge reads as a clean circle.

    uv run python scripts/make_live_emoji.py
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 128
FRAMES = 16
FRAME_MS = 80  # 16 x 80ms = 1.28s per pulse
# Discord's "online" green, and a brighter tint for the peak of the pulse
BASE = (35, 165, 90)
PEAK = (87, 242, 135)
MIN_RADIUS = 0.30
MAX_RADIUS = 0.44
# Palette colour behind the transparency index; never visible
TRANSPARENT_KEY = (255, 0, 255)

OUT = Path(__file__).resolve().parent.parent / "rsc" / "resources" / "emoji" / "live.gif"


def frame(t: float) -> Image.Image:
    """One frame at phase t in [0, 1)."""
    # Ease in and out, so the pulse lingers at its smallest and largest
    pulse = (1 - math.cos(2 * math.pi * t)) / 2
    radius = SIZE * (MIN_RADIUS + (MAX_RADIUS - MIN_RADIUS) * pulse)
    colour = tuple(round(b + (p - b) * pulse) for b, p in zip(BASE, PEAK, strict=True))

    # Explicit two-colour palette: index 0 is the transparent background, index 1
    # the dot. Letting Pillow quantize RGBA frames can hand index 0 to the dot,
    # which `transparency=0` then turns invisible.
    img = Image.new("P", (SIZE, SIZE), 0)
    img.putpalette([*TRANSPARENT_KEY, *colour])
    centre = SIZE / 2
    ImageDraw.Draw(img).ellipse((centre - radius, centre - radius, centre + radius, centre + radius), fill=1)
    return img


def main() -> None:
    frames = [frame(i / FRAMES) for i in range(FRAMES)]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        OUT,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_MS,
        loop=0,
        disposal=2,  # clear each frame so a shrinking dot leaves no trail
        transparency=0,
        optimize=False,
    )
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
