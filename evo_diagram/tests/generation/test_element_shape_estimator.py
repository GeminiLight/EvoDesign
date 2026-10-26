# -*- coding: utf-8 -*-
"""Unit tests for layout-side element size hints."""

from __future__ import annotations

from evo_diagram.agentic_system.generation_stage.layout.element_shape_estimator import (
    _ICON_DEFAULT_DIM,
    _ICON_LEFT_PAD,
    _ICON_TEXT_GAP,
    estimate_element_sizes,
)


def test_node_min_width_includes_companion_icon_budget():
    styling = {
        "svc": {
            "type": "rectangle",
            "label": {"text": "Service", "fontSize": 20},
        },
        "svc:icon": {
            "type": "icon",
            "props": {"icon": "settings"},
        },
    }
    structure = {"nodes": [{"id": "svc", "label": "Service", "class": "service"}]}

    out = estimate_element_sizes(styling, structure)

    text_width = 7 * 20 * 0.6
    icon_budget = _ICON_LEFT_PAD + _ICON_DEFAULT_DIM + _ICON_TEXT_GAP
    assert out["svc"]["min_width"] == int(text_width + icon_budget)


def test_structure_node_ids_without_node_prefix_receive_size_hints():
    styling = {
        "participant_user": {
            "type": "rectangle",
            "label": {"text": "User", "fontSize": 20},
        },
        "group_shell": {
            "type": "rectangle",
            "label": {"text": "Group", "fontSize": 20},
        },
    }
    structure = {
        "nodes": [
            {"id": "participant_user", "label": "User", "class": "actor"},
        ],
        "groups": [
            {"id": "group_shell", "members": ["participant_user"]},
        ],
    }

    out = estimate_element_sizes(styling, structure)

    assert out["participant_user"]["min_width"] == int(4 * 20 * 0.6)
    assert out["participant_user"]["min_height"] == 25
    assert "min_width" not in out["group_shell"]


def test_icon_entries_are_not_estimated_as_nodes():
    styling = {
        "node:svc:icon": {
            "type": "icon",
            "props": {"icon": "settings"},
        },
    }

    out = estimate_element_sizes(styling)

    assert "min_width" not in out["node:svc:icon"]
    assert "min_height" not in out["node:svc:icon"]


def test_node_key_absent_from_structure_is_not_estimated():
    styling = {
        "node:svc": {
            "type": "rectangle",
            "label": {"text": "Service", "fontSize": 20},
        },
    }

    out = estimate_element_sizes(styling, {"nodes": []})

    assert "min_width" not in out["node:svc"]
    assert "min_height" not in out["node:svc"]


def test_underscore_icon_key_does_not_add_companion_icon_budget():
    styling = {
        "svc": {
            "type": "rectangle",
            "label": {"text": "Service", "fontSize": 20},
        },
        "svc_icon": {
            "type": "icon",
            "props": {"icon": "settings"},
        },
    }
    structure = {"nodes": [{"id": "svc", "label": "Service", "class": "service"}]}

    out = estimate_element_sizes(styling, structure)

    text_width = 7 * 20 * 0.6
    assert out["svc"]["min_width"] == int(text_width)


def test_inline_icon_payload_no_longer_adds_size_hint_budget():
    styling = {
        "svc": {
            "type": "rectangle",
            "label": {"text": "Service", "fontSize": 20},
            "props": {"icon": "settings"},
        },
    }
    structure = {"nodes": [{"id": "svc", "label": "Service", "class": "service"}]}

    out = estimate_element_sizes(styling, structure)

    text_width = 7 * 20 * 0.6
    assert out["svc"]["min_width"] == int(text_width)
