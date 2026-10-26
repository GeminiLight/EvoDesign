from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image

from evo_diagram.scripts import build_comparison_images, cleanup_origin_only, show_image


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_build_comparison_images_collects_current_experiment_layout(tmp_path):
    dataset_dir = tmp_path / "dataset" / "images" / "diagrams"
    dataset_dir.mkdir(parents=True)
    origin = dataset_dir / "sample_a.jpg"
    origin.write_bytes(b"origin")

    evodiagram_outputs = tmp_path / "experiments" / "exp1" / "outputs" / "evodiagram"
    evo_png = (
        evodiagram_outputs
        / "evodiagram"
        / "model-x"
        / "sample_a"
        / "rendered_diagram.png"
    )
    evo_png.parent.mkdir(parents=True)
    evo_png.write_bytes(b"evo")

    baseline_outputs = tmp_path / "experiments" / "exp1" / "outputs" / "baseline"
    baseline_png = baseline_outputs / "code_mermaid" / "model-x" / "sample_a" / "render.png"
    baseline_png.parent.mkdir(parents=True)
    baseline_png.write_bytes(b"baseline")

    output_dir = tmp_path / "comparison"
    build_comparison_images.build_comparison(
        repo_root=tmp_path,
        dataset_dir=dataset_dir,
        baseline_outputs_dir=baseline_outputs,
        evodiagram_outputs_dir=evodiagram_outputs,
        output_dir=output_dir,
    )

    assert (output_dir / "sample_a" / "origin.png").read_bytes() == b"origin"
    assert (output_dir / "sample_a" / "evodiagram-model-x.png").read_bytes() == b"evo"
    assert (
        output_dir / "sample_a" / "baseline-code_mermaid-model-x.png"
    ).read_bytes() == b"baseline"


def test_show_image_resolves_repo_root_image_dir_and_returns_nonzero_for_missing(tmp_path):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    img_path = image_dir / "sample_a.png"
    Image.new("RGB", (2, 3), color="white").save(img_path)

    assert show_image.resolve_image_path("sample_a", image_dir=image_dir) == img_path
    assert show_image.main(["missing", "--image-dir", str(image_dir)]) == 1
    assert show_image.main(["sample_a", "--image-dir", str(image_dir)]) == 0


def test_cleanup_origin_only_uses_repo_root_not_package_root():
    source = Path(cleanup_origin_only.__file__).read_text(encoding="utf-8")

    assert "parents[2]" in source
    assert "parents[1]" not in source


def test_comparison_helper_scripts_have_side_effect_free_help():
    for script_name in (
        "ab_compare_modes.py",
        "regression_render.py",
        "build_comparison_images.py",
        "show_image.py",
    ):
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "evo_diagram" / "scripts" / script_name),
                "--help",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0
        assert "usage:" in result.stdout.lower()
