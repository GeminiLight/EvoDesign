"""Centralized path management for the EvoDiagram project.

This module provides a single source of truth for all project paths,
eliminating inconsistent path resolutions across the codebase.
"""

import os
from pathlib import Path
from typing import Optional

# Package root and repository root.
# This file is at: <repo>/evo_diagram/utils/path_manager.py.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PACKAGE_ROOT.parent

# Common directories
AGENTIC_SYSTEM_DIR = PACKAGE_ROOT / "agentic_system"
RESOURCES_DIR = PACKAGE_ROOT / "resources"
DATA_DIR = PACKAGE_ROOT / "data"
DATASET_DIR = REPO_ROOT / "dataset"
RESULTS_DIR = PACKAGE_ROOT / "results"
SCRIPTS_DIR = REPO_ROOT / "scripts"
CONFIG_DIR = REPO_ROOT / "configs"
DESIGN_MEMORY_DIR = PACKAGE_ROOT / "design_memory"
EVALUATION_DIR = REPO_ROOT / "evaluation"
BASELINES_DIR = REPO_ROOT / "baselines"
EXAMPLES_DIR = REPO_ROOT / "examples"
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
DEFAULT_TEST_DATASET = DATASET_DIR / "test" / "data.json"

# Resource subdirectories
FONTS_DIR = RESOURCES_DIR / "fonts"
IMAGES_DIR = RESOURCES_DIR / "images"
FIGURES_DIR = RESOURCES_DIR / "figures"

# Stage directories
GENERATION_STAGE_DIR = AGENTIC_SYSTEM_DIR / "generation_stage"
VERIFICATION_STAGE_DIR = AGENTIC_SYSTEM_DIR / "verification_stage"
REFINEMENT_STAGE_DIR = AGENTIC_SYSTEM_DIR / "refinement_stage"
RENDER_ENGINE_DIR = AGENTIC_SYSTEM_DIR / "render_engine"

# Font files
FONT_FILES = {
    "mono": FONTS_DIR / "IBMPlexMono-Medium.ttf",
    "sans": FONTS_DIR / "IBMPlexSans-Medium.ttf",
    "serif": FONTS_DIR / "IBMPlexSerif-Medium.ttf",
    "draw": FONTS_DIR / "Shantell_Sans-Informal_Regular.ttf",
}

# Material icons directory
MATERIAL_ICONS_DIR = RESOURCES_DIR / "icons" / "material-design-icons" / "filled"

# Environment file — repository-root .env
ENV_FILE = REPO_ROOT / ".env"


def get_path(relative_path: str, base: Optional[Path] = None) -> Path:
    """
    Get an absolute path from a relative path.

    Args:
        relative_path: Relative path string (e.g., 'resources/fonts')
        base: Base directory (defaults to PACKAGE_ROOT)

    Returns:
        Absolute Path object
    """
    base = base or PACKAGE_ROOT
    return (base / relative_path).resolve()


def ensure_dir(path: Path) -> Path:
    """
    Ensure a directory exists, creating it if necessary.

    Args:
        path: Directory path to ensure

    Returns:
        The path (same as input)
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_path_segment(value: object, *, field_name: str = "path segment") -> str:
    """Return a single filesystem-safe path segment or raise ``ValueError``.

    Dataset ids, tags, and sample ids are user/data controlled. They must never
    be joined directly into output paths because ``..`` or separators can escape
    the intended experiment directory. This helper is intentionally strict to
    avoid silent collisions from slugifying distinct ids to the same name.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    raw = value
    if not raw:
        raise ValueError(f"{field_name} must not be empty.")
    if raw != raw.strip():
        raise ValueError(f"{field_name} must not contain leading or trailing whitespace.")
    if raw in {".", ".."}:
        raise ValueError(f"{field_name} must be a normal file name segment: {raw!r}.")
    if "/" in raw or "\\" in raw or "\x00" in raw:
        raise ValueError(f"{field_name} must not contain path separators: {raw!r}.")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    invalid = sorted({ch for ch in raw if ch not in allowed})
    if invalid:
        sample = "".join(invalid[:8])
        raise ValueError(
            f"{field_name} contains unsupported character(s) {sample!r}; "
            "use only letters, numbers, '-', '_', and '.'."
        )
    return raw


def safe_join_under(root: Path | str, *segments: object) -> Path:
    """Join safe segments under ``root`` and verify the result stays inside it."""
    root_path = Path(root).resolve()
    safe_segments = [
        safe_path_segment(segment, field_name=f"path segment {idx + 1}")
        for idx, segment in enumerate(segments)
    ]
    joined = root_path.joinpath(*safe_segments).resolve()
    try:
        joined.relative_to(root_path)
    except ValueError as exc:
        raise ValueError(f"Resolved output path escapes root {root_path}: {joined}") from exc
    return joined


def get_package_root() -> Path:
    """Get the evo_diagram package root directory."""
    return PACKAGE_ROOT


def get_repo_root() -> Path:
    """Get the repository root directory."""
    return REPO_ROOT


def get_env_file() -> Path:
    """Get the .env file path."""
    return ENV_FILE


def get_font_path(font_name: str) -> Path:
    """
    Get the path to a font file.

    Args:
        font_name: Font name ('mono', 'sans', 'serif', 'draw')

    Returns:
        Path to the font file
    """
    font_key = font_name.lower()
    if font_key not in FONT_FILES:
        raise ValueError(f"Unknown font: {font_name}. Available fonts: {list(FONT_FILES.keys())}")
    return FONT_FILES[font_key]


__all__ = [
    "PACKAGE_ROOT",
    "REPO_ROOT",
    "RESOURCES_DIR",
    "DATASET_DIR",
    "EXAMPLES_DIR",
    "EXPERIMENTS_DIR",
    "DEFAULT_TEST_DATASET",
    "FONTS_DIR",
    "FONT_FILES",
    "MATERIAL_ICONS_DIR",
    "ENV_FILE",
    "get_path",
    "ensure_dir",
    "safe_path_segment",
    "safe_join_under",
    "get_package_root",
    "get_repo_root",
    "get_env_file",
    "get_font_path",
]
