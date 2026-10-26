#!/usr/bin/env python3
"""A/B compare multiagent vs oneshot modes on the same dataset items.

Reads artefacts written by ``python -m evo_diagram.agentic_system.main --mode
multiagent`` and ``--mode oneshot``.  Current eval outputs live under
``experiments/{exp}/outputs/evodiagram/{variant}/{model}/{sample}``; legacy
per-sample roots are still accepted for local comparisons.

For co-located mode runs, multiagent is read from
``4_render/rendered_diagram.excalidraw`` and one-shot from
``1_unified/diagram_manifest.json``.  For separate roots, one-shot may also be
read from ``4_render/diagram_manifest.json``.  The script reports element
counts, arrow coverage vs structure edges, empty-text ratio, and audit warnings
when present.

This script does NOT call any LLM itself. To populate the inputs, run the
pipeline once per mode on your chosen sample:

    python -m evo_diagram.agentic_system.main --ids swimlane_20251205_094249_164 --mode multiagent
    python -m evo_diagram.agentic_system.main --ids swimlane_20251205_094249_164 --mode oneshot

Then::

    python -m evo_diagram.scripts.ab_compare_modes \\
        --samples-root experiments/2026-06-14/outputs/evodiagram/evodiagram \\
        --model step-3.7-flash \\
        --samples swimlane_20251205_094249_164 architecture_20251204_203338_92

The report is printed as Markdown so it pastes cleanly into a PR description.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evo_diagram.utils.path_manager import safe_path_segment


DEFAULT_SAMPLES = [
    "swimlane_20251205_094249_164",
    "architecture_20251204_203338_92",
    "concept_20251205_025801_50",
]


def _default_samples_root() -> Path:
    from evo_diagram.core.experiment import get_experiment_root

    return get_experiment_root() / "outputs" / "evodiagram" / "evodiagram"


def _load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _load_first_json(candidates: List[Path]) -> tuple[Optional[Path], Optional[Dict[str, Any]]]:
    for path in candidates:
        loaded = _load_json_safe(path)
        if loaded is not None:
            return path, loaded
    return None, None


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


def _manifest_metrics(manifest: Dict[str, Any]) -> Dict[str, Any]:
    elements = manifest.get("elements") or []
    if not isinstance(elements, list):
        elements = []

    types = Counter(
        e.get("type", "?") for e in elements if isinstance(e, dict)
    )
    standalone_text = [
        e for e in elements
        if isinstance(e, dict) and e.get("type") == "text" and not e.get("containerId")
    ]
    empty_text = [e for e in standalone_text if not e.get("text")]
    arrows = [e for e in elements if isinstance(e, dict) and e.get("type") == "arrow"]
    bindings_ok = sum(
        1 for a in arrows
        if a.get("startBinding") and a.get("endBinding")
    )
    return {
        "element_count": len(elements),
        "types": dict(types),
        "arrow_count": len(arrows),
        "arrow_binding_coverage": (
            bindings_ok / len(arrows) if arrows else 1.0
        ),
        "standalone_text_count": len(standalone_text),
        "empty_text_count": len(empty_text),
    }


def _compare_one_sample(
    sample_name: str,
    *,
    multiagent_dir: Path,
    oneshot_dir: Path,
) -> Dict[str, Any]:
    structure_path, structure = _load_first_json(
        [
            multiagent_dir / "1_structure" / "structure_instantiation.json",
            oneshot_dir / "1_structure" / "structure_instantiation.json",
        ]
    )
    structure = structure or {}
    structure_edges = structure.get("edges", []) or []

    pipeline_manifest_path, pipeline_manifest = _load_first_json(
        [
            multiagent_dir / "4_render" / "rendered_diagram.excalidraw",
            multiagent_dir / "4_render" / "diagram_manifest.json",
        ]
    )
    unified_manifest_path, unified_manifest = _load_first_json(
        [
            oneshot_dir / "1_unified" / "diagram_manifest.json",
            oneshot_dir / "4_render" / "diagram_manifest.json",
        ]
    )
    unified_warnings_path = oneshot_dir / "1_unified" / "audit_warnings.txt"
    unified_warnings = (
        unified_warnings_path.read_text(encoding="utf-8").splitlines()
        if unified_warnings_path.exists()
        else []
    )
    missing_artifacts = []
    if pipeline_manifest is None:
        missing_artifacts.append("multiagent")
    if unified_manifest is None:
        missing_artifacts.append("oneshot")

    result: Dict[str, Any] = {
        "sample": sample_name,
        "structure_edge_count": len(structure_edges),
        "multiagent": None,
        "oneshot": None,
        "oneshot_warnings": unified_warnings,
        "missing_artifacts": missing_artifacts,
        "paths": {
            "structure": str(structure_path) if structure_path else None,
            "multiagent": str(pipeline_manifest_path) if pipeline_manifest_path else None,
            "oneshot": str(unified_manifest_path) if unified_manifest_path else None,
        },
    }
    if pipeline_manifest is not None:
        result["multiagent"] = _manifest_metrics(pipeline_manifest)
    if unified_manifest is not None:
        result["oneshot"] = _manifest_metrics(unified_manifest)
    return result


def _render_markdown(entries: List[Dict[str, Any]]) -> str:
    lines: List[str] = [
        "# A/B Mode Comparison",
        "",
        "_multiagent = 3-stage Structure/Styling/Layout + deterministic render_  ",
        "_oneshot = single LLM call → Excalidraw + validator_",
        "",
    ]

    for entry in entries:
        lines.append(f"## {entry['sample']}")
        lines.append("")
        lines.append(f"- structure edges: **{entry['structure_edge_count']}**")
        lines.append("")

        multiagent = entry.get("multiagent")
        oneshot = entry.get("oneshot")
        if not multiagent and not oneshot:
            lines.append("  _No artefacts found for either mode. Run both first._")
            lines.append("")
            continue

        if entry.get("missing_artifacts"):
            missing = ", ".join(entry["missing_artifacts"])
            lines.append(f"  _Missing required artefacts: {missing}_")
            lines.append("")

        lines.append("| metric | multiagent | oneshot |")
        lines.append("|---|---|---|")

        def _fmt(section: Optional[Dict[str, Any]], key: str, formatter=str) -> str:
            if not section or key not in section:
                return "—"
            return formatter(section[key])

        lines.append(
            f"| element count | {_fmt(multiagent, 'element_count')} "
            f"| {_fmt(oneshot, 'element_count')} |"
        )
        lines.append(
            f"| arrows | {_fmt(multiagent, 'arrow_count')} "
            f"| {_fmt(oneshot, 'arrow_count')} |"
        )

        def _pct(section: Optional[Dict[str, Any]]) -> str:
            if not section:
                return "—"
            expected = entry["structure_edge_count"] or 1
            return f"{section['arrow_count'] / expected:.0%}"

        lines.append(
            f"| arrow coverage vs structure | {_pct(multiagent)} "
            f"| {_pct(oneshot)} |"
        )

        def _bind_pct(section: Optional[Dict[str, Any]]) -> str:
            if not section:
                return "—"
            return f"{section['arrow_binding_coverage']:.0%}"

        lines.append(
            f"| arrow binding coverage | {_bind_pct(multiagent)} "
            f"| {_bind_pct(oneshot)} |"
        )

        def _empty_text_line(section: Optional[Dict[str, Any]]) -> str:
            if not section:
                return "—"
            total = section["standalone_text_count"] or 1
            pct = section["empty_text_count"] / total
            return (
                f"{section['empty_text_count']}/"
                f"{section['standalone_text_count']} ({pct:.0%})"
            )

        lines.append(
            f"| empty standalone text | {_empty_text_line(multiagent)} "
            f"| {_empty_text_line(oneshot)} |"
        )

        if entry["oneshot_warnings"]:
            lines.append("")
            lines.append("oneshot audit warnings:")
            for w in entry["oneshot_warnings"][:5]:
                lines.append(f"  - {w}")
        lines.append("")

    return "\n".join(lines)


def _missing_required_artifacts(entries: List[Dict[str, Any]]) -> List[str]:
    missing = []
    for entry in entries:
        for mode in entry.get("missing_artifacts", []) or []:
            missing.append(f"{entry['sample']}:{mode}")
    return missing


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
        "--multiagent-root",
        type=Path,
        default=None,
        help="Optional root for multiagent sample directories. Defaults to --samples-root.",
    )
    parser.add_argument(
        "--oneshot-root",
        type=Path,
        default=None,
        help="Optional root for oneshot sample directories. Defaults to --samples-root.",
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
        default=DEFAULT_SAMPLES,
        help="Sample subdirectory names to compare.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the comparison as JSON instead of Markdown.",
    )
    args = parser.parse_args(argv)

    entries: List[Dict[str, Any]] = []
    samples_root = args.samples_root or _default_samples_root()
    multiagent_root = args.multiagent_root or samples_root
    oneshot_root = args.oneshot_root or samples_root
    for name in args.samples:
        entries.append(
            _compare_one_sample(
                name,
                multiagent_dir=_resolve_sample_dir(multiagent_root, name, args.model),
                oneshot_dir=_resolve_sample_dir(oneshot_root, name, args.model),
            )
        )

    if args.json:
        print(json.dumps(entries, indent=2, ensure_ascii=False))
    else:
        print(_render_markdown(entries))

    missing = _missing_required_artifacts(entries)
    if missing:
        print(
            "A/B comparison is missing required artifacts: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
