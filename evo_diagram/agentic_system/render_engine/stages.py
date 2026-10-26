"""Render workflow stage names."""

from __future__ import annotations

CONVERT = "convert"
SIZE_FIT = "size_fit"
ARROW = "arrow"
FIT_GROUPS = "fit_groups"
ALIGN_GROUPS = "align_groups"
ZORDER_REPAIR = "zorder_repair"
VALIDATE = "validate"
RENDER = "render"

MANIFEST_STAGES = frozenset({
    CONVERT,
    SIZE_FIT,
    ARROW,
    FIT_GROUPS,
    ALIGN_GROUPS,
    ZORDER_REPAIR,
})

__all__ = [
    "CONVERT",
    "SIZE_FIT",
    "ARROW",
    "FIT_GROUPS",
    "ALIGN_GROUPS",
    "ZORDER_REPAIR",
    "VALIDATE",
    "RENDER",
    "MANIFEST_STAGES",
]
