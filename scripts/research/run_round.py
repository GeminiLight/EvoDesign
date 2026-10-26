"""
Round orchestrator for the EvoDiagram research loop.

Reads a samples.json (built by build_test_subset.py), runs three methods on
each sample, and writes the rendered PNGs to the canonical experiments layout
expected by `evaluation/path_resolver.py` so that `evaluation.run_evaluation`
can score them without further plumbing:

    experiments/<exp_id>/outputs/evodiagram/evodiagram/<model>/<data_id>/rendered_diagram.png
    experiments/<exp_id>/outputs/baseline/direct_llm/<model>/<data_id>/render.png
    experiments/<exp_id>/outputs/baseline/code_mermaid/<model>/<data_id>/render.png

Round-specific bookkeeping (sample list, run config, generation status,
aggregate scores, breakdown markdown) lives in:

    results/research/<round_dir>/
        samples.json          -> snapshot of inputs
        config.json           -> model, methods, seed, git commit
        run_status.json       -> per-(sample, method) success/failure
        scores.csv            -> long-form scores after eval
        breakdown.md          -> human-readable summary

Usage
-----
    PYTHONPATH=. \\
    python \\
    -m scripts.research.run_round \\
        --samples results/research/round0_baseline/samples.json \\
        --round-dir results/research/round0_baseline \\
        --methods evodiagram direct_llm_excalidraw mermaid \\
        --model-tag gpt-5.5 \\
        --limit 1                    # pilot first; drop --limit for full run

The orchestrator never touches `evaluation/prompts/metric_prompts_merged.py`
or `metric_scorer.py`. Eval prompts are unchanged across all methods.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evo_diagram.core.experiment import (  # noqa: E402
    get_baseline_output_dir,
    get_evodiagram_output_dir,
    get_experiment_id,
)


logging.basicConfig(level=logging.INFO, format="[run_round] %(message)s")
logger = logging.getLogger(__name__)


def _git_commit() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT, stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def _llm_config_from_env() -> Dict[str, Any]:
    return {
        "model_name": os.environ.get("LLM_MODEL_NAME", "gpt-5.5"),
        "provider": os.environ.get("LLM_MODEL_PROVIDER", "openai"),
        "base_url": os.environ.get("LLM_ENDPOINT_URL", "https://api.your-proxy-endpoint/v1"),
        "api_key": os.environ.get("LLM_API_KEY"),
        "temperature": float(os.environ.get("LLM_TEMPERATURE", "0.0")),
    }


def _ensure_env() -> None:
    from evo_diagram.utils.env_loader import ensure_env_loaded

    ensure_env_loaded()


def _model_segment(model_tag: str) -> str:
    """Return the filesystem segment used for experiment output paths."""
    return model_tag.replace("/", "_").replace("\\", "_").replace(":", "_")


# ---------------------------------------------------------------------------
# Method runners
# ---------------------------------------------------------------------------


def _run_evodiagram(
    sample: Dict[str, Any],
    dataset_path: Path,
    model_tag: str,
    exp_id: str | None = None,
) -> Dict[str, Any]:
    """Invoke the evodiagram CLI for a single sample id."""
    data_id = sample["id"]
    resolved_exp_id = exp_id or get_experiment_id()
    model_id = _model_segment(model_tag)
    cmd = [
        sys.executable,
        "-m",
        "evo_diagram.agentic_system.main",
        "--ids",
        data_id,
        "--dataset-path",
        str(dataset_path),
        "--model",
        model_tag,
    ]
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT)
        if not existing_pythonpath
        else f"{_REPO_ROOT}{os.pathsep}{existing_pythonpath}"
    )
    env["EVO_EXPERIMENT_ID"] = resolved_exp_id
    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    elapsed = time.time() - started

    output_path = (
        get_evodiagram_output_dir("evodiagram", model_id, resolved_exp_id)
        / data_id
        / "rendered_diagram.png"
    )
    rendered = output_path.exists()
    return {
        "method": "evodiagram",
        "data_id": data_id,
        "elapsed_s": round(elapsed, 2),
        "exit_code": proc.returncode,
        "rendered": rendered,
        "output_path": str(output_path) if rendered else None,
        "cli_output_path": str(output_path) if output_path.exists() else None,
        "stderr_tail": proc.stderr[-400:] if proc.stderr else "",
    }


def _run_direct_llm_excalidraw(
    sample: Dict[str, Any],
    model_tag: str,
    model_config: Dict[str, Any],
    exp_id: str | None = None,
) -> Dict[str, Any]:
    """Run the new excalidraw-mode direct_llm baseline.

    Saves `render.png` in the canonical experiment output directory.
    """
    from baselines.direct_llm.runner_excalidraw import run_excalidraw_baseline

    data_id = sample["id"]
    resolved_exp_id = exp_id or get_experiment_id()
    model_id = _model_segment(model_tag)
    sample_dir = get_baseline_output_dir("direct_llm", model_id, resolved_exp_id) / data_id
    sample_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    result = run_excalidraw_baseline(
        text=sample.get("content") or "",
        output_dir=sample_dir,
        model_config=model_config,
        query=sample.get("query") or "",
    )
    elapsed = time.time() - started

    output_png = sample_dir / "render.png"
    rendered_png = result.get("output_path")
    if rendered_png and Path(rendered_png).exists():
        import shutil

        if Path(rendered_png).resolve() != output_png.resolve():
            shutil.copyfile(rendered_png, output_png)

    return {
        "method": "direct_llm_excalidraw",
        "data_id": data_id,
        "elapsed_s": round(elapsed, 2),
        "rendered": output_png.exists(),
        "output_path": str(output_png) if output_png.exists() else None,
        "errors": result.get("errors", []),
        "artifacts_dir": str(sample_dir),
    }


def _run_mermaid(
    sample: Dict[str, Any],
    model_tag: str,
    model_config: Dict[str, Any],
    exp_id: str | None = None,
) -> Dict[str, Any]:
    """Run the mermaid baseline: LLM emits Mermaid code -> Kroki -> PNG."""
    from evo_diagram.core.llm_factory import LLMFactory

    # Local imports avoid relying on `baselines.programmic.mermaid` package init
    sys.path.insert(0, str(_REPO_ROOT / "baselines" / "programmic" / "mermaid"))
    from mermaid_agent import MermaidAgent  # type: ignore
    from prompts import TASK_PROMPT  # type: ignore
    from baselines.programmic.kroki_render import KrokiRender

    # MermaidAgent inherits BaseAgent which has an abstract `run`. We only use
    # `invoke()`, so a thin concrete subclass is enough to satisfy ABC.
    class _MermaidAgentConcrete(MermaidAgent):  # type: ignore[misc]
        def run(self, state):  # noqa: D401
            return state

    data_id = sample["id"]
    content = sample.get("content") or ""
    query = sample.get("query") or "Generate a diagram representing this content"

    resolved_exp_id = exp_id or get_experiment_id()
    model_id = _model_segment(model_tag)
    sample_dir = get_baseline_output_dir("code_mermaid", model_id, resolved_exp_id) / data_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    output_png = sample_dir / "render.png"
    code_path = sample_dir / "diagram.mmd"

    errors: List[str] = []
    started = time.time()

    try:
        model = LLMFactory.create(
            model=model_config["model_name"],
            model_provider=model_config["provider"],
            base_url=model_config["base_url"],
            api_key=model_config["api_key"],
            temperature=model_config.get("temperature", 0.0),
        )
        agent = _MermaidAgentConcrete(model)
        formatted = TASK_PROMPT.format(content=content, query=query)
        response = agent.invoke({"content": content, "custom_task_prompt": formatted})

        code = (response or "").strip()
        if code.startswith("```mermaid"):
            code = code[len("```mermaid"):].strip()
        if code.startswith("```"):
            code = code[3:].strip()
        if code.endswith("```"):
            code = code[:-3].strip()

        code_path.write_text(code, encoding="utf-8")

        renderer = KrokiRender(diagram_type="mermaid", output_format="png")
        renderer.render(code, output_path=str(output_png))
    except Exception as e:
        errors.append(f"mermaid runner error: {e}")
        logger.exception("Mermaid run failed for %s", data_id)

    elapsed = time.time() - started
    return {
        "method": "mermaid",
        "data_id": data_id,
        "elapsed_s": round(elapsed, 2),
        "rendered": output_png.exists(),
        "output_path": str(output_png) if output_png.exists() else None,
        "errors": errors,
        "code_path": str(code_path) if code_path.exists() else None,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


_METHOD_DISPATCH = {
    "evodiagram": _run_evodiagram,
    "direct_llm_excalidraw": _run_direct_llm_excalidraw,
    "mermaid": _run_mermaid,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", required=True, help="Path to samples.json")
    parser.add_argument("--round-dir", required=True, help="Output dir for the round")
    parser.add_argument(
        "--methods",
        nargs="+",
        default=["evodiagram", "direct_llm_excalidraw", "mermaid"],
        choices=list(_METHOD_DISPATCH),
    )
    parser.add_argument("--model-tag", default="gpt-5.5")
    parser.add_argument(
        "--exp-id",
        default=None,
        help="Experiment id under experiments/<exp-id>. Defaults to EVO_EXPERIMENT_ID/config/date.",
    )
    parser.add_argument(
        "--dataset-path",
        default="dataset/test/data.json",
        help="Original dataset path for evodiagram CLI's --dataset-path argument",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Run only the first N samples (0 = all). Useful for pilots.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip (sample, method) pairs whose PNG already exists",
    )
    args = parser.parse_args()

    _ensure_env()
    model_config = _llm_config_from_env()
    exp_id = args.exp_id or get_experiment_id()

    samples_path = Path(args.samples).resolve()
    dataset_path = Path(args.dataset_path)
    if not dataset_path.is_absolute():
        dataset_path = (_REPO_ROOT / dataset_path).resolve()
    else:
        dataset_path = dataset_path.resolve()
    round_dir = Path(args.round_dir).resolve()
    round_dir.mkdir(parents=True, exist_ok=True)

    samples = json.loads(samples_path.read_text(encoding="utf-8"))
    if args.limit:
        samples = samples[: args.limit]

    config_snapshot = {
        "round_dir": str(round_dir),
        "samples_path": str(samples_path),
        "dataset_path": str(dataset_path),
        "samples_count": len(samples),
        "methods": args.methods,
        "model_tag": args.model_tag,
        "model_segment": _model_segment(args.model_tag),
        "exp_id": exp_id,
        "model_config": {**model_config, "api_key": "<redacted>"},
        "git_commit": _git_commit(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    (round_dir / "config.json").write_text(
        json.dumps(config_snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("Round dir: %s (%d samples, methods=%s)", round_dir, len(samples), args.methods)

    status: List[Dict[str, Any]] = []

    for sample_idx, sample in enumerate(samples, start=1):
        data_id = sample["id"]
        diagram_type = sample.get("diagram_type")
        logger.info(
            "[%d/%d] %s (%s)", sample_idx, len(samples), data_id, diagram_type
        )

        for method in args.methods:
            existing = _expected_png(method, data_id, args.model_tag, exp_id)
            if args.skip_existing and existing.exists():
                logger.info("  %s: SKIP (exists at %s)", method, existing)
                status.append(
                    {
                        "method": method,
                        "data_id": data_id,
                        "diagram_type": diagram_type,
                        "skipped": True,
                        "rendered": True,
                        "output_path": str(existing),
                    }
                )
                continue

            runner = _METHOD_DISPATCH[method]
            try:
                if method == "evodiagram":
                    res = runner(
                        sample,
                        dataset_path=dataset_path,
                        model_tag=args.model_tag,
                        exp_id=exp_id,
                    )
                else:
                    res = runner(
                        sample,
                        model_tag=args.model_tag,
                        model_config=model_config,
                        exp_id=exp_id,
                    )
            except Exception as e:
                logger.exception("Runner crashed for %s/%s", method, data_id)
                res = {
                    "method": method,
                    "data_id": data_id,
                    "rendered": False,
                    "errors": [f"runner crashed: {e}"],
                }
            res["diagram_type"] = diagram_type
            status.append(res)
            logger.info(
                "  %s: rendered=%s elapsed=%ss",
                method,
                res.get("rendered"),
                res.get("elapsed_s"),
            )

    (round_dir / "run_status.json").write_text(
        json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Print a tiny summary
    rendered = sum(1 for r in status if r.get("rendered"))
    logger.info("Done: %d/%d (sample, method) pairs rendered", rendered, len(status))


def _expected_png(method: str, data_id: str, model_tag: str, exp_id: str | None = None) -> Path:
    resolved_exp_id = exp_id or get_experiment_id()
    model_id = _model_segment(model_tag)
    if method == "evodiagram":
        return (
            get_evodiagram_output_dir("evodiagram", model_id, resolved_exp_id)
            / data_id
            / "rendered_diagram.png"
        )
    elif method == "direct_llm_excalidraw":
        return (
            get_baseline_output_dir("direct_llm", model_id, resolved_exp_id)
            / data_id
            / "render.png"
        )
    elif method == "mermaid":
        return (
            get_baseline_output_dir("code_mermaid", model_id, resolved_exp_id)
            / data_id
            / "render.png"
        )
    raise ValueError(f"unknown method: {method}")


if __name__ == "__main__":
    main()
