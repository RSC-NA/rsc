import io
import logging
from pathlib import Path

import discord
from PIL import Image, ImageDraw, ImageFont

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


def drawProgressBar(
    d: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    progress,
    progress_bounds: tuple[int, int] | None = None,
    bg=(17, 17, 17),
    fg=(0, 102, 153),
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
        message = (
            f"{progress_bounds[0]} / {progress_bounds[1]} ({int(progress * 100)}%)"
        )
        d.text(((w / 2) + (x * 2), (h / 2) + y), message, font=FONT_16, anchor="mm")
    else:
        message = f"{progress * 100}%"
        d.text(((w / 2) + (x * 2), (h / 2) + y), message, font=FONT_16, anchor="mm")

    return d


def getProgressBar(
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
