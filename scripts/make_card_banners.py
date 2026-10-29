"""Generate rsc/resources/transactions/card/, the banners for the transaction card.

A single-image MediaGallery always spans the card's full width, which made the
banner far bigger than the old embed's image. Each copy here is the original
banner with transparent padding on the right, so it shows at about 70% of the
card's width, left-aligned, roughly the old embed's size.

    uv run python scripts/make_card_banners.py
"""

from pathlib import Path

from PIL import Image

# Share of the card's width the banner fills
WIDTH = 0.7
BANNERS = ("Released", "Signed", "Resigned", "Subbed", "Retired", "InactiveReserve", "Traded", "ContractExpired", "Trade")

SOURCE = Path(__file__).resolve().parent.parent / "rsc" / "resources" / "transactions"
OUT = SOURCE / "card"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name in BANNERS:
        image = Image.open(SOURCE / f"{name}.png").convert("RGBA")
        canvas = Image.new("RGBA", (round(image.width / WIDTH), image.height), (0, 0, 0, 0))
        canvas.paste(image, (0, 0))
        canvas.save(OUT / f"{name}.png", optimize=True)
        print(f"Wrote {OUT / f'{name}.png'} {canvas.size}")


if __name__ == "__main__":
    main()
