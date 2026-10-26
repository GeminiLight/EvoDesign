from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _install_fake_python(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture_path = tmp_path / "python_args.txt"
    fake_python = bin_dir / "python3"
    fake_python.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
for arg in "$@"; do
  printf '%s\\n' "$arg" >> "$CAPTURE_ARGS"
done
printf '%s\\n' '---' >> "$CAPTURE_ARGS"
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    return bin_dir, capture_path


def _run_evodiagram_with_fake_python(
    tmp_path: Path,
    env_overrides: dict[str, str],
    *,
    check: bool = True,
):
    bin_dir, capture_path = _install_fake_python(tmp_path)
    env = os.environ.copy()
    env.update(env_overrides)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["CAPTURE_ARGS"] = str(capture_path)
    env["PYTHON_BIN"] = "python3"

    result = subprocess.run(
        ["bash", "scripts/run_evodiagram.sh"],
        cwd=REPO_ROOT,
        env=env,
        check=check,
        text=True,
        capture_output=True,
    )
    args = (
        capture_path.read_text(encoding="utf-8").splitlines()
        if capture_path.exists()
        else []
    )
    return result, args


def _run_baselines_with_fake_python(
    tmp_path: Path,
    env_overrides: dict[str, str],
    *,
    check: bool = True,
):
    bin_dir, capture_path = _install_fake_python(tmp_path)
    env = os.environ.copy()
    env.update(env_overrides)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["CAPTURE_ARGS"] = str(capture_path)
    env["PYTHON_BIN"] = "python3"

    result = subprocess.run(
        ["bash", "scripts/run_baselines.sh"],
        cwd=REPO_ROOT,
        env=env,
        check=check,
        text=True,
        capture_output=True,
    )
    args = (
        capture_path.read_text(encoding="utf-8").splitlines()
        if capture_path.exists()
        else []
    )
    return result, args


def _fake_python_calls(args: list[str]) -> list[list[str]]:
    calls: list[list[str]] = []
    current: list[str] = []
    for arg in args:
        if arg == "---":
            calls.append(current)
            current = []
        else:
            current.append(arg)
    if current:
        calls.append(current)
    return calls


def test_run_evaluation_returns_nonzero_when_any_method_fails(tmp_path):
    fake_root = tmp_path / "repo"
    fake_scripts = fake_root / "scripts"
    fake_scripts.mkdir(parents=True)
    (fake_scripts / "run_evaluation.sh").write_text(
        (REPO_ROOT / "scripts" / "run_evaluation.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    fake_evaluate = fake_scripts / "evaluate.sh"
    fake_evaluate.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
for arg in "$@"; do
  if [ "$arg" = "bad-method" ]; then
    exit 7
  fi
done
exit 0
""",
        encoding="utf-8",
    )
    fake_evaluate.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "METHODS": "good-method,bad-method,another-good-method",
            "EVO_EXPERIMENT_ID": "test-exp",
        }
    )
    result = subprocess.run(
        ["bash", str(fake_scripts / "run_evaluation.sh")],
        cwd=fake_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "[ERROR] Failed methods: bad-method" in result.stdout


def test_run_evaluation_allows_partial_only_when_explicit(tmp_path):
    fake_root = tmp_path / "repo"
    fake_scripts = fake_root / "scripts"
    fake_scripts.mkdir(parents=True)
    (fake_scripts / "run_evaluation.sh").write_text(
        (REPO_ROOT / "scripts" / "run_evaluation.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    fake_evaluate = fake_scripts / "evaluate.sh"
    fake_evaluate.write_text("#!/usr/bin/env bash\nexit 7\n", encoding="utf-8")
    fake_evaluate.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "METHODS": "bad-method",
            "EVO_EXPERIMENT_ID": "test-exp",
            "ALLOW_PARTIAL": "1",
        }
    )
    result = subprocess.run(
        ["bash", str(fake_scripts / "run_evaluation.sh")],
        cwd=fake_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "ALLOW_PARTIAL=1" in result.stdout


def test_run_evaluation_requires_explicit_generated_methods():
    env = os.environ.copy()
    env.pop("METHODS", None)
    result = subprocess.run(["bash", "scripts/run_evaluation.sh"], cwd=REPO_ROOT,
                            env=env, text=True, capture_output=True)
    assert result.returncode == 2
    assert "Set METHODS" in result.stderr


def test_run_evodiagram_wo_refiner_does_not_reference_legacy_env_or_refiner_iters(tmp_path):
    result, args = _run_evodiagram_with_fake_python(
        tmp_path,
        {
            "MODELS": "unit-model",
            "DATASET": "dataset/test/data.json",
            "START": "1",
            "END": "1",
            "ABLATION": "wo_refiner",
            "REFINER_ITERS": "5",
        },
    )

    assert "[INFO] Variant:   evodiagram_wo_refiner" in result.stdout
    assert "[INFO] Refiner:   disabled by variant" in result.stdout
    assert "[INFO] Mode:" not in result.stdout
    assert "--variant" in args
    assert args[args.index("--variant") + 1] == "evodiagram_wo_refiner"
    assert "--refiner-iterations" not in args
    assert args[args.index("--dataset-path") + 1] == str(REPO_ROOT / "dataset/test/data.json")


def test_run_evodiagram_custom_uses_settings_and_preserves_absolute_dataset_path(tmp_path):
    dataset_path = tmp_path / "data.json"
    dataset_path.write_text("[]", encoding="utf-8")

    result, args = _run_evodiagram_with_fake_python(
        tmp_path,
        {
            "MODELS": "unit-model",
            "DATASET": str(dataset_path),
            "ABLATION": "custom",
            "REFINER_ITERS": "",
            "EXTRA_ARGS": "--mode oneshot --no-verifier",
        },
    )

    assert "[INFO] Variant:   settings/EXTRA_ARGS" in result.stdout
    assert "--variant" not in args
    assert "--refiner-iterations" not in args
    assert "--all" in args
    assert args[args.index("--dataset-path") + 1] == str(dataset_path)
    assert "--mode" in args
    assert args[args.index("--mode") + 1] == "oneshot"
    assert "--no-verifier" in args


def test_run_evodiagram_defaults_to_explicit_all_mode(tmp_path):
    dataset_path = tmp_path / "data.json"
    dataset_path.write_text("[]", encoding="utf-8")

    result, args = _run_evodiagram_with_fake_python(
        tmp_path,
        {
            "MODELS": "unit-model",
            "DATASET": str(dataset_path),
        },
    )

    assert result.returncode == 0
    assert "[INFO] Range:     all → all" in result.stdout
    assert "--all" in args
    assert "--start" not in args
    assert "--end" not in args


def test_run_evodiagram_rejects_unpaired_range(tmp_path):
    result, args = _run_evodiagram_with_fake_python(
        tmp_path,
        {
            "MODELS": "unit-model",
            "START": "1",
        },
        check=False,
    )

    assert result.returncode == 2
    assert "START and END must be set together" in result.stderr
    assert args == []


def test_research_run_round_uses_package_mode_evodiagram_entrypoint(monkeypatch, tmp_path):
    from scripts.research import run_round

    captured = {}

    def fake_run(cmd, cwd, env, capture_output, text, timeout):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(run_round.subprocess, "run", fake_run)

    result = run_round._run_evodiagram(
        {"id": "sample-1"},
        dataset_path=tmp_path / "dataset.json",
        model_tag="step-3.7-flash",
        exp_id="unit-exp",
    )

    assert captured["cmd"][:3] == [run_round.sys.executable, "-m", "evo_diagram.agentic_system.main"]
    assert captured["cwd"] == run_round._REPO_ROOT
    assert str(run_round._REPO_ROOT) == captured["env"]["PYTHONPATH"].split(os.pathsep)[0]
    assert str(run_round._REPO_ROOT / "evo_diagram") not in captured["env"]["PYTHONPATH"].split(os.pathsep)
    assert captured["env"]["EVO_EXPERIMENT_ID"] == "unit-exp"
    assert result["exit_code"] == 0


def test_research_run_round_expected_png_uses_experiments_layout():
    from scripts.research import run_round

    model_tag = "provider/model:tag"

    assert run_round._expected_png(
        "evodiagram",
        "sample-1",
        model_tag,
        "exp-42",
    ).parts[-8:] == (
        "experiments",
        "exp-42",
        "outputs",
        "evodiagram",
        "evodiagram",
        "provider_model_tag",
        "sample-1",
        "rendered_diagram.png",
    )
    assert run_round._expected_png(
        "direct_llm_excalidraw",
        "sample-1",
        model_tag,
        "exp-42",
    ).parts[-8:] == (
        "experiments",
        "exp-42",
        "outputs",
        "baseline",
        "direct_llm",
        "provider_model_tag",
        "sample-1",
        "render.png",
    )
    assert run_round._expected_png(
        "mermaid",
        "sample-1",
        model_tag,
        "exp-42",
    ).parts[-8:] == (
        "experiments",
        "exp-42",
        "outputs",
        "baseline",
        "code_mermaid",
        "provider_model_tag",
        "sample-1",
        "render.png",
    )


def _eval_payload(
    *,
    content: float,
    visual: float,
    cognitive: float,
    avg: float,
) -> dict:
    return {
        "status": "success",
        "images": {
            "render.png": {
                "scores": {
                    "content_dimension": content,
                    "visual_dimension": visual,
                    "cognitive_dimension": cognitive,
                },
                "average_score": avg,
                "dimensions": {
                    "content": {
                        "content_dimension": {
                            "sub_scores": {"coverage": content},
                        },
                    },
                    "visual": {
                        "visual_dimension": {
                            "sub_scores": {"clarity": visual},
                        },
                    },
                    "cognitive": {
                        "cognitive_dimension": {
                            "sub_scores": {"flow": cognitive},
                        },
                    },
                },
            },
        },
    }


def test_research_aggregate_reads_experiments_scores_and_dynamic_round_config(monkeypatch, tmp_path):
    from evaluation import path_resolver
    from scripts.research import aggregate_round

    monkeypatch.setattr(path_resolver, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(aggregate_round, "_REPO_ROOT", tmp_path)

    round_dir = tmp_path / "results" / "research" / "round_custom"
    samples_path = round_dir / "samples.json"
    model_segment = "provider_model_tag"
    samples = [
        {"id": "sample-a", "diagram_type": "flow"},
        {"id": "sample-b", "diagram_type": "flow"},
    ]
    _write_json(samples_path, samples)
    _write_json(
        round_dir / "config.json",
        {
            "exp_id": "exp-42",
            "model_tag": "provider/model:tag",
            "model_segment": model_segment,
            "methods": ["evodiagram", "direct_llm_excalidraw", "mermaid"],
        },
    )

    score_roots = {
        "evodiagram": tmp_path
        / "experiments"
        / "exp-42"
        / "scores"
        / "evodiagram"
        / "evodiagram"
        / model_segment,
        "direct_llm": tmp_path
        / "experiments"
        / "exp-42"
        / "scores"
        / "baseline"
        / "direct_llm"
        / model_segment,
        "mermaid": tmp_path
        / "experiments"
        / "exp-42"
        / "scores"
        / "baseline"
        / "code_mermaid"
        / model_segment,
    }
    for data_id in ("sample-a", "sample-b"):
        _write_json(
            score_roots["evodiagram"] / data_id / f"{data_id}.json",
            _eval_payload(content=5, visual=4, cognitive=3, avg=4),
        )
        _write_json(
            score_roots["direct_llm"] / data_id / f"{data_id}.json",
            _eval_payload(content=3, visual=3, cognitive=3, avg=3),
        )
        _write_json(
            score_roots["mermaid"] / data_id / f"{data_id}.json",
            _eval_payload(content=2, visual=2, cognitive=2, avg=2),
        )

    # Stale historical score must not override the canonical experiments score.
    _write_json(
        tmp_path
        / "results"
        / "evaluations"
        / "evodiagram"
        / "sample-a"
        / "sample-a.json",
        _eval_payload(content=1, visual=1, cognitive=1, avg=1),
    )

    aggregate_round.aggregate(
        round_dir=round_dir,
        samples_path=samples_path,
    )

    scores_csv = (round_dir / "scores.csv").read_text(encoding="utf-8")
    breakdown = (round_dir / "breakdown.md").read_text(encoding="utf-8")

    assert "sample-a,flow,evodiagram,5,4,3,4" in scores_csv
    assert "sample-a,flow,evodiagram,1,1,1,1" not in scores_csv
    assert "# round_custom — 2 samples" in breakdown
    assert "- **Experiment**: `exp-42`" in breakdown
    assert "- **Total scored pairs**: 6 expected, 6 present" in breakdown
    assert "mean over 2 samples" in breakdown
    assert "Round 1 Pilot" not in breakdown


def test_research_runners_use_package_qualified_evodiagram_imports():
    run_evodiagram = (REPO_ROOT / "scripts" / "run_evodiagram.sh").read_text(
        encoding="utf-8"
    )
    run_baselines = (REPO_ROOT / "scripts" / "run_baselines.sh").read_text(
        encoding="utf-8"
    )
    run_round = (REPO_ROOT / "scripts" / "research" / "run_round.py").read_text(
        encoding="utf-8"
    )

    for script in (run_evodiagram, run_baselines):
        assert "$PROJECT_ROOT/evo_diagram" not in script
        assert 'PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"' in script

    assert '"evo_diagram.agentic_system.main"' in run_round
    assert '"agentic_system.main"' not in run_round
    assert '_EVO_DIAGRAM = _REPO_ROOT / "evo_diagram"' not in run_round


def test_domain_knowledge_compare_scripts_have_side_effect_free_help():
    for script_name in (
        "compare_domain_knowledge.py",
        "compare_domain_knowledge_parallel.py",
    ):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "evo_diagram" / "scripts" / script_name), "--help"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0
        assert "--dataset-path" in result.stdout
        assert "--output-dir" in result.stdout


def test_domain_knowledge_compare_scripts_use_repo_root_defaults_and_worker_models():
    serial = (
        REPO_ROOT / "evo_diagram" / "scripts" / "compare_domain_knowledge.py"
    ).read_text(encoding="utf-8")
    parallel = (
        REPO_ROOT / "evo_diagram" / "scripts" / "compare_domain_knowledge_parallel.py"
    ).read_text(encoding="utf-8")

    for source in (serial, parallel):
        assert 'DATASET_PATH = "../dataset/test/data.json"' not in source
        assert 'OUTPUT_BASE = "../experiments/compare_domain_knowledge"' not in source
        assert "DEFAULT_DATASET_PATH = REPO_ROOT / \"dataset\" / \"test\" / \"data.json\"" in serial

    assert "model = create_model()" in parallel
    assert "executor.submit(run_pair, item, exp, args.output_dir)" in parallel
    assert "has_missing_outputs(all_results)" in parallel


def test_domain_knowledge_compare_detects_missing_mode_outputs():
    from evo_diagram.scripts.compare_domain_knowledge import has_missing_outputs

    assert has_missing_outputs(
        [{"default_png": "/tmp/default.png", "full_png": "/tmp/full.png"}]
    ) is False
    assert has_missing_outputs(
        [{"default_png": "/tmp/default.png", "full_png": None}]
    ) is True
    assert has_missing_outputs(
        [{"default_png": None, "full_png": "/tmp/full.png"}]
    ) is True


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_migration_scripts_are_parameterized_and_have_safe_help():
    for script_name in ("migrate_new_training_data.py", "migrate_new_images.py"):
        source = (REPO_ROOT / "scripts" / script_name).read_text(encoding="utf-8")
        assert "/home/ubuntu" not in source
        assert "--write" in source
        assert "--dry-run" in source

        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / script_name), "--help"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0
        assert "--repo-root" in result.stdout


def test_training_data_migration_defaults_to_dry_run_and_dedupes_normalized_ids(tmp_path):
    from scripts import migrate_new_training_data as migration

    repo_root = tmp_path / "repo"
    old_train = [
        {
            "id": "old",
            "diagram_type": "flowchart",
            "image_url": "./wrong.jpg",
        }
    ]
    test_data = [{"id": "test_sample", "diagram_type": "tree"}]
    new_pack = [
        {
            "id": "test_sample.jpg",
            "diagram_type": "tree",
            "image_url": "./external/test_sample.jpg",
        },
        {
            "id": "new_sample.jpg",
            "diagram_type": "flowchart",
            "image_url": "./external/new_sample.jpg",
        },
    ]
    old_path = repo_root / "dataset" / "dataset_with_other_queries.json"
    test_path = repo_root / "dataset" / "test" / "data.json"
    new_path = tmp_path / "new_pack.json"
    output_path = repo_root / "dataset" / "train" / "data.json"
    sidecar_path = repo_root / "temp" / "migration" / "new_ids.json"
    _write_json(old_path, old_train)
    _write_json(test_path, test_data)
    _write_json(new_path, new_pack)

    code = migration.main(
        [
            "--repo-root",
            str(repo_root),
            "--new-pack-json",
            str(new_path),
            "--old-train-json",
            str(old_path),
            "--test-json",
            str(test_path),
            "--output",
            str(output_path),
            "--sidecar",
            str(sidecar_path),
        ]
    )

    assert code == 0
    assert not output_path.exists()
    assert not sidecar_path.exists()

    result = migration.run_migration(
        repo_root=repo_root,
        new_pack_json=new_path,
        old_train_json=old_path,
        test_json=test_path,
        output_path=output_path,
        sidecar_path=sidecar_path,
        dry_run=False,
    )

    assert result.removed_test_overlap == 1
    assert [record["id"] for record in result.new_records] == ["new_sample"]
    assert output_path.exists()
    assert sidecar_path.exists()
    merged = json.loads(output_path.read_text(encoding="utf-8"))
    assert merged[0]["vertical_domain"] == "general"
    assert merged[0]["image_url"] == "./dataset/images/diagrams/old.jpg"
    assert merged[1]["image_url"] == "./dataset/images/diagrams/new_sample.jpg"
    assert json.loads(sidecar_path.read_text(encoding="utf-8")) == ["new_sample"]


def test_training_data_migration_rejects_collisions_without_partial_write(tmp_path):
    from scripts import migrate_new_training_data as migration

    repo_root = tmp_path / "repo"
    old_path = repo_root / "dataset" / "dataset_with_other_queries.json"
    test_path = repo_root / "dataset" / "test" / "data.json"
    new_path = tmp_path / "new_pack.json"
    output_path = repo_root / "dataset" / "train" / "data.json"
    sidecar_path = repo_root / "temp" / "migration" / "new_ids.json"
    _write_json(
        old_path,
        [{"id": "dup", "diagram_type": "flowchart", "image_url": "./old.jpg"}],
    )
    _write_json(test_path, [])
    _write_json(new_path, [{"id": "dup.jpg", "diagram_type": "tree"}])

    with pytest.raises(ValueError, match="ID collision"):
        migration.run_migration(
            repo_root=repo_root,
            new_pack_json=new_path,
            old_train_json=old_path,
            test_json=test_path,
            output_path=output_path,
            sidecar_path=sidecar_path,
            dry_run=False,
        )

    assert not output_path.exists()
    assert not sidecar_path.exists()


def test_image_migration_requires_write_and_protects_existing_targets(tmp_path):
    from scripts import migrate_new_images as migration

    repo_root = tmp_path / "repo"
    id_list = repo_root / "temp" / "migration" / "new_ids.json"
    source_dir = tmp_path / "source_images"
    target_dir = repo_root / "dataset" / "images" / "diagrams"
    _write_json(id_list, ["sample"])
    source_dir.mkdir()
    (source_dir / "sample.jpg").write_bytes(b"new-image")

    assert migration.main(
        [
            "--repo-root",
            str(repo_root),
            "--id-list-json",
            str(id_list),
            "--new-pack-images",
            str(source_dir),
            "--target-dir",
            str(target_dir),
        ]
    ) == 0
    assert not (target_dir / "sample.jpg").exists()

    result = migration.copy_images(
        repo_root=repo_root,
        id_list_json=id_list,
        new_pack_images=source_dir,
        target_dir=target_dir,
        dry_run=False,
    )

    assert result.copied == 1
    assert (target_dir / "sample.jpg").read_bytes() == b"new-image"

    with pytest.raises(FileExistsError):
        migration.copy_images(
            repo_root=repo_root,
            id_list_json=id_list,
            new_pack_images=source_dir,
            target_dir=target_dir,
            dry_run=False,
        )

    with pytest.raises(FileNotFoundError):
        migration.copy_images(
            repo_root=repo_root,
            id_list_json=id_list,
            new_pack_images=tmp_path / "missing_images",
            target_dir=target_dir,
            dry_run=True,
        )


def test_run_baselines_defaults_to_batch_capable_module_entrypoints():
    run_baselines = (REPO_ROOT / "scripts" / "run_baselines.sh").read_text(
        encoding="utf-8"
    )

    assert not (REPO_ROOT / "evo_diagram" / "scripts" / "process_baseline.py").exists()
    assert 'PYTHON_BIN="${PYTHON_BIN:-python3}"' in run_baselines
    assert 'ALGORITHMS_CSV="${ALGORITHMS:-mermaid,direct_llm}"' in run_baselines
    assert '"$PYTHON_BIN" -u -m baselines.programmic.mermaid.main' in run_baselines
    assert '"$PYTHON_BIN" -u -m baselines.direct_llm.main' in run_baselines
    assert '"$PYTHON_BIN" -m baselines.pixel.gemini_image_generator' in run_baselines
    assert '"$PYTHON_BIN" -u -m baselines.programmic.tlkz.main' in run_baselines
    assert "[ERROR] Unknown algorithm: $algo" in run_baselines


def test_run_baselines_converts_one_based_ranges_for_native_baseline_clis(tmp_path):
    dataset_path = tmp_path / "subset.json"
    dataset_path.write_text("[]", encoding="utf-8")

    result, args = _run_baselines_with_fake_python(
        tmp_path,
        {
            "DATASET": str(dataset_path),
            "MODELS": "unit-model",
            "ALGORITHMS": "mermaid,direct_llm,diagramagent,scisketch",
            "START": "2",
            "END": "5",
            "MAX_CONCURRENT": "7",
            "EVO_EXPERIMENT_ID": "unit-exp",
        },
    )
    calls = _fake_python_calls(args)

    assert "[INFO] Resolved:    " + str(dataset_path) in result.stdout
    assert len(calls) == 4

    mermaid, direct_llm, diagramagent, scisketch = calls
    assert mermaid[:3] == ["-u", "-m", "baselines.programmic.mermaid.main"]
    assert mermaid[mermaid.index("--dataset") + 1] == str(dataset_path)
    assert mermaid[mermaid.index("--start") + 1] == "1"
    assert mermaid[mermaid.index("--end") + 1] == "5"
    assert mermaid[mermaid.index("--max-concurrent") + 1] == "7"

    assert direct_llm[:3] == ["-u", "-m", "baselines.direct_llm.main"]
    assert direct_llm[direct_llm.index("--dataset") + 1] == str(dataset_path)
    assert direct_llm[direct_llm.index("--start") + 1] == "1"
    assert direct_llm[direct_llm.index("--limit") + 1] == "4"
    assert direct_llm[direct_llm.index("--max-concurrent") + 1] == "7"

    assert diagramagent[:3] == ["-u", "-m", "baselines.diagramagent.DiagramAgentEvaluator"]
    assert diagramagent[diagramagent.index("-d") + 1] == str(dataset_path)
    assert diagramagent[diagramagent.index("-s") + 1] == "1"
    assert diagramagent[diagramagent.index("-e") + 1] == "5"

    assert scisketch[:3] == ["-u", "-m", "baselines.scisketch.src.custom_main"]
    assert scisketch[scisketch.index("--dataset") + 1] == str(dataset_path)
    assert scisketch[scisketch.index("--start") + 1] == "1"
    assert scisketch[scisketch.index("--end") + 1] == "5"


def test_run_baselines_rejects_unpaired_range(tmp_path):
    result, args = _run_baselines_with_fake_python(
        tmp_path,
        {
            "MODELS": "unit-model",
            "ALGORITHMS": "mermaid",
            "START": "2",
        },
        check=False,
    )

    assert result.returncode == 2
    assert "START and END must be set together" in result.stderr
    assert args == []


def test_run_baselines_rejects_range_for_pixel_unless_explicitly_allowed(tmp_path):
    result, args = _run_baselines_with_fake_python(
        tmp_path,
        {
            "MODELS": "unit-model",
            "ALGORITHMS": "pixel",
            "START": "1",
            "END": "3",
        },
        check=False,
    )

    assert result.returncode == 2
    assert "Pixel baseline does not support START/END range selection" in result.stderr
    assert args == []


def test_run_baselines_can_intentionally_allow_full_pixel_run_with_range_warning(tmp_path):
    result, args = _run_baselines_with_fake_python(
        tmp_path,
        {
            "MODELS": "unit-model",
            "ALGORITHMS": "pixel",
            "START": "1",
            "END": "3",
            "ALLOW_UNSUPPORTED_RANGE": "1",
        },
    )
    calls = _fake_python_calls(args)

    assert result.returncode == 0
    assert "Pixel baseline ignores START/END" in result.stderr
    assert len(calls) == 1
    assert calls[0][:2] == ["-m", "baselines.pixel.gemini_image_generator"]


def test_generated_frontend_api_contract_is_current():
    result = subprocess.run(
        [sys.executable, "scripts/generate_frontend_api_contract.py", "--check"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_quality_script_and_ci_include_engine_evaluation_and_user_memory_gates():
    check_quality = (REPO_ROOT / "scripts" / "check_quality.sh").read_text(
        encoding="utf-8"
    )
    quality_workflow = (
        REPO_ROOT / ".github" / "workflows" / "quality.yml"
    ).read_text(encoding="utf-8")

    assert "run_engine()" in check_quality
    assert "--ignore=evo_diagram/tests/design_memory/test_real_chroma_cosine.py" in check_quality
    assert "npm run test:editor" in check_quality
    assert "scripts/generate_frontend_api_contract.py --check" in check_quality
    assert '"$PY" -m pytest tests/pipeline evo_diagram/tests' in check_quality
    assert "tests/test_scripts.py" in check_quality
    assert "engine)" in check_quality
    assert "Run engine quality gate" in quality_workflow
    assert "./scripts/check_quality.sh engine" in quality_workflow

    assert "run_backend()" in check_quality
    assert '"$PY" -m pytest tests/backend' in check_quality
    assert "tests/backend/test_diagram_endpoint.py" not in check_quality
    assert "Run backend quality gate" in quality_workflow
    assert "./scripts/check_quality.sh backend" in quality_workflow

    assert "run_evaluation()" in check_quality
    assert '"$PY" -m pytest tests/evaluation' in check_quality
    assert "evaluation)" in check_quality
    assert "run_evaluation" in check_quality
    assert "Run evaluation quality gate" in quality_workflow
    assert "./scripts/check_quality.sh evaluation" in quality_workflow

    assert "run_user_memory()" in check_quality
    assert '"$PY" -m pytest evo_diagram/tests/user_memory' in check_quality
    assert "user-memory)" in check_quality
    assert "Run user memory quality gate" in quality_workflow
    assert "./scripts/check_quality.sh user-memory" in quality_workflow


@pytest.mark.parametrize('root_environment', [True, False])
def test_service_launcher_uses_project_python_not_global_uvicorn(tmp_path, root_environment):
    import time

    repo = tmp_path / 'repo with spaces'
    (repo / 'scripts').mkdir(parents=True)
    (repo / 'backend').mkdir()
    (repo / '.env').write_text('')
    script = repo / 'scripts/start_service.sh'
    script.write_text((REPO_ROOT / 'scripts/start_service.sh').read_text())
    capture = repo / 'invocation.txt'
    for relative, label in [('backend/venv/bin/python', 'legacy'), ('.venv/bin/python', 'root')]:
        if label == 'root' and not root_environment:
            continue
        interpreter = repo / relative
        interpreter.parent.mkdir(parents=True)
        interpreter.write_text(f'#!/bin/bash\nprintf "%s\\n" "{label}" "$@" > "$CAPTURE_ARGS"\n')
        interpreter.chmod(0o755)
    env = {**os.environ, 'CAPTURE_ARGS': str(capture), 'HOST': '127.0.0.1'}
    result = subprocess.run(['bash', str(script), 'backend'], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    deadline = time.monotonic() + 3
    while not capture.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert capture.read_text().splitlines() == [
        'root' if root_environment else 'legacy', '-m', 'uvicorn', 'app.main:app',
        '--host', '127.0.0.1', '--port', '3010', '--reload',
    ]
