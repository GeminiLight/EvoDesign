"""Generate responsive website previews; retain the original screenshots and figures."""

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "docs/assets/previews"


def main() -> None:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    sources = [
        ("docs/screenshots/studio-home-en.jpg", "studio-home", (640, 960, 1440), False),
        ("docs/assets/method-overview.png", "method-overview", (612, 1224, 2448), True),
        ("docs/assets/canvasbench-overview.png", "canvasbench-overview", (612, 1224, 2448), True),
    ]
    for source, name, widths, lossless in sources:
        with Image.open(ROOT / source) as original:
            image = original.convert("RGB")
            for width in widths:
                height = round(image.height * width / image.width)
                preview = image.resize((width, height), Image.Resampling.LANCZOS)
                target = DESTINATION / f"{name}-{width}.webp"
                preview.save(target, "WEBP", lossless=lossless, quality=88, method=6)
                print(f"{target.relative_to(ROOT)}: {target.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
