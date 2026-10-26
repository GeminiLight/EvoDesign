# -*- coding: utf-8 -*-
"""Regression tests for the unified-mode manifest normalizer.

The pipeline-mode converter (``InstantiationToExcalidrawConverter``) enforces
three render-fidelity invariants since the 2026-04 z-order fix:

1. Group frames paint behind their children.
2. A group with a standalone ``:title`` sibling does not also emit a
   centered bound-text title on the frame itself.
3. Fractional indices are zero-padded so lexicographic compare matches
   numeric compare.

The unified workflow bypasses the converter — the LLM emits Excalidraw
elements directly. These tests pin the ``normalize_excalidraw_manifest``
pass that retrofits all three invariants onto unified-mode output.

Run with::

    cd evo_diagram && pytest tests/test_unified_normalizer.py -v
"""

from __future__ import annotations

import pytest

from evo_diagram.agentic_system.render_engine.excalidraw.normalizer import (
    _LAYER_GROUP_FRAME,
    _LAYER_NODE,
    _LAYER_TEXT,
    _reassign_indices,
    normalize_excalidraw_manifest,
)
from evo_diagram.agentic_system.render_engine.shared.normalization import (
    deduplicate_group_titles,
    detect_group_frame_ids,
)


# ----------------------------------------------------------------------------
# Fixtures — hand-crafted mini-scenes that mirror common unified outputs
# ----------------------------------------------------------------------------


def _rect(id_, x, y, w, h, **extra):
    base = {
        "id": id_,
        "type": "rectangle",
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "strokeColor": "#1e1e1e",
        "backgroundColor": "#ffffff",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "groupIds": [],
        "boundElements": [],
        "frameId": None,
        "index": "a0",
        "roundness": None,
        "seed": 1,
        "version": 1,
        "versionNonce": 1,
        "isDeleted": False,
        "link": None,
        "locked": False,
    }
    base.update(extra)
    return base


def _text(id_, x, y, text, **extra):
    base = {
        "id": id_,
        "type": "text",
        "x": x,
        "y": y,
        "width": max(60, len(text) * 12),
        "height": 24,
        "text": text,
        "originalText": text,
        "fontSize": 20,
        "fontFamily": 2,
        "textAlign": "left",
        "verticalAlign": "top",
        "containerId": None,
        "strokeColor": "#1e1e1e",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "groupIds": [],
        "boundElements": [],
        "frameId": None,
        "index": "a0",
        "roundness": None,
        "seed": 1,
        "version": 1,
        "versionNonce": 1,
        "isDeleted": False,
        "link": None,
        "locked": False,
        "autoResize": True,
        "lineHeight": 1.25,
    }
    base.update(extra)
    return base


def _manifest(elements):
    return {
        "type": "excalidraw/clipboard",
        "elements": elements,
        "files": {},
        "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None},
    }


# ----------------------------------------------------------------------------
# Frame detection
# ----------------------------------------------------------------------------


def test_frame_detection_via_explicit_id_prefix():
    elements = [
        _rect("g_box", 0, 0, 300, 200),
        _rect("n_a", 20, 20, 80, 40),
    ]
    assert detect_group_frame_ids(elements, structural=True) == {"g_box"}


def test_frame_detection_via_background_suffix():
    elements = [
        _rect("lane:background", 0, 0, 400, 600),
        _rect("n_a", 20, 20, 80, 40),
    ]
    assert detect_group_frame_ids(elements, structural=True) == {"lane:background"}


def test_frame_detection_via_is_group_flag():
    elements = [
        _rect("frame-xyz-123", 0, 0, 400, 300, is_group=True),
        _rect("n_a", 20, 20, 80, 40),
    ]
    assert detect_group_frame_ids(elements, structural=True) == {"frame-xyz-123"}


def test_frame_detection_via_containment_heuristic():
    # Unified-style LLM with opaque ids: detect via groupIds + bbox containment.
    elements = [
        _rect("rect-1", 0, 0, 400, 300, groupIds=["grp-a"]),
        _rect("rect-2", 20, 20, 80, 40, groupIds=["grp-a"]),
        _rect("rect-3", 120, 20, 80, 40, groupIds=["grp-a"]),
    ]
    assert detect_group_frame_ids(elements, structural=True) == {"rect-1"}


def test_frame_detection_rejects_single_child_shape():
    # A regular node with one bound-text neighbour must NOT be classified
    # as a frame.
    elements = [
        _rect("n_a", 0, 0, 160, 60, groupIds=["grp-a"]),
        _text("t_a", 40, 20, "A", groupIds=["grp-a"], containerId="n_a"),
    ]
    assert detect_group_frame_ids(elements, structural=True) == set()


# ----------------------------------------------------------------------------
# Duplicate title dedup
# ----------------------------------------------------------------------------


def test_deduplicate_group_titles_removes_bound_copy_when_standalone_matches():
    frame_id = "g_box"
    elements = [
        _rect(frame_id, 0, 0, 300, 300, groupIds=["grp-a"],
              boundElements=[{"type": "text", "id": "bt_box"}]),
        _text("bt_box", 150, 150, "Empathize", containerId=frame_id,
              groupIds=["grp-a"], textAlign="center", verticalAlign="middle"),
        _text("st_box", 10, 10, "Empathize", containerId=None,
              groupIds=["grp-a"], textAlign="left", verticalAlign="top"),
    ]
    filtered = deduplicate_group_titles(elements, {frame_id})
    assert {elem["id"] for elem in filtered} == {"g_box", "st_box"}
    assert elements[0].get("boundElements") == []


def test_deduplicate_group_titles_keeps_bound_title_when_text_differs():
    frame_id = "g_box"
    elements = [
        _rect(frame_id, 0, 0, 300, 300, groupIds=["grp-a"]),
        _text("bt_box", 150, 150, "Empathize", containerId=frame_id,
              groupIds=["grp-a"]),
        _text("st_box", 10, 10, "Define", containerId=None,
              groupIds=["grp-a"]),
    ]
    assert deduplicate_group_titles(elements, {frame_id}) is elements


def test_deduplicate_group_titles_uses_bbox_containment_without_shared_groups():
    # Even if groupIds differ, if a standalone title sits inside the frame,
    # treat it as a header duplicate.
    frame_id = "g_box"
    elements = [
        _rect(frame_id, 0, 0, 300, 300),
        _text("bt_box", 150, 150, "Team", containerId=frame_id),
        _text("st_box", 10, 10, "Team", containerId=None),
    ]
    filtered = deduplicate_group_titles(elements, {frame_id})
    assert {elem["id"] for elem in filtered} == {"g_box", "st_box"}


# ----------------------------------------------------------------------------
# Index reassignment — zero-padded lexicographic sort
# ----------------------------------------------------------------------------


def test_reassign_puts_group_frames_before_nodes():
    frame_id = "g_box"
    elements = [
        _rect("n_a", 20, 20, 80, 40),
        _rect("n_b", 120, 20, 80, 40),
        _rect(frame_id, 0, 0, 300, 200),
    ]
    ordered = _reassign_indices(elements, {frame_id})
    idx = {e["id"]: e["index"] for e in ordered}
    assert idx[frame_id] < idx["n_a"] < idx["n_b"]
    # Zero-padded format so string compare == numeric compare.
    assert all(len(v) == 6 and v.startswith("e") for v in idx.values())


def test_reassign_puts_text_on_top():
    frame_id = "g_box"
    elements = [
        _text("t_top", 10, 10, "Header"),
        _rect(frame_id, 0, 0, 300, 200),
        _rect("n_a", 20, 40, 80, 40),
    ]
    ordered = _reassign_indices(elements, {frame_id})
    idx = {e["id"]: e["index"] for e in ordered}
    assert idx[frame_id] < idx["n_a"] < idx["t_top"]


def test_explicit_zindex_overrides_layer_heuristic():
    frame_id = "g_deco"
    # zIndex=250 should push the decorative frame ABOVE the node (node layer is 200).
    elements = [
        _rect(frame_id, 0, 0, 300, 200, zIndex=250),
        _rect("n_under", 20, 20, 80, 40),
    ]
    ordered = _reassign_indices(elements, {frame_id})
    idx = {e["id"]: e["index"] for e in ordered}
    assert idx[frame_id] > idx["n_under"]


def test_index_lexicographic_compare_matches_numeric_after_10_elements():
    # Before the zero-padding fix, "a10" sorted BEFORE "a2" lex-wise.
    # Feed 12 nodes and assert lex order preserves numeric order.
    elements = [
        _rect(f"n_{i}", i * 10, 0, 20, 20)
        for i in range(12)
    ]
    ordered = _reassign_indices(elements, set())
    indices = [e["index"] for e in ordered]
    assert sorted(indices) == indices  # lexicographic order is already numeric order


# ----------------------------------------------------------------------------
# End-to-end normalizer — full flow
# ----------------------------------------------------------------------------


def test_normalize_full_flow_on_unified_like_manifest():
    """Mirrors the failure shape: LLM emits group AFTER children, emits both
    centered bound-text title and top-left standalone title. After
    normalization we get a single standalone title and group behind children.
    """
    frame_id = "g_empathize"
    manifest = _manifest([
        # Children first
        _rect("n_obs", 20, 50, 100, 40, groupIds=["grp-a"]),
        _rect("n_lst", 140, 50, 100, 40, groupIds=["grp-a"]),
        # Group frame LAST with a centered bound title
        _rect(frame_id, 0, 0, 260, 120, groupIds=["grp-a"],
              boundElements=[{"type": "text", "id": "bt_emp"}]),
        # Bound center title
        _text("bt_emp", 90, 50, "Empathize", containerId=frame_id,
              groupIds=["grp-a"], textAlign="center", verticalAlign="middle"),
        # Top-left standalone title
        _text("st_emp", 10, 10, "Empathize", containerId=None,
              groupIds=["grp-a"], textAlign="left", verticalAlign="top"),
    ])

    normalize_excalidraw_manifest(manifest)

    elements = manifest["elements"]
    ids = [e["id"] for e in elements]
    # Bound-center duplicate dropped
    assert "bt_emp" not in ids
    # Frame's boundElements reference cleaned up
    frame = next(e for e in elements if e["id"] == frame_id)
    assert frame.get("boundElements") == []
    # Exactly one "Empathize" text remains, and it's the standalone
    emp_texts = [e for e in elements if e.get("type") == "text" and e.get("text") == "Empathize"]
    assert len(emp_texts) == 1
    assert emp_texts[0]["containerId"] is None
    # z-order: frame BEFORE children BEFORE standalone title
    idx = {e["id"]: e["index"] for e in elements}
    assert idx[frame_id] < idx["n_obs"] < idx["st_emp"]
    assert idx[frame_id] < idx["n_lst"] < idx["st_emp"]


def test_normalize_is_idempotent():
    """Applying the normalizer twice must produce the same result as once."""
    frame_id = "g_box"
    manifest = _manifest([
        _rect("n_a", 20, 20, 80, 40, groupIds=["grp-a"]),
        _rect(frame_id, 0, 0, 200, 100, groupIds=["grp-a"]),
    ])

    normalize_excalidraw_manifest(manifest)
    first_indices = {e["id"]: e["index"] for e in manifest["elements"]}

    normalize_excalidraw_manifest(manifest)
    second_indices = {e["id"]: e["index"] for e in manifest["elements"]}

    assert first_indices == second_indices


def test_normalize_handles_empty_and_malformed_input():
    # Should NOT raise
    assert normalize_excalidraw_manifest(None) is None
    assert normalize_excalidraw_manifest({}) == {}
    assert normalize_excalidraw_manifest({"elements": []}) == {"elements": []}
    assert normalize_excalidraw_manifest({"elements": "not-a-list"}) == {"elements": "not-a-list"}


def test_normalize_skips_when_disabled():
    frame_id = "g_box"
    manifest = _manifest([
        _rect(frame_id, 0, 0, 300, 300,
              boundElements=[{"type": "text", "id": "bt"}]),
        _text("bt", 150, 150, "Team", containerId=frame_id),
        _text("st", 10, 10, "Team"),
    ])

    # Dedup disabled: duplicate title should remain.
    normalize_excalidraw_manifest(manifest, dedup_titles=False)
    ids = [e["id"] for e in manifest["elements"]]
    assert "bt" in ids


def test_normalize_safe_on_pipeline_mode_output():
    """Running the normalizer AFTER the pipeline-mode converter must not
    reorder or damage an already-correct manifest. This lets us apply the
    normalizer unconditionally as defense-in-depth later without breaking
    the pipeline path."""
    # Simulate pipeline output: frame already at index a00000, node at a00001
    manifest = _manifest([
        _rect("g_box", 0, 0, 300, 200, index="a00000"),
        _rect("n_a", 20, 20, 80, 40, index="a00001"),
    ])

    normalize_excalidraw_manifest(manifest)

    idx = {e["id"]: e["index"] for e in manifest["elements"]}
    assert idx["g_box"] < idx["n_a"]
