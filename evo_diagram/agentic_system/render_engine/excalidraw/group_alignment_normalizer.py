# -*- coding: utf-8 -*-
"""Preserve layout-stage group alignment intent after group fitting."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from evo_diagram.agentic_system.common.semantic_ids import (
    BACKGROUND_SUFFIX,
    ICON_SUFFIX,
    TITLE_SUFFIX,
    companion_id,
    id_map_from_manifest,
)
from ..shared.normalization import base_id


_SIZE_TOL = 2.0
_POSITION_TOL = 40.0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dim(data: Dict[str, Any], key: str) -> float:
    if key == "width":
        return _num(data.get("width", data.get("w")))
    if key == "height":
        return _num(data.get("height", data.get("h")))
    return _num(data.get(key))


def _is_group_candidate(element_id: str, layout: Dict[str, Any]) -> bool:
    if (
        not isinstance(element_id, str)
        or element_id.endswith(TITLE_SUFFIX)
        or element_id.endswith(ICON_SUFFIX)
    ):
        return False
    if element_id.endswith(BACKGROUND_SUFFIX):
        return True
    if element_id.startswith("group_") or element_id.startswith("g_"):
        return True
    return companion_id(base_id(element_id), TITLE_SUFFIX) in layout


def _group_layout_records(layout_instantiation: Dict[str, Any], id_map: Dict[str, str]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for semantic_id, data in layout_instantiation.items():
        if not isinstance(semantic_id, str) or not isinstance(data, dict):
            continue
        if not _is_group_candidate(semantic_id, layout_instantiation):
            continue
        render_id = id_map.get(semantic_id)
        if not render_id:
            continue
        w = _dim(data, "width")
        h = _dim(data, "height")
        if w <= 0 or h <= 0:
            continue
        records.append({
            "semantic_id": semantic_id,
            "render_id": render_id,
            "x": _dim(data, "x"),
            "y": _dim(data, "y"),
            "width": w,
            "height": h,
        })
    return records


def _cluster_equal_width(records: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    clusters: List[List[Dict[str, Any]]] = []
    for record in sorted(records, key=lambda r: (round(r["x"] / _POSITION_TOL), r["width"], r["y"])):
        placed = False
        for cluster in clusters:
            anchor = cluster[0]
            if abs(record["x"] - anchor["x"]) <= _POSITION_TOL and abs(record["width"] - anchor["width"]) <= _SIZE_TOL:
                cluster.append(record)
                placed = True
                break
        if not placed:
            clusters.append([record])
    return [cluster for cluster in clusters if len(cluster) >= 2]


def _cluster_equal_height(records: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    clusters: List[List[Dict[str, Any]]] = []
    for record in sorted(records, key=lambda r: (round(r["y"] / _POSITION_TOL), r["height"], r["x"])):
        placed = False
        for cluster in clusters:
            anchor = cluster[0]
            if abs(record["y"] - anchor["y"]) <= _POSITION_TOL and abs(record["height"] - anchor["height"]) <= _SIZE_TOL:
                cluster.append(record)
                placed = True
                break
        if not placed:
            clusters.append([record])
    return [cluster for cluster in clusters if len(cluster) >= 2]


def preserve_group_alignment_intent(
    manifest: Dict[str, Any],
    layout_instantiation: Dict[str, Any],
) -> Dict[str, Any]:
    """Restore equal-width/equal-height group relations expressed by layout.

    The layout LLM often communicates intent by assigning several group
    backdrops exactly the same width or height. Later local fitting can expand
    one group to contain an enlarged child. This pass propagates that expansion
    across the original equal-size cluster, preserving the layout intent while
    still keeping every group large enough for its children.
    """
    manifest = deepcopy(manifest)
    elements = manifest.get("elements") or []
    id_map = id_map_from_manifest(manifest)
    by_id = {
        e["id"]: e
        for e in elements
        if isinstance(e, dict) and e.get("id")
    }
    records = _group_layout_records(layout_instantiation or {}, id_map)
    if not records:
        return manifest

    for cluster in _cluster_equal_width(records):
        elems = [by_id[r["render_id"]] for r in cluster if r["render_id"] in by_id]
        if len(elems) < 2:
            continue
        common_x = min(_num(e.get("x")) for e in elems)
        common_right = max(_num(e.get("x")) + _num(e.get("width")) for e in elems)
        common_w = common_right - common_x
        for elem in elems:
            elem["x"] = common_x
            elem["width"] = common_w

    for cluster in _cluster_equal_height(records):
        elems = [by_id[r["render_id"]] for r in cluster if r["render_id"] in by_id]
        if len(elems) < 2:
            continue
        common_y = min(_num(e.get("y")) for e in elems)
        common_bottom = max(_num(e.get("y")) + _num(e.get("height")) for e in elems)
        common_h = common_bottom - common_y
        for elem in elems:
            elem["y"] = common_y
            elem["height"] = common_h

    manifest["elements"] = elements
    return manifest
