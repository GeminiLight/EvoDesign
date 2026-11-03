"""Scene preparation and visual geometry exposed to generation and refinement."""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from . import _render_engine_adapter


def excalidraw_element_defaults(seed: Any) -> Dict[str, Any]:
    """Return deterministic metadata defaults for one native element."""
    return _render_engine_adapter.excalidraw_element_defaults(seed)


def rebuild_excalidraw_arrows(
    manifest: Dict[str, Any], structure_instantiation: Dict[str, Any],
) -> Dict[str, Any]:
    """Rebuild semantic connectors while retaining authored styles and labels."""
    return _render_engine_adapter.rebuild_excalidraw_arrows(manifest, structure_instantiation)


def compact_architecture_layout(
    manifest: Dict[str, Any], structure_instantiation: Dict[str, Any],
) -> Dict[str, Any]:
    """Compact native architecture scenes; preserve identity for other types."""
    return _render_engine_adapter.compact_architecture_layout(manifest, structure_instantiation)


def normalize_architecture_style(
    manifest: Dict[str, Any], structure_instantiation: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply consistent architecture typography and role-based styling."""
    return _render_engine_adapter.normalize_architecture_style(manifest, structure_instantiation)


def disjoint_segment_box_distance(
    start: Sequence[float], end: Sequence[float], box: Sequence[float],
) -> float:
    """Measure the gap between a disjoint connector segment and label box."""
    return _render_engine_adapter.disjoint_segment_box_distance(start, end, box)


def color_contrast_ratio(color_a: str, color_b: str) -> Optional[float]:
    """Return color contrast, or None when either color cannot be resolved."""
    return _render_engine_adapter.color_contrast_ratio(color_a, color_b)
