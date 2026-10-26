#!/usr/bin/env python3
"""Regression metrics for the render pipeline's fidelity.

Walks selected samples and re-runs the current rendering facade
(``canvas_environment.render_manifest``) from structure + layout inputs.  It
emits per-sample metrics so render regressions can be detected without
eyeballing PNGs.

Metrics:
    - structure_edge_count vs rendered_arrow_count
    - standalone_text_count vs empty_text_count
    - edge styling coverage (strokeColor applied)
    - layout self-audit flags surviving from the Layout agent
    - audit warnings emitted during render

Exit status is 0 if every sample meets the thresholds; otherwise 1 so this
can be wired into CI later.

Usage::

    python -m evo_diagram.scripts.regression_render
    python -m evo_diagram.scripts.regression_render --samples-root path/to/results
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure the package root (..) is on sys.path.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evo_diagram.canvas_environment import (
    audit_layout_instantiation,
    audit_manifest,
    render_manifest,
)
from evo_diagram.utils.path_manager import safe_path_segment

DEFAULT_SAMPLE_NAMES = [
    "swimlane_20251205_094249_164",
    "architecture_20251204_203338_92",
    "concept_20251205_025801_50",
]


def _default_samples_root() -> Path:
    from evo_diagram.core.experiment import get_experiment_root

    return get_experiment_root() / "outputs" / "evodiagram" / "evodiagram"

# Thresholds that flip the exit status to non-zero.
ARROW_COVERAGE_MIN = 0.8
EMPTY_TEXT_MAX_RATIO = 0.05


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _strip_specification(instantiation: Dict[str, Any]) -> Dict[str, Any]:
    """Return the element-id-keyed dict without the spec payload."""
    return {k: v for k, v in instantiation.items() if k != "specification"}


def _resolve_sample_dir(root: Path, sample_name: str, model: Optional[str]) -> Path:
    safe_sample = safe_path_segment(sample_name, field_name="sample name")
    direct = root / safe_sample
    if direct.exists():
        return direct
    if model:
        safe_model = safe_path_segment(model, field_name="model name")
        return root / safe_model / safe_sample
    if root.exists():
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            candidate = child / safe_sample
            if candidate.exists():
                return candidate
    return direct


def _audit_sample(sample_dir: Path) -> Optional[Dict[str, Any]]:
    structure_path = sample_dir / "1_structure" / "structure_instantiation.json"
    layout_path = sample_dir / "3_layout" / "layout_instantiation.json"
    if not structure_path.exists() or not layout_path.exists():
        return None

    structure_raw = _load_json(structure_path)
    layout_raw = _load_json(layout_path)
    structure = _strip_specification(structure_raw)
    layout = _strip_specification(layout_raw)

    layout_audit = audit_layout_instantiation(layout, structure)
    with tempfile.TemporaryDirectory(prefix="evodiagram-regression-render-") as tmp_dir:
        render_result = render_manifest(
            layout_instantiation=layout,
            structure_instantiation=structure,
            canvas_library="excalidraw",
            output_dir=tmp_dir,
        )
        manifest = render_result.manifest

    manifest_audit = audit_manifest(
        manifest,
        structure_instantiation=structure,
        canvas_library="excalidraw",
    ).warnings

    elements = manifest["elements"]
    types = Counter(e["type"] for e in elements)

    standalone_text = [
        e for e in elements if e["type"] == "text" and not e.get("containerId")
    ]
    empty_text = [e for e in standalone_text if not e.get("text")]

    arrows = [e for e in elements if e["type"] == "arrow"]
    styled_arrows = [a for a in arrows if a.get("strokeColor") != "#1e1e1e"]

    structure_edges = structure.get("edges", []) or []
    layout_spec = layout_raw.get("specification", {}) or {}
    layout_self_audit = layout_spec.get("layout_self_audit", {})

    return {
        "sample": sample_dir.name,
        "element_types": dict(types),
        "structure_edges": len(structure_edges),
        "rendered_arrows": len(arrows),
        "arrow_coverage": (
            len(arrows) / len(structure_edges) if structure_edges else 1.0
        ),
        "styled_arrow_coverage": (
            len(styled_arrows) / len(arrows) if arrows else 1.0
        ),
        "standalone_text_total": len(standalone_text),
        "empty_text_count": len(empty_text),
        "empty_text_ratio": (
            len(empty_text) / len(standalone_text) if standalone_text else 0.0
        ),
        "layout_self_audit": layout_self_audit,
        "layout_warnings": layout_audit,
        "manifest_warnings": manifest_audit,
    }


def _format_report(entries: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for entry in entries:
        lines.append(f"## {entry['sample']}")
        lines.append(
            f"  element types: {entry['element_types']}"
        )
        lines.append(
            f"  arrows: rendered={entry['rendered_arrows']}"
            f" / structure_edges={entry['structure_edges']}"
            f" (coverage={entry['arrow_coverage']:.0%},"
            f" styled={entry['styled_arrow_coverage']:.0%})"
        )
        lines.append(
            f"  standalone text: total={entry['standalone_text_total']},"
            f" empty={entry['empty_text_count']}"
            f" ({entry['empty_text_ratio']:.0%})"
        )
        passed_audit = [
            k for k, v in (entry.get("layout_self_audit") or {}).items() if v is True
        ]
        failed_audit = [
            k for k, v in (entry.get("layout_self_audit") or {}).items() if v is False
        ]
        if entry.get("layout_self_audit"):
            lines.append(
                f"  layout self-audit: {len(passed_audit)} pass / "
                f"{len(failed_audit)} fail"
            )
            if failed_audit:
                lines.append(f"    failures: {failed_audit}")
        for warning in entry.get("layout_warnings", []) or []:
            lines.append(f"  warn (layout): {warning}")
        for warning in entry.get("manifest_warnings", []) or []:
            lines.append(f"  warn (manifest): {warning}")
        lines.append("")
    return "\n".join(lines)


def _verdict(entries: List[Dict[str, Any]]) -> int:
    """Return exit code — 0 if every sample meets thresholds, 1 otherwise."""
    failures: List[str] = []
    for entry in entries:
        if entry["arrow_coverage"] < ARROW_COVERAGE_MIN:
            failures.append(
                f"{entry['sample']}: arrow coverage "
                f"{entry['arrow_coverage']:.0%} < {ARROW_COVERAGE_MIN:.0%}"
            )
        if entry["empty_text_ratio"] > EMPTY_TEXT_MAX_RATIO:
            failures.append(
                f"{entry['sample']}: empty text ratio "
                f"{entry['empty_text_ratio']:.0%} > "
                f"{EMPTY_TEXT_MAX_RATIO:.0%}"
            )
    if failures:
        print("\nREGRESSION FAILURES:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--samples-root",
        type=Path,
        default=None,
        help=(
            "Directory containing per-sample subdirectories, or a variant root "
            "containing model subdirectories."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Model directory under the root when --samples-root points at "
            "outputs/evodiagram/<variant>."
        ),
    )
    parser.add_argument(
        "--samples",
        nargs="+",
        default=DEFAULT_SAMPLE_NAMES,
        help="Sample subdirectory names to audit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON report instead of the human-readable one.",
    )
    args = parser.parse_args(argv)

    entries: List[Dict[str, Any]] = []
    missing: List[str] = []
    samples_root = args.samples_root or _default_samples_root()
    for name in args.samples:
        sample_dir = _resolve_sample_dir(samples_root, name, args.model)
        result = _audit_sample(sample_dir)
        if result is None:
            missing.append(name)
            continue
        entries.append(result)

    if args.json:
        print(json.dumps(
            {"results": entries, "missing": missing}, indent=2, ensure_ascii=False
        ))
    else:
        if missing:
            print(f"# Skipped (missing inputs): {missing}\n")
        print(_format_report(entries))

    if missing:
        print("\nREGRESSION INPUT FAILURES:", file=sys.stderr)
        for name in missing:
            print(f"  - {name}: missing structure/layout inputs", file=sys.stderr)
        return 1
    if not entries:
        print("\nREGRESSION INPUT FAILURES:", file=sys.stderr)
        print("  - no samples were audited", file=sys.stderr)
        return 1

    return _verdict(entries)


if __name__ == "__main__":
    raise SystemExit(main())
