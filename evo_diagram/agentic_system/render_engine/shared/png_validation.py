"""PNG artifact validation shared by render entrypoints."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError


def validate_png_file(output_file: Path, *, context: str) -> None:
    """Raise RuntimeError when output_file is missing, empty, or not a valid PNG."""
    if not output_file.exists():
        raise RuntimeError(f"{context} did not create output file: {output_file}")
    if output_file.stat().st_size <= 0:
        raise RuntimeError(f"{context} created an empty output file: {output_file}")
    try:
        with Image.open(output_file) as image:
            if image.format != "PNG":
                raise RuntimeError(
                    f"{context} created a non-PNG image: {output_file} "
                    f"(format={image.format!r})"
                )
            image.verify()
    except UnidentifiedImageError as exc:
        raise RuntimeError(f"{context} created an unreadable PNG: {output_file}") from exc
    except (OSError, SyntaxError) as exc:
        raise RuntimeError(f"{context} created a corrupt PNG: {output_file}") from exc


__all__ = ["validate_png_file"]
