"""Pillow-backed image helpers.

None of this had coverage before, which meant a Pillow upgrade could only be
validated by hand. The progress bar in particular builds its fonts at import
time, so a FreeType regression breaks bot startup rather than one command.
"""

import io

import discord
from PIL import Image, ImageDraw, ImageFont

from rsc.utils import images
from rsc.utils.utils import img_to_thumbnail, resize_image


def _png_bytes(size: tuple[int, int], color=(200, 30, 30), mode: str = "RGB") -> bytes:
    fill = color if mode == "RGB" else (*color, 255)
    with io.BytesIO() as buf:
        Image.new(mode, size, fill).save(buf, format="PNG")
        return buf.getvalue()


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def _file_bytes(f: discord.File) -> bytes:
    f.fp.seek(0)
    return f.fp.read()


class TestFonts:
    def test_bundled_fonts_exist(self):
        assert images.RSC_FONT.is_file()
        assert images.RSC_FONT_BOLD.is_file()

    def test_fonts_load_at_import(self):
        # These are module level, so a FreeType or OTF parsing regression takes
        # down `import rsc.utils.images` and with it the whole cog.
        for font in (images.FONT_12, images.FONT_16, images.FONT_22, images.FONT_32):
            assert isinstance(font, ImageFont.FreeTypeFont)

        assert images.FONT_32.size > images.FONT_12.size


class TestDrawProgressBar:
    def test_returns_the_draw_it_was_given(self):
        canvas = Image.new("RGBA", (275, 50))
        draw = ImageDraw.Draw(canvas)

        assert images.drawProgressBar(draw, x=10, y=10, w=225, h=30, progress=0.5) is draw

    def test_progress_changes_the_pixels(self):
        def render(progress: float) -> bytes:
            canvas = Image.new("RGBA", (275, 50))
            images.drawProgressBar(ImageDraw.Draw(canvas), x=10, y=10, w=225, h=30, progress=progress)
            return canvas.tobytes()

        assert render(0.0) != render(1.0)

    def test_bounds_label_differs_from_percentage_label(self):
        # The two branches of the label render different text through FONT_16.
        def render(bounds) -> bytes:
            canvas = Image.new("RGBA", (275, 50))
            images.drawProgressBar(
                ImageDraw.Draw(canvas),
                x=10,
                y=10,
                w=225,
                h=30,
                progress=0.5,
                progress_bounds=bounds,
            )
            return canvas.tobytes()

        assert render(None) != render((50, 100))

    def test_custom_colors_are_applied(self):
        def render(fg) -> bytes:
            canvas = Image.new("RGBA", (275, 50))
            images.drawProgressBar(ImageDraw.Draw(canvas), x=10, y=10, w=225, h=30, progress=0.5, fg=fg)
            return canvas.tobytes()

        assert render((0, 102, 153)) != render((153, 102, 0))


class TestGetProgressBar:
    def test_returns_a_readable_discord_file(self):
        # getProgressBar builds the buffer inside a `with io.BytesIO()` block and
        # returns a File wrapping it. That only survives because discord.File
        # stubs out fp.close(). If that ever changes the buffer arrives closed.
        f = images.getProgressBar(x=10, y=10, w=225, h=30, progress=0.5)

        assert isinstance(f, discord.File)
        assert not f.fp.closed
        assert _file_bytes(f)

    def test_output_is_a_valid_png(self):
        f = images.getProgressBar(x=10, y=10, w=225, h=30, progress=0.5)

        img = _open(_file_bytes(f))
        assert img.format == "PNG"
        assert img.size == (275, 50)
        assert img.mode == "RGBA"

    def test_filename_matches_the_embed_attachment_url(self):
        # rsc/admin/sync.py points its embed at `attachment://progress.jpeg`, so
        # the name is load bearing even though the payload is really a PNG.
        assert images.getProgressBar(x=10, y=10, w=225, h=30).filename == "progress.jpeg"

    def test_renders_across_the_whole_progress_range(self):
        rendered = [
            _open(_file_bytes(images.getProgressBar(x=10, y=10, w=225, h=30, progress=p, progress_bounds=(int(p * 100), 100)))).tobytes()
            for p in (0.0, 0.5, 1.0)
        ]

        assert len(set(rendered)) == 3


class TestResizeImage:
    async def test_resizes_to_the_requested_dimensions(self):
        out = await resize_image(_png_bytes((512, 512)), 64, 32, "PNG")

        # Signature is (height, width); Pillow wants (width, height).
        assert _open(out).size == (32, 64)

    async def test_does_not_preserve_aspect_ratio(self):
        # Unlike img_to_thumbnail, resize stretches to exactly what was asked for.
        out = await resize_image(_png_bytes((400, 100)), 200, 200, "PNG")

        assert _open(out).size == (200, 200)

    async def test_upscales_as_well_as_shrinks(self):
        out = await resize_image(_png_bytes((32, 32)), 128, 128, "PNG")

        assert _open(out).size == (128, 128)

    async def test_converts_rgba_to_rgb_for_jpeg(self):
        # JPEG cannot hold an alpha channel; without the convert() this raises.
        out = await resize_image(_png_bytes((64, 64), mode="RGBA"), 32, 32, "JPEG")

        img = _open(out)
        assert img.format == "JPEG"
        assert img.mode == "RGB"
        assert img.size == (32, 32)

    async def test_keeps_alpha_for_png(self):
        out = await resize_image(_png_bytes((64, 64), mode="RGBA"), 32, 32, "PNG")

        img = _open(out)
        assert img.format == "PNG"
        assert img.mode == "RGBA"


class TestImgToThumbnail:
    async def test_shrinks_to_fit_the_box(self):
        out = await img_to_thumbnail(_png_bytes((512, 512)), 128, 128, "PNG")

        assert _open(out).size == (128, 128)

    async def test_honors_a_non_default_box(self):
        out = await img_to_thumbnail(_png_bytes((512, 512)), 32, 32, "PNG")

        assert _open(out).size == (32, 32)

    async def test_preserves_aspect_ratio(self):
        out = await img_to_thumbnail(_png_bytes((512, 256)), 128, 128, "PNG")

        assert _open(out).size == (128, 64)

    async def test_never_upscales(self):
        out = await img_to_thumbnail(_png_bytes((32, 32)), 128, 128, "PNG")

        assert _open(out).size == (32, 32)

    async def test_shrinks_the_payload_for_guild_emoji_upload(self):
        # rsc/admin/franchise.py uses this to squeeze a logo under the emoji
        # size cap, so the byte count has to actually come down.
        original = _png_bytes((512, 512), color=(12, 200, 87))
        out = await img_to_thumbnail(original, 128, 128, "PNG")

        assert len(out) < len(original)
        assert _open(out).format == "PNG"
