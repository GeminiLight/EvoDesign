#!/usr/bin/env python3
"""Collect comparison images by id into a single folder.

Default layout (relative to repo root):
- dataset/images/diagrams
- experiments/{exp}/outputs/baseline/<method>/<model>/<id>/render.png
- experiments/{exp}/outputs/evodiagram/<variant>/<model>/<id>/rendered_diagram.png
- experiments/comparison/<id>/

Naming in output:
- origin.png
- baseline-<method>-<model>.png
- <variant>-<model>.png
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

IMAGE_EXTS = {".png", ".jpg", ".jpeg"}


def _default_experiment_outputs() -> tuple[Path, Path]:
    from evo_diagram.core.experiment import get_experiment_root

    experiment_root = get_experiment_root()
    return (
        experiment_root / "outputs" / "baseline",
        experiment_root / "outputs" / "evodiagram",
    )


def _iter_dirs(path: Path) -> Iterable[Path]:
    if not path.exists():
        return []
    return [p for p in path.iterdir() if p.is_dir()]


def _find_image_by_id(folder: Path, image_id: str) -> Optional[Path]:
    if not folder.exists():
        return None
    candidates = []
    for ext in (".png", ".jpg", ".jpeg"):
        candidate = folder / f"{image_id}{ext}"
        if candidate.exists():
            candidates.append(candidate)
    return candidates[0] if candidates else None


def _copy(src: Path, dst: Path, dry_run: bool) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        return
    shutil.copy2(src, dst)


def _copy_current_evodiagram_outputs(
    evodiagram_outputs_dir: Path,
    image_id: str,
    id_output_dir: Path,
    dry_run: bool,
) -> None:
    for variant_dir in _iter_dirs(evodiagram_outputs_dir):
        for model_dir in _iter_dirs(variant_dir):
            rendered = model_dir / image_id / "rendered_diagram.png"
            if rendered.exists():
                name = f"{variant_dir.name}-{model_dir.name}.png"
                _copy(rendered, id_output_dir / name, dry_run)


def _copy_current_baseline_outputs(
    baseline_outputs_dir: Path,
    image_id: str,
    id_output_dir: Path,
    dry_run: bool,
) -> None:
    for method_dir in _iter_dirs(baseline_outputs_dir):
        for model_dir in _iter_dirs(method_dir):
            for filename in ("render.png", "image.png"):
                rendered = model_dir / image_id / filename
                if rendered.exists():
                    name = f"baseline-{method_dir.name}-{model_dir.name}.png"
                    _copy(rendered, id_output_dir / name, dry_run)
                    break


def build_comparison(
    repo_root: Path,
    dataset_dir: Path,
    baseline_outputs_dir: Path,
    evodiagram_outputs_dir: Path,
    output_dir: Path,
    legacy_baselines_dir: Optional[Path] = None,
    legacy_evodiagram_dir: Optional[Path] = None,
    legacy_evodiagram_wo_icon_dir: Optional[Path] = None,
    dry_run: bool = False,
) -> None:
    # Build id -> dataset image map
    dataset_images = [p for p in dataset_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    id_to_dataset = {p.stem: p for p in dataset_images}

    for image_id, origin_path in id_to_dataset.items():
        id_output_dir = output_dir / image_id

        # origin
        _copy(origin_path, id_output_dir / "origin.png", dry_run)

        _copy_current_evodiagram_outputs(
            evodiagram_outputs_dir,
            image_id,
            id_output_dir,
            dry_run,
        )
        _copy_current_baseline_outputs(
            baseline_outputs_dir,
            image_id,
            id_output_dir,
            dry_run,
        )

        # Legacy fallback layouts kept for older local reports.
        if legacy_evodiagram_dir:
            for model_dir in _iter_dirs(legacy_evodiagram_dir):
                rendered = model_dir / image_id / "rendered_diagram.png"
                if rendered.exists():
                    name = f"legacy-evodiagram-{model_dir.name}.png"
                    _copy(rendered, id_output_dir / name, dry_run)

        if legacy_evodiagram_wo_icon_dir:
            for model_dir in _iter_dirs(legacy_evodiagram_wo_icon_dir):
                rendered = model_dir / image_id / "rendered_diagram.png"
                if rendered.exists():
                    name = f"legacy-evodiagram_wo_icon-{model_dir.name}.png"
                    _copy(rendered, id_output_dir / name, dry_run)

        if legacy_baselines_dir:
            for method_dir in _iter_dirs(legacy_baselines_dir):
                for model_dir in _iter_dirs(method_dir):
                    image_path = _find_image_by_id(model_dir, image_id)
                    if image_path:
                        name = f"legacy-baseline-{method_dir.name}-{model_dir.name}.png"
                        _copy(image_path, id_output_dir / name, dry_run)


def main() -> None:
    repo_root = REPO_ROOT

    parser = argparse.ArgumentParser(description="Collect comparison images by id.")
    parser.add_argument("--dataset-dir", type=Path, default=repo_root / "dataset/images/diagrams")
    parser.add_argument("--baseline-outputs-dir", type=Path, default=None)
    parser.add_argument("--evodiagram-outputs-dir", type=Path, default=None)
    parser.add_argument("--legacy-baselines-dir", type=Path, default=repo_root / "experiments/baselines")
    parser.add_argument("--legacy-evodiagram-dir", type=Path, default=repo_root / "experiments/evodiagram")
    parser.add_argument("--legacy-evodiagram-wo-icon-dir", type=Path, default=repo_root / "experiments/evodiagram_wo_icon")
    parser.add_argument("--output-dir", type=Path, default=repo_root / "experiments/comparison")
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    default_baseline_outputs, default_evodiagram_outputs = _default_experiment_outputs()

    build_comparison(
        repo_root=repo_root,
        dataset_dir=args.dataset_dir,
        baseline_outputs_dir=args.baseline_outputs_dir or default_baseline_outputs,
        evodiagram_outputs_dir=args.evodiagram_outputs_dir or default_evodiagram_outputs,
        legacy_baselines_dir=args.legacy_baselines_dir,
        legacy_evodiagram_dir=args.legacy_evodiagram_dir,
        legacy_evodiagram_wo_icon_dir=args.legacy_evodiagram_wo_icon_dir,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
