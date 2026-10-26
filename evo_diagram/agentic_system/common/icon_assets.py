"""Shared Material icon asset contract.

The canonical runtime URL is ``/icons/material-design-icons/{color}/{icon}.svg``.
Actual SVG files are generated locally and ignored by git, while
``manifest.json`` is tracked and is the stable icon-name catalog.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

from evo_diagram.agentic_system.common.tldraw_utils import TLDrawColorValidator

ICON_ROUTE_PREFIX = "/icons/material-design-icons/"
LEGACY_ICON_ROUTE_PREFIX = "/material-icons/"
ICON_FALLBACK_NAME = "label"
FALLBACK_ICON_FOLDER = "filled"


def icon_assets_root() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "tool_services"
        / "public"
        / "icons"
        / "material-design-icons"
    )


def icon_manifest_path() -> Path:
    return icon_assets_root() / "manifest.json"


def icon_svg_count() -> int:
    """Return the number of generated Material icon SVG files available locally."""
    root = icon_assets_root()
    if not root.exists():
        return 0
    return sum(1 for _ in root.glob("*/*.svg"))


def require_icon_assets_available() -> None:
    """Fail fast when icon generation is enabled but runtime SVG assets are absent."""
    manifest = icon_manifest_path()
    if not manifest.exists():
        raise RuntimeError(
            "Icon generation is enabled, but the Material icon manifest is missing: "
            f"{manifest}. Disable icons or run the icon setup step first."
        )
    if icon_svg_count() == 0:
        raise RuntimeError(
            "Icon generation is enabled, but no Material icon SVG files were found under "
            f"{icon_assets_root()}. Disable icons or run "
            "`python -m evo_diagram.scripts.setup_icons` before generating diagrams with icons."
        )
    # Surface an unreadable/empty catalog here rather than letting every icon
    # name validate as "unknown catalog, allow anything" until render time.
    manifest_icon_names()


class IconManifestError(RuntimeError):
    """Raised when the tracked icon manifest exists but cannot be trusted."""


@lru_cache(maxsize=1)
def manifest_icon_names() -> frozenset[str]:
    """Return the catalog of known icon names.

    An empty result means "no manifest is installed", which callers treat as an
    unknown catalog. A manifest that exists but cannot be parsed, or that
    carries no icon names, raises instead: silently returning an empty set there
    would turn every hallucinated icon name into a valid one. Failures are not
    memoized by ``lru_cache``, so a repaired manifest is picked up on the next
    call.
    """
    manifest_path = icon_manifest_path()
    if not manifest_path.exists():
        return frozenset()

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IconManifestError(
            f"Material icon manifest is unreadable: {manifest_path}: {exc}. "
            "Restore it from git or re-run `python -m evo_diagram.scripts.setup_icons`."
        ) from exc

    names: set[str] = set()
    colors = manifest.get("colors") if isinstance(manifest, dict) else None
    if isinstance(colors, dict):
        for color_data in colors.values():
            if not isinstance(color_data, dict):
                continue
            icons = color_data.get("icons")
            if not isinstance(icons, list):
                continue
            for icon in icons:
                if not isinstance(icon, dict):
                    continue
                name = icon.get("name")
                if isinstance(name, str) and name:
                    names.add(name)

    if not names:
        raise IconManifestError(
            f"Material icon manifest declares no icon names: {manifest_path}. "
            "Restore it from git or re-run `python -m evo_diagram.scripts.setup_icons`."
        )
    return frozenset(names)


def icon_name_exists(icon_name: str) -> bool:
    """Return whether *icon_name* is in the catalog (permissive without one)."""
    names = manifest_icon_names()
    return not names or icon_name in names


def color_to_icon_folder(color: Optional[str]) -> str:
    return TLDrawColorValidator.normalize_color(color or "black").replace("-", "_")


def icon_name_from_filename(filename: str) -> str:
    name = filename.rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".svg") else name


def icon_filename(icon_name: str) -> str:
    name = icon_name.rsplit("/", 1)[-1]
    return name if name.endswith(".svg") else f"{name}.svg"


def format_icon_url(icon_name: str, icon_color: str, base_url: str) -> str:
    return base_url.format(
        color=color_to_icon_folder(icon_color),
        icon=icon_name_from_filename(icon_name),
    )


def is_local_material_icon_url(icon_url: str) -> bool:
    """Return whether a URL/path points at the bundled Material icon route."""
    path = icon_url_path(icon_url)
    return ICON_ROUTE_PREFIX in path or LEGACY_ICON_ROUTE_PREFIX in path


def icon_url_path(icon_url: str) -> str:
    if not isinstance(icon_url, str) or not icon_url:
        return ""
    parsed = urlparse(icon_url)
    return parsed.path if parsed.scheme or parsed.netloc else icon_url


def icon_folder_hint(icon_url: str) -> Optional[str]:
    path = icon_url_path(icon_url)
    for prefix in (ICON_ROUTE_PREFIX, LEGACY_ICON_ROUTE_PREFIX):
        if prefix not in path:
            continue
        suffix = path.split(prefix, 1)[1].lstrip("/")
        folder = suffix.split("/", 1)[0]
        if folder:
            return folder
    return None


def resolve_icon_svg_path(filename: str, folders: Iterable[str]) -> Optional[Path]:
    if not filename:
        return None
    filename = icon_filename(filename)
    root = icon_assets_root()
    seen: set[str] = set()
    for folder in folders:
        if not folder or folder in seen:
            continue
        seen.add(folder)
        candidate = root / folder / filename
        if candidate.exists():
            return candidate
    return None


def require_icon_svg_path(
    icon_name: str,
    *,
    icon_color: Optional[str] = None,
    icon_url: str = "",
    element_id: Optional[str] = None,
) -> Path:
    """Resolve a concrete SVG asset or raise with an actionable diagnostic."""
    if not isinstance(icon_name, str) or not icon_name.strip():
        target = f" for {element_id}" if element_id else ""
        raise RuntimeError(f"Icon asset reference{target} is missing an icon name.")

    candidate_folders: list[str] = []
    folder_hint = icon_folder_hint(icon_url)
    if folder_hint:
        candidate_folders.append(folder_hint)
    if icon_color:
        candidate_folders.append(color_to_icon_folder(icon_color))
    candidate_folders.append(FALLBACK_ICON_FOLDER)

    resolved = resolve_icon_svg_path(icon_name.strip(), candidate_folders)
    if resolved is not None:
        return resolved

    target = f" for {element_id}" if element_id else ""
    folders = ", ".join(dict.fromkeys(candidate_folders))
    raise RuntimeError(
        f"Icon asset not found{target}: icon={icon_name!r}, "
        f"color={icon_color!r}, folders=[{folders}], root={icon_assets_root()}. "
        "Run `python -m evo_diagram.scripts.setup_icons` or disable icon generation."
    )


__all__ = [
    "ICON_FALLBACK_NAME",
    "ICON_ROUTE_PREFIX",
    "LEGACY_ICON_ROUTE_PREFIX",
    "FALLBACK_ICON_FOLDER",
    "IconManifestError",
    "color_to_icon_folder",
    "format_icon_url",
    "icon_assets_root",
    "icon_filename",
    "icon_folder_hint",
    "icon_manifest_path",
    "icon_svg_count",
    "icon_name_exists",
    "icon_name_from_filename",
    "icon_url_path",
    "is_local_material_icon_url",
    "manifest_icon_names",
    "require_icon_svg_path",
    "require_icon_assets_available",
    "resolve_icon_svg_path",
]
