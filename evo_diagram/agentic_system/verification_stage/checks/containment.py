"""Containment checks: group bbox vs children, swimlane lane membership.

Two related but distinct checks:

1. **group_bbox_contains_children** — for every child of a group, the
   shape's full bounding box must lie within that group's bbox (with a
   small tolerance). When ``structure.groups[].members`` is available,
   explicit membership is used; otherwise falls back to centroid-based
   geometric inference (smallest-containing group wins when groups nest).

2. **swimlane_lane_membership** — for ``chart_type == "swimlane"``, every
   non-lane shape MUST have its centroid land inside exactly one lane,
   and its full y-band must fit within that lane's y-band. Out-of-band
   nodes (the regression that motivated adding ``swimlane`` to
   ``DAGRE_SKIP_TYPES``) and "escaped all lanes" are both MAJOR findings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple

from evo_diagram.agentic_system.common.semantic_ids import (
    group_frame_render_id,
    id_map_from_manifest,
    resolve_group_id_map,
    reverse_base_id_map,
)
from .finding import Finding, Severity


_BBOX_TOLERANCE_PX = 4   # padding allowance for full-bbox containment
_CENTROID_TOLERANCE_PX = 2

_BBox = Tuple[float, float, float, float]   # (x, y, w, h)


@dataclass(frozen=True)
class _MembershipContext:
    elements: List[Any]
    groups: List[Dict[str, Any]]
    groups_by_id: Dict[str, Dict[str, Any]]
    background_ids: set
    title_ids: set
    reverse_id_map: Dict[str, str]
    explicit_member_to_group: Dict[str, str]

    @property
    def use_explicit(self) -> bool:
        return bool(self.explicit_member_to_group)


def _get_bbox(elem: Dict[str, Any]) -> Optional[_BBox]:
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


def _centroid(bbox: _BBox) -> Tuple[float, float]:
    x, y, w, h = bbox
    return (x + w / 2.0, y + h / 2.0)


def _bbox_area(bbox: _BBox) -> float:
    _, _, w, h = bbox
    return w * h


def _point_in_bbox(point: Tuple[float, float], bbox: _BBox, tol: float = _CENTROID_TOLERANCE_PX) -> bool:
    px, py = point
    x, y, w, h = bbox
    return (x - tol) <= px <= (x + w + tol) and (y - tol) <= py <= (y + h + tol)


def _bbox_contains(parent: _BBox, child: _BBox, tol: float = _BBOX_TOLERANCE_PX) -> bool:
    px, py, pw, ph = parent
    cx, cy, cw, ch = child
    return (
        cx >= px - tol
        and cy >= py - tol
        and cx + cw <= px + pw + tol
        and cy + ch <= py + ph + tol
    )


def _y_band_contains(parent: _BBox, child: _BBox, tol: float = _BBOX_TOLERANCE_PX) -> bool:
    """True iff child's full y-band is inside parent's y-band."""
    _, py, _, ph = parent
    _, cy, _, ch = child
    return cy >= py - tol and cy + ch <= py + ph + tol


# ---------------------------------------------------------------------------
# Group / lane registry — derived from _meta.id_map naming convention.
# ---------------------------------------------------------------------------


def _collect_groups(
    manifest: Dict[str, Any],
    structure: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], set, set]:
    """Walk ``_meta.id_map`` and return:

    - ``groups``: list of dicts with keys ``id``, ``bg_id``, ``bg_bbox``,
      ``title_id`` (optional). Sorted by bg area (smallest first), so
      "smallest containing group" lookups are linear.
    - ``background_ids``: set of element ids that are group backgrounds.
    - ``title_ids``: set of element ids that are group titles.

    Recognises both naming conventions seen in EvoDiagram's renderer:
    ``<group>:background`` and ``<group>:title`` (also ``<group>:label``,
    used by some pipeline versions for the lane title).
    """
    elements = manifest.get("elements", [])
    if not isinstance(elements, list):
        return [], set(), set()

    by_id: Dict[str, Dict[str, Any]] = {
        elem.get("id"): elem
        for elem in elements
        if isinstance(elem, dict) and elem.get("id") and not elem.get("isDeleted")
    }

    idm = id_map_from_manifest(manifest)
    group_id_map = resolve_group_id_map(idm)
    bg_for = dict(group_id_map.background_by_group)
    title_for = group_id_map.title_by_group

    # When Structure is available, a semantic group may map directly to the
    # frame element instead of only using the "<group>:background" companion
    # id convention.
    if isinstance(structure, dict):
        for group in structure.get("groups") or []:
            if not isinstance(group, dict):
                continue
            group_id = group.get("id")
            frame_id = group_frame_render_id(idm, group_id)
            if isinstance(group_id, str) and frame_id:
                bg_for.setdefault(group_id, frame_id)

    groups: List[Dict[str, Any]] = []
    for group_id, bg_id in bg_for.items():
        bg_elem = by_id.get(bg_id)
        if not bg_elem:
            continue
        bg_bbox = _get_bbox(bg_elem)
        if bg_bbox is None:
            continue
        groups.append(
            {
                "id": group_id,
                "bg_id": bg_id,
                "bg_bbox": bg_bbox,
                "title_id": title_for.get(group_id),
            }
        )

    # Smallest first — the first match in `_assign_centroid_to_group` is
    # therefore the smallest containing group, which is the canonical
    # parent for nested groups.
    groups.sort(key=lambda g: _bbox_area(g["bg_bbox"]))

    return groups, set(bg_for.values()), set(title_for.values())


def _assign_centroid_to_group(
    centroid: Tuple[float, float],
    groups: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Pick the smallest group whose bg contains the centroid (or None)."""
    for g in groups:   # already sorted smallest-first
        if _point_in_bbox(centroid, g["bg_bbox"]):
            return g
    return None


def build_explicit_member_map(
    structure: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    """Build element_id → group_id mapping from structure.groups[].members.

    Returns an empty dict when the structure lacks explicit membership data.
    The mapping uses manifest element IDs (the values in ``_meta.id_map``),
    not the semantic node IDs from the structure.  We rely on the id_map
    being available in the manifest to translate between the two.
    """
    if not isinstance(structure, dict):
        return {}

    groups = structure.get("groups")
    if not isinstance(groups, list):
        return {}

    member_to_group: Dict[str, str] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        gid = group.get("id")
        members = group.get("members")
        if not gid or not isinstance(members, list):
            continue
        for mid in members:
            if isinstance(mid, str):
                member_to_group[mid] = gid
    return member_to_group


def _is_candidate_child(
    elem: Dict[str, Any],
    *,
    background_ids: set,
    title_ids: set,
) -> bool:
    """Should this element be tested against a group bbox?

    Excluded:
      - arrows (their bbox is just the routing rectangle, not a 'shape')
      - group backgrounds (they ARE the parent)
      - registered group titles (they sit on the corner by convention)
      - bound text labels (they ride along their containerId; the container
        carries the binding)
      - lines / freedraw / images without a meaningful enclosure semantics
    """
    eid = elem.get("id")
    if not eid:
        return False
    if elem.get("isDeleted"):
        return False
    etype = elem.get("type")
    if etype in {"arrow", "freedraw", "line"}:
        return False
    if eid in background_ids or eid in title_ids:
        return False
    if etype == "text" and elem.get("containerId"):
        return False
    return True


def _membership_context(
    manifest: Dict[str, Any],
    structure: Optional[Dict[str, Any]],
) -> Optional[_MembershipContext]:
    groups, background_ids, title_ids = _collect_groups(manifest, structure)
    if not groups:
        return None

    elements = manifest.get("elements", [])
    if not isinstance(elements, list):
        return None

    idm = id_map_from_manifest(manifest)
    reverse_ids = reverse_base_id_map(idm)
    explicit_members = build_explicit_member_map(structure)
    groups_by_id = {group["id"]: group for group in groups}
    # Concept-map sections are created from branch ownership, not from the
    # optional structure.groups list. Geometry-based inference would silently
    # reassign a node after a refiner moves its original frame away.
    nodes = (structure or {}).get("nodes") or []
    branch_groups = {
        node.get("branch_id"): node["id"]
        for node in nodes
        if isinstance(node, dict)
        and node.get("class") == "branch_anchor"
        and node.get("branch_id")
        and node.get("id") in groups_by_id
    }
    for node in nodes:
        if not isinstance(node, dict):
            continue
        group_id = branch_groups.get(node.get("branch_id"))
        if group_id and node.get("id"):
            explicit_members.setdefault(node["id"], group_id)
    frame_groups = {group["bg_id"]: group["id"] for group in groups}
    for element in elements:
        if not isinstance(element, dict) or element.get("id") not in frame_groups:
            continue
        for member_id in (element.get("meta") or {}).get("memberIds", []):
            explicit_members.setdefault(
                reverse_ids.get(member_id, member_id), frame_groups[element["id"]],
            )
    return _MembershipContext(
        elements=elements,
        groups=groups,
        groups_by_id=groups_by_id,
        background_ids=background_ids,
        title_ids=title_ids,
        reverse_id_map=reverse_ids,
        explicit_member_to_group=explicit_members,
    )


def _iter_candidate_children(
    context: _MembershipContext,
) -> Iterator[Tuple[Dict[str, Any], _BBox]]:
    for elem in context.elements:
        if not isinstance(elem, dict):
            continue
        if not _is_candidate_child(
            elem,
            background_ids=context.background_ids,
            title_ids=context.title_ids,
        ):
            continue
        elem_bbox = _get_bbox(elem)
        if elem_bbox is None:
            continue
        yield elem, elem_bbox


def _resolve_parent_group(
    elem: Dict[str, Any],
    elem_bbox: _BBox,
    context: _MembershipContext,
) -> Optional[Dict[str, Any]]:
    if context.use_explicit:
        eid = elem.get("id")
        semantic_id = context.reverse_id_map.get(eid, eid)
        group_id = context.explicit_member_to_group.get(semantic_id)
        return context.groups_by_id.get(group_id) if group_id else None
    return _assign_centroid_to_group(_centroid(elem_bbox), context.groups)


# ---------------------------------------------------------------------------
# Public checks
# ---------------------------------------------------------------------------


def check_group_bbox_contains_children(
    manifest: Dict[str, Any],
    structure: Optional[Dict[str, Any]] = None,
) -> List[Finding]:
    """Generic group containment — used for every chart_type EXCEPT swimlane.

    For swimlane the dedicated ``check_swimlane_lane_membership`` covers it
    with a more specific message and an additional 'escaped all lanes' case.

    When ``structure.groups[].members`` provides explicit membership, uses
    that for assignment. Otherwise falls back to centroid-based inference.
    """
    findings: List[Finding] = []
    if not isinstance(manifest, dict):
        return findings

    chart_type = (
        structure.get("chart_type")
        if isinstance(structure, dict)
        else None
    )
    if chart_type == "swimlane":
        # Delegate to the specialised check to avoid double-counting.
        return findings

    context = _membership_context(manifest, structure)
    if context is None:
        return findings

    for elem, elem_bbox in _iter_candidate_children(context):
        parent = _resolve_parent_group(elem, elem_bbox, context)

        if parent is None:
            # Floating element outside all groups — legal for many chart
            # types (e.g. canvas-level title text). No finding.
            continue

        if not _bbox_contains(parent["bg_bbox"], elem_bbox):
            px, py, pw, ph = parent["bg_bbox"]
            cx, cy, cw, ch = elem_bbox
            findings.append(
                Finding(
                    category="containment/group_bbox",
                    severity=Severity.MAJOR,
                    message=(
                        f"child {elem.get('id')!r} bbox=({cx:.0f},{cy:.0f},"
                        f"{cw:.0f}x{ch:.0f}) escapes group {parent['id']!r} "
                        f"bbox=({px:.0f},{py:.0f},{pw:.0f}x{ph:.0f})."
                    ),
                    element_id=elem.get("id"),
                    location={
                        "child": {"x": cx, "y": cy, "w": cw, "h": ch},
                        "group": {"x": px, "y": py, "w": pw, "h": ph},
                        "group_id": parent["id"],
                    },
                )
            )

    return findings


def check_swimlane_lane_membership(
    manifest: Dict[str, Any],
    structure: Optional[Dict[str, Any]] = None,
) -> List[Finding]:
    """For swimlane charts, every node MUST sit inside exactly one lane y-band.

    Two failure modes — both MAJOR:
      1. centroid not in any lane → "escaped all lanes"
      2. centroid in lane X, but full y-band crosses lane X boundary →
         "y-band escapes lane band"

    X-axis containment is NOT enforced — by EvoDiagram convention lanes
    span the canvas width, so x is process order, not a lane attribute.

    When ``structure.groups[].members`` provides explicit membership, uses
    that for lane assignment. Otherwise falls back to centroid inference.
    """
    findings: List[Finding] = []
    if not isinstance(manifest, dict):
        return findings

    chart_type = (
        structure.get("chart_type")
        if isinstance(structure, dict)
        else None
    )
    if chart_type != "swimlane":
        return findings

    context = _membership_context(manifest, structure)
    if context is None:
        return findings

    for elem, elem_bbox in _iter_candidate_children(context):
        eid = elem.get("id")
        cx, cy = _centroid(elem_bbox)

        lane = _resolve_parent_group(elem, elem_bbox, context)

        if lane is None:
            findings.append(
                Finding(
                    category="containment/swimlane_lane",
                    severity=Severity.MAJOR,
                    message=(
                        f"node {eid!r} centroid=({cx:.0f},{cy:.0f}) is not "
                        "inside any lane — node has escaped the lane system."
                    ),
                    element_id=eid,
                    location={
                        "node": dict(zip("xywh", elem_bbox)),
                        "centroid": {"x": cx, "y": cy},
                    },
                )
            )
            continue

        if not _y_band_contains(lane["bg_bbox"], elem_bbox):
            lx, ly, lw, lh = lane["bg_bbox"]
            nx, ny, nw, nh = elem_bbox
            findings.append(
                Finding(
                    category="containment/swimlane_lane",
                    severity=Severity.MAJOR,
                    message=(
                        f"node {eid!r} y-band=[{ny:.0f},{ny + nh:.0f}] crosses "
                        f"lane {lane['id']!r} band [{ly:.0f},{ly + lh:.0f}]."
                    ),
                    element_id=eid,
                    location={
                        "node": {"x": nx, "y": ny, "w": nw, "h": nh},
                        "lane": {"x": lx, "y": ly, "w": lw, "h": lh},
                        "lane_id": lane["id"],
                    },
                )
            )

    return findings


__all__ = [
    "check_group_bbox_contains_children",
    "check_swimlane_lane_membership",
    "build_explicit_member_map",
]
