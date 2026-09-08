"""Aggregator: run every objective check and return a flat List[Finding]."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from evo_diagram.canvas_runtime import normalize_canvas_library

from .binding_consistency import check_arrow_shape_binding
from .collision_detection import (
    check_edge_crossings,
    check_edge_node_intersections,
    check_node_overlap,
    check_out_of_canvas,
)
from .containment import (
    check_group_bbox_contains_children,
    check_swimlane_lane_membership,
)
from .finding import Finding, summarize_findings
from .objective_manifest import build_objective_manifest
from .render_validation import (
    check_layout_audit,
    check_render_audit,
    check_schema,
)

logger = logging.getLogger(__name__)
_CheckSpec = Tuple[str, Callable[..., List[Finding]], tuple[Any, ...]]


def _is_skipped(skip_key: str, skip_prefixes: set[str]) -> bool:
    return any(
        skip_key == prefix or skip_key.startswith(f"{prefix}/")
        for prefix in skip_prefixes
    )


def _check_specs(
    manifest: Dict[str, Any],
    structure: Optional[Dict[str, Any]],
    layout_instantiation: Optional[Dict[str, Any]],
    canvas_library: str,
) -> List[_CheckSpec]:
    objective_manifest = build_objective_manifest(
        manifest,
        canvas_library=canvas_library,
        structure=structure,
    )
    return [
        ("schema", check_schema, (manifest, canvas_library)),
        ("render_audit", check_render_audit, (manifest, structure, canvas_library)),
        ("layout_audit", check_layout_audit, (layout_instantiation, structure)),
        ("binding", check_arrow_shape_binding, (objective_manifest,)),
        ("containment/group_bbox", check_group_bbox_contains_children, (objective_manifest, structure)),
        ("containment/swimlane_lane", check_swimlane_lane_membership, (objective_manifest, structure)),
        ("collision/node_overlap", check_node_overlap, (objective_manifest,)),
        ("collision/edge_crossing", check_edge_crossings, (objective_manifest,)),
        ("collision/edge_node_intersection", check_edge_node_intersections, (objective_manifest,)),
        ("collision/out_of_canvas", check_out_of_canvas, (objective_manifest,)),
    ]


def run_all_checks(
    manifest: Dict[str, Any],
    structure: Optional[Dict[str, Any]] = None,
    layout_instantiation: Optional[Dict[str, Any]] = None,
    canvas_library: str = "excalidraw",
    skip_categories: Optional[List[str]] = None,
) -> List[Finding]:
    """Run every objective check, concatenate results in deterministic order.

    Order matters for deterministic reports: schema → audit → layout audit →
    binding → containment (group then swimlane) → collisions
    (overlap → crossings → out_of_canvas).

    Parameters
    ----------
    skip_categories:
        List of category prefixes to skip (e.g. ``["schema", "collision"]``).
        A check is skipped if any skip prefix matches the beginning of any
        Finding category it would produce.  The mapping from skip prefix to
        check functions is defined by ``_check_specs``.
    """
    canvas_library = normalize_canvas_library(canvas_library)
    skip = set(skip_categories or [])

    findings: List[Finding] = []
    for skip_key, check_fn, args in _check_specs(
        manifest,
        structure,
        layout_instantiation,
        canvas_library,
    ):
        if _is_skipped(skip_key, skip):
            continue
        try:
            findings.extend(check_fn(*args))
        except Exception as exc:  # noqa: BLE001
            logger.exception("objective check failed: %s", skip_key)
            findings.append(
                Finding(
                    category=f"verification/internal_error/{skip_key}",
                    severity="critical",
                    message=(
                        f"Objective check {skip_key} failed: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )
            )

    return findings


__all__ = ["run_all_checks", "summarize_findings"]
