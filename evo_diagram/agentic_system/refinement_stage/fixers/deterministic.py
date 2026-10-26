"""Deterministic fixers — verifier finding → EditOp list, no LLM involved.

Each fixer is a pure function that consumes the current manifest and the
list of Findings, and returns a List[EditOp]. The fixer NEVER mutates the
manifest itself — that's apply_edits's job. This keeps the workflow
auditable: every change shows up as an EditOp before being applied.

Fixers are idempotent by construction: re-running a fixer on a manifest
that already satisfies the invariant returns ``[]``. This is verified by
the workflow's idempotence smoke test.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

from evo_diagram.canvas_environment import (
    CANVAS_MARGIN,
    CANVAS_MAX_X,
    CANVAS_MAX_Y,
    detect_group_frame_ids,
    repair_manifest_zorder,
)
from evo_diagram.agentic_system.common.semantic_ids import id_map_from_manifest
from evo_diagram.agentic_system.verification_stage.checks.finding import Finding

from ..state import EditOp

logger = logging.getLogger(__name__)


class DeterministicFixerError(RuntimeError):
    """Raised when a deterministic fixer crashes instead of producing edits."""

    def __init__(self, fixer_name: str, cause: Exception) -> None:
        self.fixer_name = fixer_name
        self.cause = cause
        super().__init__(f"deterministic fixer {fixer_name!r} failed: {cause}")


def _get_bbox(elem: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    try:
        x = float(elem.get("x", 0) or 0)
        y = float(elem.get("y", 0) or 0)
        w = float(elem.get("width", 0) or 0)
        h = float(elem.get("height", 0) or 0)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


def _by_id(manifest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    elements = manifest.get("elements", [])
    if not isinstance(elements, list):
        return {}
    return {
        elem.get("id"): elem
        for elem in elements
        if isinstance(elem, dict) and elem.get("id") and not elem.get("isDeleted")
    }


def _hex_to_rgb(hex_str: str) -> Optional[Tuple[int, int, int]]:
    if not isinstance(hex_str, str):
        return None
    s = hex_str.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        return None
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return None


def _luminance(rgb: Tuple[int, int, int]) -> float:
    """WCAG relative luminance."""

    def _ch(v: int) -> float:
        c = v / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * _ch(r) + 0.7152 * _ch(g) + 0.0722 * _ch(b)


def _contrast_ratio(a: Tuple[int, int, int], b: Tuple[int, int, int]) -> float:
    """WCAG contrast ratio between two colors. Range ``[1.0, 21.0]``."""
    lum_a = _luminance(a)
    lum_b = _luminance(b)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def _findings_by_category(findings: List[Finding], category_prefix: str) -> List[Finding]:
    return [f for f in findings if f.category.startswith(category_prefix)]


# ---------------------------------------------------------------------------
# Fixer 1 — clear_dangling_binding
# ---------------------------------------------------------------------------


def fix_dangling_bindings(
    manifest: Dict[str, Any],
    findings: List[Finding],
    _structure: Optional[Dict[str, Any]] = None,
) -> List[EditOp]:
    """For each ``binding/dangling_reference`` finding, clear the bad binding.

    Dispatch is driven by the FINDING shape, not by the element type. The
    verifier emits ``boundElements lists id=...`` for **every** element type
    (arrows routinely carry a bound label), so a type-based branch dropped the
    arrow case entirely and the same MAJOR was re-reported every round with no
    fixer able to address it.

      - ``location.missing_bound_id``     → ``remove_bound_element`` (any type)
      - ``location.missing_container_id`` → ``clear_container_binding``
      - arrow ``start``/``end`` binding   → ``clear_arrow_binding``
    """
    edits: List[EditOp] = []
    by_id = _by_id(manifest)
    live_ids = set(by_id.keys())

    relevant = _findings_by_category(findings, "binding/dangling_reference")
    for finding in relevant:
        eid = finding.element_id
        if not eid or eid not in by_id:
            continue
        elem = by_id[eid]
        loc = finding.location if isinstance(finding.location, dict) else {}

        # --- stale boundElements ref (holder can be any type, arrows included)
        missing_bound_id = loc.get("missing_bound_id")
        if isinstance(missing_bound_id, str) and missing_bound_id:
            holder_id = loc.get("holder_id")
            if isinstance(holder_id, str) and holder_id and holder_id != eid:
                logger.warning(
                    "Skipping dangling boundElements finding with mismatched holder: "
                    "element_id=%r location.holder_id=%r",
                    eid,
                    holder_id,
                )
                continue
            bound = elem.get("boundElements")
            if not isinstance(bound, list):
                continue
            if not any(
                isinstance(item, dict) and item.get("id") == missing_bound_id
                for item in bound
            ):
                continue
            if missing_bound_id in live_ids:
                continue
            edits.append(
                EditOp(
                    op="remove_bound_element",
                    id=eid,
                    payload={"bound_id": missing_bound_id},
                    rationale=f"remove dangling boundElements ref {missing_bound_id!r}",
                    source="deterministic",
                )
            )
            continue

        # --- text containerId pointing at a missing shape
        missing_container_id = loc.get("missing_container_id")
        container_id = elem.get("containerId")
        if isinstance(missing_container_id, str) and missing_container_id:
            if (
                isinstance(container_id, str)
                and container_id
                and container_id not in live_ids
            ):
                edits.append(
                    EditOp(
                        op="clear_container_binding",
                        id=eid,
                        payload={"container_id": container_id},
                        rationale=f"clear dangling text containerId={container_id!r}",
                        source="deterministic",
                    )
                )
            continue

        # --- arrow side binding pointing at a missing shape
        if elem.get("type") == "arrow":
            for side in ("start", "end"):
                binding = elem.get(f"{side}Binding")
                if not isinstance(binding, dict):
                    continue
                target = binding.get("elementId")
                if target and target not in live_ids:
                    edits.append(
                        EditOp(
                            op="clear_arrow_binding",
                            id=eid,
                            payload={"side": side},
                            rationale=f"{side}Binding.elementId={target!r} does not exist",
                            source="deterministic",
                        )
                    )
            continue

        # --- fallback for findings without location payload
        if (
            elem.get("type") == "text"
            and isinstance(container_id, str)
            and container_id
            and container_id not in live_ids
        ):
            edits.append(
                EditOp(
                    op="clear_container_binding",
                    id=eid,
                    payload={"container_id": container_id},
                    rationale=f"clear dangling text containerId={container_id!r}",
                    source="deterministic",
                )
            )

    return edits


# ---------------------------------------------------------------------------
# Fixer 2 — repair_back_refs
# ---------------------------------------------------------------------------


def fix_missing_back_refs(
    manifest: Dict[str, Any],
    findings: List[Finding],
    _structure: Optional[Dict[str, Any]] = None,
) -> List[EditOp]:
    """Append missing arrow→shape back-refs in ``boundElements``.

    The verifier message looks like:
      "arrow X binds to shape Y via startBinding, but the shape's
       boundElements does not list this arrow id back."

    We re-derive (arrow_id, shape_id) by scanning bindings ourselves; the
    finding messages are human-readable and not parsed.
    """
    edits: List[EditOp] = []
    by_id = _by_id(manifest)
    elements = manifest.get("elements", [])
    if not isinstance(elements, list):
        return edits

    if not _findings_by_category(findings, "binding/missing_back_ref"):
        return edits

    for elem in elements:
        if not isinstance(elem, dict) or elem.get("type") != "arrow":
            continue
        arrow_id = elem.get("id")
        if not arrow_id:
            continue
        for side in ("start", "end"):
            binding = elem.get(f"{side}Binding")
            if not isinstance(binding, dict):
                continue
            target_id = binding.get("elementId")
            if not target_id or target_id not in by_id:
                continue
            target = by_id[target_id]
            bound = target.get("boundElements")
            existing = (
                {b.get("id") for b in bound if isinstance(b, dict)}
                if isinstance(bound, list)
                else set()
            )
            if arrow_id not in existing:
                edits.append(
                    EditOp(
                        op="append_bound_element",
                        id=target_id,
                        payload={"bound_id": arrow_id, "type": "arrow"},
                        rationale=f"add missing back-ref for arrow {arrow_id} via {side}Binding",
                        source="deterministic",
                    )
                )

    return edits


# ---------------------------------------------------------------------------
# Fixer 3 — snap_to_lane_centerline
# ---------------------------------------------------------------------------


def fix_swimlane_lane_membership(
    manifest: Dict[str, Any],
    findings: List[Finding],
    _structure: Optional[Dict[str, Any]] = None,
) -> List[EditOp]:
    """For nodes whose y-band crosses or escapes their lane, snap to centerline."""
    edits: List[EditOp] = []
    by_id = _by_id(manifest)

    relevant = _findings_by_category(findings, "containment/swimlane_lane")
    for finding in relevant:
        eid = finding.element_id
        if not eid or eid not in by_id:
            continue
        loc = finding.location or {}
        lane = loc.get("lane")
        if not isinstance(lane, dict):
            continue
        node = loc.get("node") or {}
        try:
            lane_y = float(lane.get("y", 0))
            lane_h = float(lane.get("h", 0))
            node_h = float(node.get("h", 0))
        except (TypeError, ValueError):
            continue
        if lane_h <= 0 or node_h <= 0:
            continue

        # Centerline placement; preserve x.
        target_y = lane_y + lane_h / 2 - node_h / 2
        elem = by_id[eid]
        edits.append(
            EditOp(
                op="set_position",
                id=eid,
                payload={"x": float(elem.get("x", 0)), "y": target_y},
                rationale=(
                    f"snap to lane '{loc.get('lane_id', '?')}' centerline "
                    f"y={target_y:.0f}"
                ),
                source="deterministic",
            )
        )

    return edits


# ---------------------------------------------------------------------------
# Fixer 4 — shrink_to_group_bbox
# ---------------------------------------------------------------------------


def fix_group_bbox_escape(
    manifest: Dict[str, Any],
    findings: List[Finding],
    _structure: Optional[Dict[str, Any]] = None,
) -> List[EditOp]:
    """Move/shrink a child whose bbox escapes its group bg."""
    edits: List[EditOp] = []
    by_id = _by_id(manifest)

    relevant = _findings_by_category(findings, "containment/group_bbox")
    for finding in relevant:
        eid = finding.element_id
        if not eid or eid not in by_id:
            continue
        loc = finding.location or {}
        child = loc.get("child")
        group = loc.get("group")
        if not (isinstance(child, dict) and isinstance(group, dict)):
            continue
        try:
            cx = float(child["x"])
            cy = float(child["y"])
            cw = float(child["w"])
            ch = float(child["h"])
            gx = float(group["x"])
            gy = float(group["y"])
            gw = float(group["w"])
            gh = float(group["h"])
        except (TypeError, ValueError, KeyError):
            continue

        # Strategy: clamp position first; if child too large for group, also resize.
        target_w = min(cw, gw - 8)
        target_h = min(ch, gh - 8)
        target_x = max(gx + 4, min(cx, gx + gw - target_w - 4))
        target_y = max(gy + 4, min(cy, gy + gh - target_h - 4))

        if target_x != cx or target_y != cy:
            edits.append(
                EditOp(
                    op="set_position",
                    id=eid,
                    payload={"x": target_x, "y": target_y},
                    rationale=f"clamp into group {loc.get('group_id', '?')!r} bbox",
                    source="deterministic",
                )
            )
        if target_w != cw or target_h != ch:
            edits.append(
                EditOp(
                    op="set_size",
                    id=eid,
                    payload={"width": target_w, "height": target_h},
                    rationale="shrink to fit group bbox",
                    source="deterministic",
                )
            )

    return edits


# ---------------------------------------------------------------------------
# Fixer 5 — clamp_to_canvas
# ---------------------------------------------------------------------------


def _bbox_inside(outer: Tuple[float, float, float, float],
                 inner: Tuple[float, float, float, float],
                 tol: float = 4.0) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return (
        ix >= ox - tol
        and iy >= oy - tol
        and ix + iw <= ox + ow + tol
        and iy + ih <= oy + oh + tol
    )


def _clamp_axis(value: float, size: float, limit: float) -> Optional[float]:
    """Clamp one axis into ``[CANVAS_MARGIN, limit - CANVAS_MARGIN]``.

    Returns ``None`` when the element is wider/taller than the safe area — no
    position satisfies the check, so nudging it only produces a MINOR that
    reappears every round.
    """
    if size > limit - 2 * CANVAS_MARGIN:
        return None
    return max(CANVAS_MARGIN, min(value, limit - size - CANVAS_MARGIN))


def fix_out_of_canvas(
    manifest: Dict[str, Any],
    findings: List[Finding],
    _structure: Optional[Dict[str, Any]] = None,
) -> List[EditOp]:
    """Pull off-canvas elements back into the safe area.

    Two guards that were missing:

    - **Frames / lane backgrounds.** ``op_set_position`` relocates only the
      container's bound text, never its members, so clamping a lane converted
      one MINOR into a batch of MAJOR containment findings. A frame is moved
      only when it still fits the safe area, and then every element sitting
      inside it is moved by the same delta.
    - **Oversized elements.** A background as wide as the canvas can never
      satisfy the margin; clamping it re-emits the same MINOR forever, so the
      axis it cannot fit on is left alone.

    Arrows are skipped outright: their shape is a baked polyline that follows
    its endpoints through the arrow re-route pass, not through set_position.
    """
    edits: List[EditOp] = []
    by_id = _by_id(manifest)
    elements = [
        elem for elem in manifest.get("elements", []) if isinstance(elem, dict)
    ]
    frame_ids = detect_group_frame_ids(
        elements,
        structural=True,
        id_map=id_map_from_manifest(manifest),
    )
    moved: set[str] = set()

    relevant = _findings_by_category(findings, "collision/out_of_canvas")
    for finding in relevant:
        eid = finding.element_id
        if not eid or eid not in by_id or eid in moved:
            continue
        elem = by_id[eid]
        if elem.get("type") == "arrow":
            continue
        bbox = _get_bbox(elem)
        if bbox is None:
            continue
        x, y, w, h = bbox
        clamped_x = _clamp_axis(x, w, CANVAS_MAX_X)
        clamped_y = _clamp_axis(y, h, CANVAS_MAX_Y)
        new_x = x if clamped_x is None else clamped_x
        new_y = y if clamped_y is None else clamped_y
        if new_x == x and new_y == y:
            if clamped_x is None or clamped_y is None:
                logger.debug(
                    "out_of_canvas: element %r (%.0fx%.0f) cannot fit the safe "
                    "area; leaving it in place",
                    eid, w, h,
                )
            continue

        if eid in frame_ids:
            if clamped_x is None or clamped_y is None:
                logger.debug(
                    "out_of_canvas: frame %r cannot fit the safe area; refusing "
                    "to drag its members", eid,
                )
                continue
            members = [
                child for child in elements
                if child.get("id")
                and child.get("id") != eid
                and not child.get("isDeleted")
                and child.get("type") != "arrow"
                and (_get_bbox(child) is not None)
                and _bbox_inside(bbox, _get_bbox(child))  # type: ignore[arg-type]
            ]
            dx = new_x - x
            dy = new_y - y
            edits.append(
                EditOp(
                    op="set_position",
                    id=eid,
                    payload={"x": new_x, "y": new_y},
                    rationale=(
                        f"clamp container into canvas safe area "
                        f"(+{len(members)} member(s) moved by the same delta)"
                    ),
                    source="deterministic",
                )
            )
            moved.add(eid)
            for child in members:
                child_id = child["id"]
                if child_id in moved:
                    continue
                child_bbox = _get_bbox(child)
                if child_bbox is None:
                    continue
                edits.append(
                    EditOp(
                        op="set_position",
                        id=child_id,
                        payload={
                            "x": child_bbox[0] + dx,
                            "y": child_bbox[1] + dy,
                        },
                        rationale=f"follow container {eid!r} clamp (dx={dx:.0f}, dy={dy:.0f})",
                        source="deterministic",
                    )
                )
                moved.add(child_id)
            continue

        edits.append(
            EditOp(
                op="set_position",
                id=eid,
                payload={"x": new_x, "y": new_y},
                rationale="clamp into canvas safe area",
                source="deterministic",
            )
        )
        moved.add(eid)
    return edits


# ---------------------------------------------------------------------------
# Fixer 6 — fix_group_frame_zorder
# ---------------------------------------------------------------------------


def fix_group_frame_zorder(
    manifest: Dict[str, Any],
    findings: List[Finding],
    _structure: Optional[Dict[str, Any]] = None,
) -> List[EditOp]:
    """Re-assign indices so group bg paints below its children.

    Requires per-element findings from render_audit. Aggregated audit messages
    without element ids are intentionally ignored because scanning all
    backgrounds can modify unrelated groups and hide verifier regressions.
    """
    edits: List[EditOp] = []
    zorder_findings = [
        f for f in findings
        if f.category == "render_validation/audit/zorder" and f.element_id
    ]
    if not zorder_findings:
        return edits

    by_id = _by_id(manifest)
    if not any(f.element_id in by_id for f in zorder_findings):
        return edits

    repaired = repair_manifest_zorder(manifest, canvas_library="excalidraw")
    repaired_by_id = _by_id(repaired)
    reason = zorder_findings[0].message[:80]

    for eid, elem in by_id.items():
        target = repaired_by_id.get(eid)
        if not target:
            continue
        target_index = target.get("index")
        if not isinstance(target_index, str) or not target_index:
            continue
        if elem.get("index") != target_index:
            edits.append(EditOp(
                op="set_index", id=eid,
                payload={"index": target_index},
                rationale=f"repair manifest z-order: {reason}",
                source="deterministic",
            ))

    return edits


# ---------------------------------------------------------------------------
# Fixer 7 — fix_low_contrast
# ---------------------------------------------------------------------------


_DARK = "#1e1e1e"
_LIGHT = "#ffffff"
_MIN_CONTRAST_RATIO = 4.5  # WCAG AA for normal-size text


def _best_text_color(bg_rgb: Tuple[int, int, int]) -> Optional[Tuple[str, float]]:
    """Return ``(hex_color, ratio)`` — the more readable of _DARK / _LIGHT.

    Deliberately measured instead of thresholded on luminance: where the two
    candidates cross over depends on the candidates themselves (for the
    current pair it sits at L≈0.2072, nowhere near 0.5), so a hard-coded
    threshold silently rots whenever _DARK / _LIGHT change.
    """
    scored: List[Tuple[float, str]] = []
    for hex_color in (_DARK, _LIGHT):
        rgb = _hex_to_rgb(hex_color)
        if rgb is None:
            continue
        scored.append((_contrast_ratio(rgb, bg_rgb), hex_color))
    if not scored:
        return None
    ratio, hex_color = max(scored)
    return hex_color, ratio


def fix_low_contrast(
    manifest: Dict[str, Any],
    findings: List[Finding],
    _structure: Optional[Dict[str, Any]] = None,
) -> List[EditOp]:
    """For each WCAG AA contrast failure, swap text color to dark or light.

    Requires per-element findings (with element_id) so the fixer only changes
    the specific text elements that failed contrast validation. When neither
    candidate text color clears AA against a mid-tone background, the
    container background is repainted instead — emitting nothing there would
    leave the MAJOR standing forever while ``edits_applied`` stayed False.
    """
    edits: List[EditOp] = []
    contrast_findings = [
        f for f in findings
        if f.category == "render_validation/audit/contrast" and f.element_id
    ]
    if not contrast_findings:
        return edits

    by_id = _by_id(manifest)
    for f in contrast_findings:
        elem = by_id.get(f.element_id)
        if not elem:
            continue
        container_id = elem.get("containerId")
        if not container_id:
            continue
        container = by_id.get(container_id)
        if not container:
            continue
        bg = container.get("backgroundColor")
        rgb = _hex_to_rgb(bg)
        if rgb is None:
            continue
        best = _best_text_color(rgb)
        if best is None:
            continue
        target, ratio = best

        if elem.get("strokeColor") != target:
            edits.append(EditOp(
                op="set_style", id=f.element_id,
                payload={"strokeColor": target},
                rationale=(
                    f"fix contrast (ratio {ratio:.2f} vs background {bg}): "
                    f"{f.message[:60]}"
                ),
                source="deterministic",
            ))

        if ratio >= _MIN_CONTRAST_RATIO:
            continue

        # Mid-tone background: no text color reaches AA against it, so repaint
        # the container to the extreme that maximises contrast with `target`.
        fallback_bg = _LIGHT if target == _DARK else _DARK
        if container.get("backgroundColor") == fallback_bg:
            continue
        edits.append(EditOp(
            op="set_style", id=container_id,
            payload={"backgroundColor": fallback_bg},
            rationale=(
                f"background {bg} caps text contrast at {ratio:.2f} (<"
                f"{_MIN_CONTRAST_RATIO}); repaint so {target} is readable"
            ),
            source="deterministic",
        ))

    return edits


# ---------------------------------------------------------------------------
# Pre-processing — fill_schema_defaults  (mutates manifest directly)
# ---------------------------------------------------------------------------


def _stable_excalidraw_int_seed(element_id: Any, field_name: str, position: int) -> int:
    key = f"{element_id or f'element:{position}'}:{field_name}".encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()
    return (int(digest[:16], 16) % 2_000_000_000) + 1


def patch_schema_defaults(manifest: Dict[str, Any]) -> None:
    """Patch missing required Excalidraw fields in place. Always safe to call.

    Idempotent — ``setdefault`` only fills fields that are absent. Should be
    called once as pre-processing before the fixer pipeline, not per-iteration.
    """
    elements = manifest.get("elements", [])
    if not isinstance(elements, list):
        return

    for position, elem in enumerate(elements):
        if not isinstance(elem, dict):
            continue
        elem.setdefault("seed", _stable_excalidraw_int_seed(elem.get("id"), "seed", position))
        elem.setdefault("version", 1)
        elem.setdefault(
            "versionNonce",
            _stable_excalidraw_int_seed(elem.get("id"), "versionNonce", position),
        )
        elem.setdefault("isDeleted", False)
        elem.setdefault("groupIds", [])
        elem.setdefault("frameId", None)
        elem.setdefault("roundness", None)
        elem.setdefault("locked", False)
        elem.setdefault("link", None)
        elem.setdefault("updated", 0)


# ---------------------------------------------------------------------------
# Fixer 8 — fix_node_overlap
# ---------------------------------------------------------------------------


def fix_node_overlap(
    manifest: Dict[str, Any],
    findings: List[Finding],
    _structure: Optional[Dict[str, Any]] = None,
) -> List[EditOp]:
    """Resolve node overlaps using minimum translation vector (MTV).

    For each overlap finding, compute the smallest axis-aligned push that
    separates the two bounding boxes, then move the element identified by
    ``element_id`` (the "secondary" element in the pair).

    The MTV algorithm: compute overlap on both axes, push along the axis
    with smaller overlap (shortest escape route).

    All findings of one round describe the SAME unmodified manifest, so an
    element named by two overlap findings (``check_node_overlap`` puts the
    first shape of every pair in ``element_id``) used to receive two absolute
    ``set_position`` edits — applied in order, the last one silently discarded
    the first while both reported ``applied=True``. A per-round displacement
    ledger fixes that: pushes accumulate, overlap is re-tested against the
    ledger position, and each moved element emits exactly one edit.
    """
    edits: List[EditOp] = []
    by_id = _by_id(manifest)
    elements = [
        elem
        for elem in manifest.get("elements", [])
        if isinstance(elem, dict)
    ]
    frame_ids = detect_group_frame_ids(
        elements,
        structural=True,
        id_map=id_map_from_manifest(manifest),
    )

    origin: Dict[str, Tuple[float, float]] = {}
    ledger: Dict[str, Tuple[float, float]] = {}
    reasons: Dict[str, List[str]] = {}

    def _position(eid: str, fallback: Tuple[float, float]) -> Tuple[float, float]:
        if eid not in ledger:
            elem = by_id.get(eid)
            if elem is None:
                start_pos = fallback
            else:
                start_pos = (
                    float(elem.get("x", 0) or 0),
                    float(elem.get("y", 0) or 0),
                )
            origin[eid] = start_pos
            ledger[eid] = start_pos
        return ledger[eid]

    relevant = _findings_by_category(findings, "collision/node_overlap")
    for finding in relevant:
        loc = finding.location or {}
        bbox_a = loc.get("a")  # [x, y, w, h]
        bbox_b = loc.get("b")  # [x, y, w, h]
        other_id = loc.get("other_id")
        eid = finding.element_id

        if not (eid and other_id and bbox_a and bbox_b):
            continue
        if eid not in by_id:
            continue
        if eid in frame_ids or other_id in frame_ids:
            continue
        try:
            _ax, _ay, aw, ah = (float(v) for v in bbox_a)
            _bx, _by, bw, bh = (float(v) for v in bbox_b)
        except (TypeError, ValueError):
            continue

        # Positions come from the ledger so earlier pushes in this same round
        # are visible to later findings (for both sides of the pair).
        ax, ay = _position(eid, (_ax, _ay))
        bx, by_ = _position(other_id, (_bx, _by))

        # Compute overlap region.
        overlap_left = max(ax, bx)
        overlap_top = max(ay, by_)
        overlap_right = min(ax + aw, bx + bw)
        overlap_bottom = min(ay + ah, by_ + bh)

        if overlap_right <= overlap_left or overlap_bottom <= overlap_top:
            continue  # already separated by an earlier push this round

        overlap_w = overlap_right - overlap_left
        overlap_h = overlap_bottom - overlap_top

        # Push along the shorter axis (minimum translation).
        padding = 4.0
        if overlap_w < overlap_h:
            dx = overlap_w + padding
            new_x = ax - dx if (ax + aw / 2) < (bx + bw / 2) else ax + dx
            ledger[eid] = (new_x, ay)
            axis_note = f"horizontal MTV {overlap_w:.0f}px"
        else:
            dy = overlap_h + padding
            new_y = ay - dy if (ay + ah / 2) < (by_ + bh / 2) else ay + dy
            ledger[eid] = (ax, new_y)
            axis_note = f"vertical MTV {overlap_h:.0f}px"
        reasons.setdefault(eid, []).append(f"{other_id} ({axis_note})")

    for eid, (new_x, new_y) in ledger.items():
        start_x, start_y = origin.get(eid, (new_x, new_y))
        if new_x == start_x and new_y == start_y:
            continue
        if eid not in by_id:
            continue
        detail = "; ".join(reasons.get(eid, [])) or "overlap"
        edits.append(EditOp(
            op="set_position", id=eid,
            payload={"x": new_x, "y": new_y},
            rationale=f"resolve overlap with {detail}",
            source="deterministic",
        ))

    return edits


def reorder_elements_by_index(manifest: Dict[str, Any]) -> bool:
    """Sort ``manifest["elements"]`` so the array agrees with ``index``.

    ``repair_manifest_zorder`` does two things — reassign the fractional
    ``index`` **and** reorder the elements array (see
    ``render_engine/excalidraw/zorder_repair.py``). ``set_index`` can only
    carry the first half, which left the manifest asserting one paint order in
    its array and another in its indices while the audit (which compares index
    strings only) reported the z-order as repaired.

    Running this after the edits are applied restores the second half without
    giving up the EditOp audit trail. Returns True when the order changed.
    """
    elements = manifest.get("elements")
    if not isinstance(elements, list) or len(elements) < 2:
        return False

    decorated: List[Tuple[str, int, Dict[str, Any]]] = []
    for position, elem in enumerate(elements):
        if not isinstance(elem, dict):
            return False  # malformed manifest — the validator owns this case
        index = elem.get("index")
        if not isinstance(index, str) or not index:
            return False  # partial indices: any sort order would be arbitrary
        decorated.append((index, position, elem))

    ordered = [elem for _index, _position, elem in sorted(decorated, key=lambda t: (t[0], t[1]))]
    if [id(elem) for elem in ordered] == [id(elem) for elem in elements]:
        return False
    manifest["elements"] = ordered
    return True


# ---------------------------------------------------------------------------
# Aggregator — run every fixer and concatenate
# ---------------------------------------------------------------------------


_FIXERS = (
    ("dangling_bindings", fix_dangling_bindings),
    ("missing_back_refs", fix_missing_back_refs),
    ("swimlane_lane", fix_swimlane_lane_membership),
    ("group_bbox", fix_group_bbox_escape),
    ("out_of_canvas", fix_out_of_canvas),
    ("node_overlap", fix_node_overlap),
    ("group_frame_zorder", fix_group_frame_zorder),
    ("low_contrast", fix_low_contrast),
)


def run_all_deterministic_fixers(
    manifest: Dict[str, Any],
    findings: List[Finding],
    structure: Optional[Dict[str, Any]] = None,
) -> List[EditOp]:
    """Run every deterministic fixer in a fixed order; concat results.

    Order matters slightly: bindings before geometry (reduces noise on later
    passes); contrast last (textual fix independent of layout).

    Note: ``fix_schema_defaults`` is NOT in this pipeline — it mutates the
    manifest directly without EditOps and should be called as a
    pre-processing step before the fixer loop.
    """
    all_edits: List[EditOp] = []
    for name, fixer in _FIXERS:
        try:
            edits = fixer(manifest, findings, structure)
        except Exception as exc:  # noqa: BLE001
            logger.exception("deterministic fixer %s raised", name)
            raise DeterministicFixerError(name, exc) from exc
        all_edits.extend(edits)
    return all_edits


__all__ = [
    "DeterministicFixerError",
    "run_all_deterministic_fixers",
    "patch_schema_defaults",
    "reorder_elements_by_index",
    "fix_dangling_bindings",
    "fix_missing_back_refs",
    "fix_swimlane_lane_membership",
    "fix_group_bbox_escape",
    "fix_out_of_canvas",
    "fix_node_overlap",
    "fix_group_frame_zorder",
    "fix_low_contrast",
]
