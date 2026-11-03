# -*- coding: utf-8 -*-
"""Display dataset images from notebooks or the command line."""

import argparse
import sys
from pathlib import Path
from typing import Optional

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IMAGE_DIR = REPO_ROOT / "dataset" / "images" / "diagrams"
IMAGE_EXTS = (".jpg", ".jpeg", ".png")


def resolve_image_path(data_id: str, image_dir: Path = DEFAULT_IMAGE_DIR) -> Path:
    """Resolve a dataset image id or explicit path to an existing file."""
    explicit = Path(data_id).expanduser()
    if explicit.exists() and explicit.is_file():
        return explicit

    stem = explicit.stem if explicit.suffix.lower() in IMAGE_EXTS else data_id
    for ext in IMAGE_EXTS:
        candidate = image_dir / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Image not found for id {data_id!r} under {image_dir}")


def show_image(
    data_id: str,
    width: Optional[int] = None,
    height: Optional[int] = None,
    title: Optional[str] = None
) -> Image.Image:
    """
    Display images in Jupyter Notebook

    Args:
        data_id: Data ID, automatically concatenated to ./dataset/images/diagrams/{data_id}.jpg
        width: Optional, display width (pixels)
        height: Optional, display height (pixels)
        title: Optional, title displayed above the image

    Returns:
        PIL.Image object

    Raises:
        FileNotFoundError: Image file does not exist

    Example:
        >>> from scripts.show_image import show_image
        >>> show_image("tree_20251205_064215_211")
    """
    img_path = resolve_image_path(data_id)

    img = Image.open(img_path)

    # Optional scaling
    if width or height:
        w, h = img.size
        if width and not height:
            height = int(h * width / w)
        elif height and not width:
            width = int(w * height / h)
        img = img.resize((width, height))

    print(title or data_id)

    from IPython.display import display
    display(img)
    return img


def show_images(
    data_ids: list,
    width: Optional[int] = None,
    titles: Optional[list] = None
) -> list:
    """
    Batch display multiple images

    Args:
        data_ids: Data ID list
        width: Optional, unified display width
        titles: Optional, title list for each image

    Returns:
        PIL.Image object list
    """
    images = []
    for i, data_id in enumerate(data_ids):
        title = titles[i] if titles and i < len(titles) else None
        img = show_image(data_id, width=width, title=title)
        images.append(img)
    return images


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_id", help="Dataset image id or explicit image path.")
    parser.add_argument(
        "--image-dir",
        type=Path,
        default=DEFAULT_IMAGE_DIR,
        help="Directory containing dataset images.",
    )
    args = parser.parse_args(argv)

    try:
        img_path = resolve_image_path(args.data_id, image_dir=args.image_dir)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    img = Image.open(img_path)
    print(f"Image: {img_path}")
    print(f"Image size: {img.size}")
    print(f"Image mode: {img.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
