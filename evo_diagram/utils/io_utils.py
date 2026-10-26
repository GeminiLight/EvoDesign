"""Generic file I/O utilities. No domain-specific dependencies."""

import os
import json
import base64
import shutil
from io import BytesIO
from mimetypes import guess_type
from typing import Any


def ensure_dirs(*dirs: str) -> None:
    """Create directories (mkdir -p)."""
    for d in dirs:
        os.makedirs(d, exist_ok=True)


def save_json(data: Any, path: str) -> str:
    """Save data as JSON. Returns the path written."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    return path


def load_json(path: str) -> Any:
    """Load JSON from file."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def copy_file(source: str, dest: str) -> str:
    """Copy a file from source to dest. Returns dest path."""
    if not os.path.exists(source):
        raise FileNotFoundError(f"Source file not found: {source}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy(source, dest)
    return dest


def image_to_data_url(image_path: str, *, max_edge: int | None = None) -> str:
    """Encode an image, optionally bounding review input without changing the file.

    Geometry-sensitive refiner inputs must use the default (original pixels).
    The critic uses a bounded, lossless PNG instead of a 4x product export.
    """
    if max_edge is not None:
        if max_edge < 1:
            raise ValueError("max_edge must be positive")
        from PIL import Image

        with Image.open(image_path) as image:
            if max(image.size) > max_edge:
                image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    mime_type, _ = guess_type(image_path)
    if mime_type is None:
        mime_type = 'application/octet-stream'
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode('utf-8')
    return f"data:{mime_type};base64,{b64}"
