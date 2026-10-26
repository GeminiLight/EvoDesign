"""
Aggregate round evaluation outputs into a Markdown breakdown.

Reads only the per-sample eval JSONs written by ``evaluation.run_evaluation``
under the canonical ``experiments/<exp_id>/scores`` layout. Historical
``results/evaluations`` files are used only as a read fallback.

Layout it expects:
    experiments/<exp_id>/scores/evodiagram/evodiagram/<model>/<data_id>/<data_id>.json
    experiments/<exp_id>/scores/baseline/direct_llm/<model>/<data_id>/<data_id>.json
    experiments/<exp_id>/scores/baseline/code_mermaid/<model>/<data_id>/<data_id>.json

Outputs:
    <round-dir>/scores.csv
    <round-dir>/breakdown.md

Usage:
    python -m scripts.research.aggregate_round \\
        --samples results/research/round1_pilot10/samples.json \\
        --round-dir results/research/round1_pilot10 \\
        --model-tag gpt-5.5
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evo_diagram.core.experiment import get_experiment_id  # noqa: E402
from evaluation.path_resolver import parse_method_paths  # noqa: E402


@dataclass(frozen=True)
class MethodDefinition:
    key: str
    label: str
    evaluation_method_template: str
    legacy_eval_template: str

    def evaluation_method(self, model_segment: str) -> str:
        return self.evaluation_method_template.format(model=model_segment)

    def legacy_eval_dir(self, model: str, model_segment: str, data_id: str) -> Path:
        return _REPO_ROOT / self.legacy_eval_template.format(
            model=model,
            model_segment=model_segment,
            data_id=data_id,
        )


_METHOD_DEFINITIONS: Dict[str, MethodDefinition] = {
    "evodiagram": MethodDefinition(
        key="evodiagram",
        label="evodiagram",
        evaluation_method_template="evodiagram/{model}",
        legacy_eval_template="results/evaluations/evodiagram/{data_id}",
    ),
    "direct_llm_excalidraw": MethodDefinition(
        key="direct_llm_excalidraw",
        label="direct_llm",
        evaluation_method_template="baselines/direct_llm/{model}",
        legacy_eval_template="results/evaluations/baselines/direct_llm/{model}/{data_id}",
    ),
    "mermaid": MethodDefinition(
        key="mermaid",
        label="mermaid",
        evaluation_method_template="baselines/code_mermaid/{model}",
        legacy_eval_template="results/evaluations/baselines/code_mermaid/{model}/{data_id}",
    ),
}

_DEFAULT_METHOD_KEYS = ("evodiagram", "direct_llm_excalidraw", "mermaid")

_DIMENSIONS = ["content_dimension", "visual_dimension", "cognitive_dimension"]


def _model_segment(model_tag: str) -> str:
    return model_tag.replace("/", "_").replace("\\", "_").replace(":", "_")


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


def _load_round_config(round_dir: Path) -> Dict[str, Any]:
    config_path = round_dir / "config.json"
    if not config_path.exists():
        return {}
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  [warn] could not parse {config_path}: {exc}")
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _resolve_methods(
    configured_methods: Iterable[str] | None,
) -> List[MethodDefinition]:
    method_keys = list(configured_methods or _DEFAULT_METHOD_KEYS)
    methods: List[MethodDefinition] = []
    for key in method_keys:
        if key not in _METHOD_DEFINITIONS:
            raise ValueError(f"unknown research method: {key}")
        methods.append(_METHOD_DEFINITIONS[key])
    return methods


def _load_eval_json(
    method: MethodDefinition,
    data_id: str,
    *,
    model: str,
    model_segment: str,
    exp_id: str,
) -> Optional[Dict[str, Any]]:
    """Locate and load the per-(method, sample) eval JSON, or return None."""
    eval_method = method.evaluation_method(model_segment)
    _, score_dir, _ = parse_method_paths(eval_method, data_id, exp_id=exp_id)
    candidate = score_dir / f"{data_id}.json"
    if not candidate.exists():
        legacy_candidate = method.legacy_eval_dir(model, model_segment, data_id) / f"{data_id}.json"
        candidate = legacy_candidate
    if not candidate.exists():
        return None
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [warn] could not parse {candidate}: {e}")
        return None


def _scores_from_eval(eval_json: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """
    Pull the 3 dimension scores + their avg out of an eval JSON. The JSON has
    one entry under ``images``; we always pick the first (only one image per
    sample/method in our pipeline).
    """
    images = eval_json.get("images") or {}
    if not images:
        return {dim: None for dim in _DIMENSIONS} | {"avg": None}
    first = next(iter(images.values()))
    scores = first.get("scores") or {}
    avg = first.get("average_score")
    out = {dim: scores.get(dim) for dim in _DIMENSIONS}
    out["avg"] = avg
    return out


def _sub_scores_from_eval(eval_json: Dict[str, Any]) -> Dict[str, Dict[str, Optional[float]]]:
    """
    Pull sub-scores for each dimension (e.g. visual.flow_coherence) so we can
    show fine-grained deltas. Returns {dim: {sub_name: score}}.
    """
    images = eval_json.get("images") or {}
    if not images:
        return {}
    first = next(iter(images.values()))
    dims = first.get("dimensions") or {}
    out: Dict[str, Dict[str, Optional[float]]] = {}
    # The eval JSON nests as: dimensions.{content,visual,cognitive}.<dim>.sub_scores
    short_to_full = {
        "content": "content_dimension",
        "visual": "visual_dimension",
        "cognitive": "cognitive_dimension",
    }
    for short, full in short_to_full.items():
        bucket = (dims.get(short) or {}).get(full) or {}
        sub = bucket.get("sub_scores") or {}
        out[full] = {k: v for k, v in sub.items()}
    return out


def aggregate(
    round_dir: Path,
    samples_path: Path,
    model: str | None = None,
    exp_id: str | None = None,
    methods: Iterable[str] | None = None,
) -> None:
    samples: List[Dict[str, Any]] = json.loads(samples_path.read_text(encoding="utf-8"))
    config = _load_round_config(round_dir)
    resolved_model = model or str(config.get("model_tag") or "gpt-5.5")
    resolved_model_segment = str(config.get("model_segment") or _model_segment(resolved_model))
    resolved_exp_id = exp_id or str(config.get("exp_id") or get_experiment_id())
    method_defs = _resolve_methods(methods or config.get("methods"))
    method_labels = [method.label for method in method_defs]

    # Long-form rows for CSV: one per (sample, method)
    rows: List[Dict[str, Any]] = []
    # method -> dim -> [scores]
    by_method_dim: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    # method -> dim -> sub_name -> [scores]
    by_method_sub: Dict[str, Dict[str, Dict[str, List[float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    # type -> method -> [avg scores]
    by_type_method_avg: Dict[str, Dict[str, List[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    # (data_id, method) -> avg, for head-to-head pivot
    avg_grid: Dict[Tuple[str, str], Optional[float]] = {}

    missing: List[Tuple[str, str]] = []  # (data_id, method) pairs with no JSON

    for s in samples:
        data_id = s["id"]
        diagram_type = s.get("diagram_type", "?")
        for method in method_defs:
            label = method.label
            ej = _load_eval_json(
                method,
                data_id,
                model=resolved_model,
                model_segment=resolved_model_segment,
                exp_id=resolved_exp_id,
            )
            if ej is None:
                missing.append((data_id, label))
                rows.append(
                    {
                        "data_id": data_id,
                        "diagram_type": diagram_type,
                        "method": label,
                        "content": None,
                        "visual": None,
                        "cognitive": None,
                        "avg": None,
                    }
                )
                avg_grid[(data_id, label)] = None
                continue

            scores = _scores_from_eval(ej)
            sub = _sub_scores_from_eval(ej)
            rows.append(
                {
                    "data_id": data_id,
                    "diagram_type": diagram_type,
                    "method": label,
                    "content": scores.get("content_dimension"),
                    "visual": scores.get("visual_dimension"),
                    "cognitive": scores.get("cognitive_dimension"),
                    "avg": scores.get("avg"),
                }
            )
            avg_grid[(data_id, label)] = scores.get("avg")
            for dim in _DIMENSIONS:
                v = scores.get(dim)
                if v is not None:
                    by_method_dim[label][dim].append(v)
                for sub_name, sub_v in (sub.get(dim) or {}).items():
                    if sub_v is not None:
                        by_method_sub[label][dim][sub_name].append(sub_v)
            if scores.get("avg") is not None:
                by_type_method_avg[diagram_type][label].append(scores["avg"])

    # --- write CSV ---------------------------------------------------------
    round_dir.mkdir(parents=True, exist_ok=True)
    csv_path = round_dir / "scores.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["data_id", "diagram_type", "method", "content", "visual", "cognitive", "avg"],
        )
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"Wrote {csv_path}")

    # --- compute aggregates ------------------------------------------------
    def _mean(xs: List[float]) -> Optional[float]:
        return round(statistics.mean(xs), 3) if xs else None

    overall_avg: Dict[str, Optional[float]] = {}
    for m in method_labels:
        all_avgs = [
            avg_grid[(s["id"], m)]
            for s in samples
            if avg_grid.get((s["id"], m)) is not None
        ]
        overall_avg[m] = _mean(all_avgs)

    # --- write Markdown ---------------------------------------------------
    md_path = round_dir / "breakdown.md"
    lines: List[str] = []
    lines.append(f"# {round_dir.name} — {len(samples)} samples")
    lines.append("")
    lines.append(f"- **Samples**: {_display_path(samples_path)}")
    lines.append(f"- **Experiment**: `{resolved_exp_id}`")
    lines.append(f"- **Methods**: {' | '.join(method_labels)}")
    lines.append(f"- **Model**: `{resolved_model}`")
    expected_pairs = len(method_labels) * len(samples)
    lines.append(f"- **Total scored pairs**: {expected_pairs} expected, {expected_pairs - len(missing)} present")
    if missing:
        lines.append("")
        lines.append("**Missing eval outputs:**")
        for did, m in missing:
            lines.append(f"- `{did}` × `{m}`")

    # ---- 1. Overall scoreboard --------------------------------------------
    lines.append("")
    lines.append(f"## 1. Overall scoreboard (mean over {len(samples)} samples)")
    lines.append("")
    header = "| Method | content | visual | cognitive | **avg** |"
    sep = "|---|---:|---:|---:|---:|"
    lines += [header, sep]
    for m in method_labels:
        c = _mean(by_method_dim[m]["content_dimension"])
        v = _mean(by_method_dim[m]["visual_dimension"])
        cog = _mean(by_method_dim[m]["cognitive_dimension"])
        avg = overall_avg[m]
        lines.append(
            f"| {m} | {c if c is not None else '—'} | {v if v is not None else '—'} | "
            f"{cog if cog is not None else '—'} | **{avg if avg is not None else '—'}** |"
        )

    # ---- 2. Per-sample table ----------------------------------------------
    lines.append("")
    lines.append("## 2. Per-sample average scores")
    lines.append("")
    lines.append("| diagram_type | data_id | " + " | ".join(method_labels) + " | best |")
    lines.append("|---|---|" + "|".join(["---:"] * len(method_labels)) + "|---|")
    for s in samples:
        did = s["id"]
        dt = s.get("diagram_type", "?")
        cells = [avg_grid.get((did, label)) for label in method_labels]
        valid = [(label, x) for label, x in zip(method_labels, cells) if x is not None]
        best = max(valid, key=lambda kv: kv[1])[0] if valid else "—"

        def _fmt(x):
            return f"{x:.2f}" if isinstance(x, (int, float)) else "—"

        score_cells = " | ".join(_fmt(value) for value in cells)
        lines.append(f"| {dt} | `{did}` | {score_cells} | {best} |")

    # ---- 3. Per-type means ------------------------------------------------
    lines.append("")
    lines.append("## 3. Per-type average")
    lines.append("")
    lines.append("| diagram_type | " + " | ".join(method_labels) + " |")
    lines.append("|---|" + "|".join(["---:"] * len(method_labels)) + "|")
    seen_types: List[str] = []
    for s in samples:
        if s.get("diagram_type") not in seen_types:
            seen_types.append(s.get("diagram_type"))
    for t in seen_types:
        def _fmt(x):
            return f"{x:.2f}" if isinstance(x, (int, float)) else "—"

        cells = [_fmt(_mean(by_type_method_avg[t][label])) for label in method_labels]
        lines.append(f"| {t} | " + " | ".join(cells) + " |")

    # ---- 4. Head-to-head deltas (evodiagram vs each baseline) -------------
    baseline_labels = [label for label in method_labels if label != "evodiagram"]
    if "evodiagram" in method_labels and baseline_labels:
        def _fmt_delta(x):
            return f"{x:+.2f}" if isinstance(x, (int, float)) else "—"

        lines.append("")
        lines.append("## 4. Head-to-head: evodiagram - baseline (per sample, avg)")
        lines.append("")
        lines.append("Positive = evodiagram wins. Mean shown at the bottom.")
        lines.append("")
        lines.append("| data_id | " + " | ".join(f"Δ vs {label}" for label in baseline_labels) + " |")
        lines.append("|---|" + "|".join(["---:"] * len(baseline_labels)) + "|")
        deltas_by_label: Dict[str, List[float]] = {label: [] for label in baseline_labels}
        for s in samples:
            did = s["id"]
            evo = avg_grid.get((did, "evodiagram"))
            row_deltas: List[Optional[float]] = []
            for label in baseline_labels:
                baseline_value = avg_grid.get((did, label))
                delta = (
                    evo - baseline_value
                    if evo is not None and baseline_value is not None
                    else None
                )
                if delta is not None:
                    deltas_by_label[label].append(delta)
                row_deltas.append(delta)

            lines.append(f"| `{did}` | " + " | ".join(_fmt_delta(x) for x in row_deltas) + " |")

        summary_cells = []
        for label in baseline_labels:
            values = deltas_by_label[label]
            mean_delta = _mean(values)
            wins = sum(1 for x in values if x > 0)
            summary_cells.append(
                f"{_fmt_delta(mean_delta)} (evodiagram wins {wins}/{len(values)})"
            )
        lines.append("| **mean** | " + " | ".join(summary_cells) + " |")

    # ---- 5. Sub-metric breakdown ------------------------------------------
    lines.append("")
    lines.append(f"## 5. Sub-metric breakdown (mean over {len(samples)} samples)")
    lines.append("")
    sub_names_per_dim: Dict[str, List[str]] = {}
    for dim in _DIMENSIONS:
        names = set()
        for m in method_labels:
            names.update(by_method_sub[m][dim].keys())
        sub_names_per_dim[dim] = sorted(names)

    for dim in _DIMENSIONS:
        if not sub_names_per_dim[dim]:
            continue
        lines.append(f"### {dim}")
        lines.append("")
        header = "| sub-metric | " + " | ".join(method_labels) + " |"
        sep = "|---|" + "|".join(["---:"] * len(method_labels)) + "|"
        lines += [header, sep]
        for sub in sub_names_per_dim[dim]:
            cells = []
            for m in method_labels:
                v = _mean(by_method_sub[m][dim].get(sub, []))
                cells.append(f"{v:.2f}" if v is not None else "—")
            lines.append(f"| {sub} | " + " | ".join(cells) + " |")
        lines.append("")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {md_path}")
    if overall_avg:
        head = "  ".join(f"{m}={overall_avg[m]}" for m in method_labels)
        print(f"\nOverall avg: {head}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--samples", required=True, help="Path to samples.json")
    p.add_argument("--round-dir", required=True, help="Output dir of the round")
    p.add_argument("--model-tag", default=None)
    p.add_argument("--exp-id", default=None)
    p.add_argument(
        "--methods",
        nargs="+",
        choices=sorted(_METHOD_DEFINITIONS),
        help="Research method keys to aggregate. Defaults to round config or all known methods.",
    )
    args = p.parse_args()

    aggregate(
        round_dir=Path(args.round_dir).resolve(),
        samples_path=Path(args.samples).resolve(),
        model=args.model_tag,
        exp_id=args.exp_id,
        methods=args.methods,
    )


if __name__ == "__main__":
    main()
