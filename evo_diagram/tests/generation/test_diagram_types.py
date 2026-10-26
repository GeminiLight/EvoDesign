from __future__ import annotations

from pathlib import Path

import pytest

from evo_diagram.agentic_system.common import domain_knowledge_loader
from evo_diagram.agentic_system.common.diagram_types import (
    TYPE_PATTERNS_DIR,
    DiagramTypeValidationError,
    get_supported_diagram_types,
    is_supported_diagram_type,
    normalize_diagram_type,
    normalize_supported_diagram_type,
)


def _digest_types() -> set[str]:
    digest_path = TYPE_PATTERNS_DIR.parent / "diagram_type_digest.md"
    types: set[str] = set()
    for line in digest_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells or cells[0] in {"diagram_type", "---"}:
            continue
        if cells[0] and all(ch.islower() or ch.isdigit() or ch == "_" for ch in cells[0]):
            types.add(cells[0])
    return types


def test_supported_diagram_type_registry_matches_prompt_assets():
    pattern_types = {path.stem for path in Path(TYPE_PATTERNS_DIR).glob("*.md")}
    supported_types = set(get_supported_diagram_types())

    assert len(supported_types) == 22
    assert supported_types == pattern_types
    assert supported_types == _digest_types()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("flow chart", "flowchart"),
        ("class", "class_diagram"),
        ("uml class diagram", "class_diagram"),
        ("swimlane diagram", "swimlane"),
        ("state machine", "state_diagram"),
    ],
)
def test_supported_diagram_type_aliases_canonicalize(raw, expected):
    assert normalize_diagram_type(raw) == expected
    assert normalize_supported_diagram_type(raw) == expected
    assert is_supported_diagram_type(raw) is True


def test_unknown_diagram_type_is_only_allowed_by_non_strict_normalizer():
    assert normalize_diagram_type("made up chart") == "made_up_chart"
    assert is_supported_diagram_type("made up chart") is False

    with pytest.raises(DiagramTypeValidationError, match="Unsupported diagram_type"):
        normalize_supported_diagram_type("made up chart")


def test_domain_knowledge_loader_uses_shared_diagram_type_aliases():
    assert domain_knowledge_loader.normalize_diagram_type("flow") == "flowchart"

    context = domain_knowledge_loader.build_diagram_context("flow")

    assert "Diagram family: flowchart" in context
