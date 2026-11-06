"""Record (and replay) end-to-end Python pipeline runs with the LLM cassette.

Every run in RUN_SPECS executes the production entry path of
``evodesign.agentic_system.main`` — ``parse_arguments`` → ``build_config`` →
``validate_config`` → ``load_dataset`` → ``determine_items`` →
``initialize_model`` / ``initialize_router_model`` → ``process_example`` →
``Text2DiagramWorkflow.run`` — with only two substitutions:

* every chat model is the cassette model (tools/llm_cassette.py); in record
  mode its answers come from tools/cassette_synth.py, in replay mode from the
  recorded ``cassette.jsonl``;
* the per-item output directory is a fresh temporary directory instead of
  ``examples/<model>/<id>`` (main.get_output_dir), so recording never writes
  into the repository's examples.

Design memory and user memory are off (``--no-design-memory``, user memory
flags absent). Rendering goes through the normal Python renderer subprocess
(``tool_services/scripts/render-excalidraw.ts``) against
``EXCALIDRAW_RENDER_URL`` (default http://127.0.0.1:3001/renderers/excalidraw).

Output per run, ``fixtures/runs/<run>/``::

    input.json        spec, dataset item, CLI argv, environment, model config
    cassette.jsonl    one line per LLM call (see llm_cassette.py)
    images/           image parts sent to the model, by sha256
    snapshots.jsonl   node snapshots (see run_snapshots.py)
    artifacts/        every file the pipeline wrote, normalized (run_normalize.py)
    artifacts.json    index: path, kind, sha256 (+ PNG width/height/rgba_sha256)
    result.json       process_example() return value, normalized

Usage (repo root)::

    PYTHONPATH=. .venv/bin/python packages/render-engine/tools/record_runs.py            # record all twice + compare
    ... record_runs.py --run flow_x1__multi             # one run (substring match)
    ... record_runs.py --replay                         # replay every recorded run from its cassette
    ... record_runs.py --list
"""
from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional

TOOLS = pathlib.Path(__file__).resolve().parent
PACKAGE = TOOLS.parent
REPO = TOOLS.parents[2]
RUNS = PACKAGE / "fixtures" / "runs"
CASES = TOOLS / "run_cases"            # hand-authored cases (no example artifacts exist)
DEFAULT_RENDER_URL = "http://127.0.0.1:3001/renderers/excalidraw"

# Fixed, non-secret model configuration for every recording. configs/models.yaml
# resolves these env references; nothing ever reaches this endpoint because
# init_chat_model is replaced by the cassette model.
CASSETTE_ENV = {
    "LLM_MODEL_PROVIDER": "openai",
    "LLM_MODEL_NAME": "cassette-model",
    "LLM_ENDPOINT_URL": "http://127.0.0.1:9/v1",
    "LLM_API_KEY": "cassette-not-a-key",
    "LLM_THINKING": "",
    "LLM_TEMPERATURE": "",
    "LLM_MAX_TOKENS": "",
    # Keys that the repo .env would otherwise inject (dotenv never overrides
    # an existing variable, even an empty one).
    "JWT_SECRET": "", "SESSION_SECRET": "", "GUEST_TOKEN": "", "DB_TYPE": "", "DB_NAME": "",
    "HOST": "", "AUTO_REFINE_ENABLED": "", "DESIGN_MEMORY_ENABLED": "", "DESIGN_MEMORY_LEARNING": "",
    "RETAIN_GENERATION_ARTIFACTS": "", "STEPFUN_API_KEY": "",
    "PYTHONHASHSEED": "0",
}


def _spec(name: str, case: str, **options: Any) -> Dict[str, Any]:
    spec = {
        "name": name,
        "case": case,
        "mode": "multiagent",        # multiagent | oneshot
        "router": False,             # True: dataset item has no diagram_type → RouterAgent runs
        "refiner": False,            # --enable-refiner (else ENABLE_REFINER=false)
        "refiner_iterations": 2,
        "verifier": True,
        "critic": True,
        "use_icons": None,           # None: --use-icons iff the case styling has :icon entries
        "faults": [],
        "critic_scores": [],         # override overall_score per critic call (None keeps)
        "refiner_edits": None,       # explicit edit lists per refiner call
        "layout_format": "full",     # full | compact
        "notes": "",
    }
    spec.update(options)
    return spec


RUN_SPECS: List[Dict[str, Any]] = [
    # ── multiagent (Structure → Styling → Layout), no refinement ─────────────
    _spec("flow_x1__multi", "flow_x1", notes="flowchart, explicit diagram_type, verifier+critic"),
    _spec("flow_h1__router", "flow_h1", router=True, notes="flowchart through RouterAgent"),
    _spec("flow_leave_aes__compact", "flow_leave_aes", layout_format="compact",
          notes="flowchart with compact layout tuples (expand_layout_output)"),
    _spec("paper_full_f2__multi", "paper_full_f2", notes="architecture"),
    _spec("quickstart_service__router", "quickstart-service", router=True, notes="architecture with groups, router"),
    _spec("plain_ecommerce__icons", "plain-ecommerce", use_icons=True, notes="architecture with groups, icons on"),
    _spec("t_er_ty__multi", "t_er_ty", notes="er_diagram"),
    _spec("t_mindmap_ty__router", "t_mindmap_ty", router=True, notes="mindmap via router"),
    _spec("t_orgchart_ty__multi", "t_orgchart_ty", notes="orgchart"),
    _spec("t_sequence_tz__multi", "t_sequence_tz", notes="sequence_diagram"),
    _spec("t_state_tz__multi", "t_state_tz", notes="state_diagram"),
    _spec("t_swimlane_ty__multi", "t_swimlane_ty", notes="swimlane"),
    _spec("t_matrix_ty__multi", "t_matrix_ty", notes="matrix"),
    _spec("t_fishbone_ty__multi", "t_fishbone_ty", notes="fishbone"),
    _spec("cy_flywheel_ty2__multi", "cy_flywheel_ty2", notes="cycle"),
    _spec("ls_web_ty2__multi", "ls_web_ty2", notes="layer_stack"),
    _spec("dp_k8s_ty1__multi", "dp_k8s_ty1", notes="deployment"),
    _spec("kb_sprint_ty1__multi", "kb_sprint_ty1", notes="kanban"),
    _spec("sm_course_ty1__nocritic", "sm_course_ty1", critic=False, notes="story_map, --no-critic"),
    _spec("dg_pkgs_ty1__noverify", "dg_pkgs_ty1", verifier=False, notes="dependency_graph, --no-verifier"),
    _spec("concept_ml__multi", "concept_ml", notes="concept_map (hand-authored case in tools/run_cases)"),
    # ── JSON repair / resample faults ───────────────────────────────────────
    _spec("t_funnel_ty__repair", "t_funnel_ty", router=True,
          faults=[{"caller": "RouterAgent", "call": 1, "kind": "trailing_comma"},
                  {"caller": "StructureAgent", "call": 1, "kind": "fenced_prose"},
                  {"caller": "LayoutAgent", "call": 1, "kind": "truncated"},
                  {"caller": "VerifierCriticAgent", "call": 1, "kind": "not_json"}],
          notes="funnel; malformed router/structure/layout/critic answers exercise JSON repair and resampling"),
    _spec("t_timeline_ty__repair", "t_timeline_ty",
          faults=[{"caller": "StylingAgent", "call": 1, "kind": "empty"}],
          notes="timeline; empty styling answer → repair turn with the empty-response echo"),
    # ── verification + iterative refinement ─────────────────────────────────
    _spec("hcai_demo__refine", "hcai_demo", refiner=True, notes="flowchart; critic 6.5 → refinement, report LLM edits"),
    _spec("big_en_aes__refine", "big_en_aes", refiner=True, refiner_iterations=3,
          notes="architecture; refinement loop with recorded LLM edits"),
    _spec("paper_method_x2__refine", "paper_method_x2", refiner=True,
          notes="architecture; refinement + final verification"),
    _spec("t_swot_ty__refine", "t_swot_ty", refiner=True,
          faults=[{"caller": "RefinerLLMAgent", "call": 1, "kind": "not_json"},
                  {"caller": "RefinerLLMAgent", "call": 2, "kind": "edit_schema_drift"}],
          notes="swot; refiner resample after non-JSON, schema-drifted edit rejected"),
    _spec("t_class_tz__refine_forced", "t_class_tz", refiner=True, critic_scores=[5.0, 8.0],
          notes="class_diagram; low critic score forces refinement, candidate re-verified"),
    _spec("ne_saas_ty1__refine", "ne_saas_ty1", refiner=True, refiner_iterations=1, notes="nested; one iteration"),
    _spec("t_er_tz__refine_regress", "t_er_tz", refiner=True, critic_scores=[6.0, 4.0],
          notes="er_diagram; candidate scores lower → refined candidate rejected"),
    _spec("t_state_tz__refine_multi", "t_state_tz", refiner=True, refiner_iterations=3, critic_scores=[5.0, 8.0],
          refiner_edits=[
              [{"op": "set_position", "id": "7c536a61fd38c319b571", "payload": {"x": 500, "y": 170},
                "rationale": "cassette: overlap a neighbour to create an objective regression"},
               {"op": "set_style", "id": "9f935c092cbdc07814f7", "payload": {"strokeWidth": 3},
                "rationale": "cassette: emphasise the final state"}],
              [{"op": "set_position", "id": "7c536a61fd38c319b571", "payload": {"x": 757.5, "y": 158.5},
                "rationale": "cassette: move it back"}],
              [],
          ],
          notes="state_diagram; scripted LLM edits: iteration 1 regresses objectively → rolled back, stops at fixed point"),
    # ── unified / native (oneshot) ──────────────────────────────────────────
    _spec("ecommerce_aes__unified", "ecommerce_aes", mode="oneshot", notes="architecture, native scene"),
    _spec("flow_x2__unified_router", "flow_x2", mode="oneshot", router=True, notes="flowchart, router + native scene"),
    _spec("t_orgchart_ty__unified_repair", "t_orgchart_ty", mode="oneshot",
          faults=[{"caller": "UnifiedGenerator", "call": 1, "kind": "invalid_scene"}],
          notes="native scene fails sidecar validation once → repair turn"),
    _spec("rag_aes__unified_stream", "rag_aes", mode="oneshot",
          faults=[{"caller": "UnifiedGenerator", "call": 1, "kind": "stream_interrupted"},
                  {"caller": "UnifiedGenerator", "call": 2, "kind": "continuation"}],
          notes="native stream interrupted → continuation suffix request"),
    _spec("iot_aes__unified_refine", "iot_aes", mode="oneshot", refiner=True, critic_scores=[6.0, 8.0],
          notes="native scene + refinement loop"),
]


# A finished pipeline whose verification quality gate fails is a legitimate,
# recordable production outcome (main.process_example returns success=False).
ACCEPTED_FAILURES = {"VerificationQualityError"}


# ── worker (one run, in a subprocess) ─────────────────────────────────────


def case_root(case: str) -> pathlib.Path:
    custom = CASES / case
    return custom if custom.is_dir() else REPO / "examples" / "configured-model" / case


def build_item(spec: Dict[str, Any], case: Any) -> Dict[str, Any]:
    from cassette_synth import synthesize_input

    text = synthesize_input(case)
    item = {"id": spec["name"], "content": text["content"], "query": text["query"], "content_area": "unknown"}
    if not spec["router"]:
        item["diagram_type"] = case.chart_type
    return item


def case_uses_icons(case: Any) -> bool:
    return any(str(key).endswith(":icon") for key in (case.styling or {}))


def build_argv(spec: Dict[str, Any], dataset_path: str, case: Any) -> List[str]:
    argv = ["main", "--example", "1", "--dataset-path", dataset_path, "--mode", spec["mode"],
            "--no-design-memory", "--refiner-iterations", str(spec["refiner_iterations"])]
    if spec["refiner"]:
        argv.append("--enable-refiner")
    if not spec["verifier"]:
        argv.append("--no-verifier")
    if not spec["critic"]:
        argv.append("--no-critic")
    use_icons = case_uses_icons(case) if spec["use_icons"] is None else spec["use_icons"]
    argv.append("--use-icons" if use_icons else "--no-icons")
    return argv


def run_environment(spec: Dict[str, Any], render_url: str) -> Dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "TMPDIR": os.environ.get("TMPDIR", tempfile.gettempdir()),
        "PYTHONPATH": f"{REPO}{os.pathsep}{TOOLS}",
        "EXCALIDRAW_RENDER_URL": render_url,
        "ENABLE_REFINER": "true" if spec["refiner"] else "false",
        "LANG": "en_US.UTF-8",
        **CASSETTE_ENV,
    }
    for name in ("PLAYWRIGHT_BROWSERS_PATH", "NODE_PATH", "npm_config_cache"):
        if os.environ.get(name):
            env[name] = os.environ[name]
    return env


def worker(spec: Dict[str, Any], mode: str, dest: pathlib.Path, source: Optional[pathlib.Path], trace: bool) -> int:
    """Execute one run in this process and write its fixture directory."""
    import logging

    sys.path.insert(0, str(TOOLS))
    import export_fixtures
    import llm_cassette
    import run_snapshots
    from cassette_synth import CaseArtifacts, Synthesizer
    from run_normalize import Normalizer

    os.chdir(REPO)
    case = CaseArtifacts(spec["case"], root=case_root(spec["case"]).parent)
    work = pathlib.Path(tempfile.mkdtemp(prefix="evodesign-run-"))
    out_dir = work / "out"
    out_dir.mkdir()
    normalizer = Normalizer(work)
    dest.mkdir(parents=True, exist_ok=True)

    tracer = None
    if trace:  # phase-2 function vectors (export_fixtures.py --phase2)
        tracer = export_fixtures.Tracer(modules=export_fixtures.PHASE2_TRACED_MODULES, first_calls=10, max_per_function=20)
        tracer.source = "runs"
        tracer.install()

    if mode == "record":
        session = llm_cassette.CassetteSession(dest, mode="record", responder=Synthesizer(case, spec))
    else:
        assert source is not None
        session = llm_cassette.CassetteSession.load(source)
        session.directory = dest
        session.images = llm_cassette.ImageStore(dest)
    llm_cassette.install(session)
    recorder = run_snapshots.SnapshotRecorder(export_fixtures.encode, normalizer.value)
    run_snapshots.install(recorder)

    item = build_item(spec, case)
    dataset_path = work / "dataset.json"
    dataset_path.write_text(json.dumps([item], ensure_ascii=False, indent=2), encoding="utf-8")
    argv = build_argv(spec, str(dataset_path), case)

    from evodesign.agentic_system import main as entry

    logging.getLogger().setLevel(logging.WARNING)
    sys.argv = argv
    args = entry.parse_arguments()
    config = entry.build_config(args)
    entry.validate_config(config, args)
    dataset, loaded_path = entry.load_dataset(args.dataset_path)
    items = entry.determine_items(dataset, args)
    model, model_name = entry.initialize_model(config)
    router_model = entry.initialize_router_model() if entry._items_need_router(items) else None
    (example_num, dataset_item), = items
    item_router = router_model if entry._explicit_diagram_type(dataset_item) is None else None
    error: Optional[str] = None
    try:
        result = entry.process_example(example_num, dataset_item, model, config, str(out_dir), router_model=item_router)
    except llm_cassette.CassetteMismatch as exc:
        error = f"CassetteMismatch: {exc}"
        result = None
    recorder.enabled = False

    if tracer is not None:
        tracer.write_partial(dest / "_vectors.json")

    # ── write fixture directory ──
    session.write(dest)
    with open(dest / "snapshots.jsonl", "w", encoding="utf-8") as handle:
        for record in recorder.records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    artifacts_dir = dest / "artifacts"
    if artifacts_dir.exists():
        shutil.rmtree(artifacts_dir)
    index = []
    for path in sorted(p for p in out_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(out_dir).as_posix()
        target = artifacts_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        entry_info: Dict[str, Any] = {"path": rel}
        if path.suffix in {".json", ".excalidraw"}:
            data = normalizer.value(json.loads(path.read_text(encoding="utf-8")))
            target.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            entry_info["kind"] = "json"
        elif path.suffix in {".md", ".txt", ".log"}:
            target.write_text(normalizer.text(path.read_text(encoding="utf-8")), encoding="utf-8")
            entry_info["kind"] = "text"
        elif path.suffix == ".png":
            shutil.copyfile(path, target)
            entry_info.update(kind="png", **png_info(path))
        else:
            shutil.copyfile(path, target)
            entry_info["kind"] = "binary"
        entry_info["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        index.append(entry_info)
    (dest / "artifacts.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    (dest / "result.json").write_text(json.dumps(normalizer.value({"result": result, "error": error}), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (dest / "input.json").write_text(json.dumps(normalizer.value({
        "run": spec["name"],
        "spec": spec,
        "item": item,
        "argv": argv[1:],
        "dataset_path": str(dataset_path),
        "output_dir": "<OUT>",
        "model_name": model_name,
        "env": {k: v for k, v in run_environment(spec, os.environ.get("EXCALIDRAW_RENDER_URL", DEFAULT_RENDER_URL)).items()
                if k not in {"PATH", "HOME", "TMPDIR", "PYTHONPATH", "LANG"}},
        "models_yaml": "configs/models.yaml",
        "settings_yaml": "configs/settings.yaml",
        "normalization": "tools/run_normalize.py",
    }), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if session.mismatch:
        (dest / "mismatch.json").write_text(json.dumps(session.mismatch, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    return 2 if session.mismatch else 0


def png_info(path: pathlib.Path) -> Dict[str, Any]:
    from PIL import Image

    with Image.open(path) as image:
        return {"width": image.size[0], "height": image.size[1],
                "rgba_sha256": hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()}


# ── comparison ───────────────────────────────────────────────────────────


def compare_dirs(expected: pathlib.Path, actual: pathlib.Path) -> List[str]:
    """Identical fixture directories? PNGs may differ in bytes but not pixels."""
    problems: List[str] = []
    left = {p.relative_to(expected).as_posix() for p in expected.rglob("*") if p.is_file() and not p.name.startswith("_")}
    right = {p.relative_to(actual).as_posix() for p in actual.rglob("*") if p.is_file() and not p.name.startswith("_")}
    for rel in sorted(left ^ right):
        problems.append(f"{rel}: only in {'first' if rel in left else 'second'}")
    for rel in sorted(left & right):
        a, b = (expected / rel).read_bytes(), (actual / rel).read_bytes()
        if a == b:
            continue
        if rel.endswith(".png"):
            if png_info(expected / rel) == png_info(actual / rel):
                continue
            problems.append(f"{rel}: PNG pixels differ")
        elif rel == "artifacts.json":
            if _artifact_index_equal(json.loads(a), json.loads(b)):
                continue
            problems.append(f"{rel}: index differs")
        else:
            problems.append(f"{rel}: content differs ({_first_line_diff(a, b)})")
    return problems


def _artifact_index_equal(a: List[Dict[str, Any]], b: List[Dict[str, Any]]) -> bool:
    strip = lambda items: [{k: v for k, v in item.items() if not (item.get("kind") == "png" and k == "sha256")} for item in items]
    return strip(a) == strip(b)


def _first_line_diff(a: bytes, b: bytes) -> str:
    la, lb = a.decode("utf-8", "replace").splitlines(), b.decode("utf-8", "replace").splitlines()
    for index, (x, y) in enumerate(zip(la, lb)):
        if x != y:
            return f"line {index + 1}: {x[:160]!r} vs {y[:160]!r}"
    return f"line count {len(la)} vs {len(lb)}"


# ── driver ───────────────────────────────────────────────────────────────


def spawn(spec: Dict[str, Any], mode: str, dest: pathlib.Path, source: Optional[pathlib.Path], render_url: str, trace: bool = False) -> Dict[str, Any]:
    started = time.monotonic()
    command = [sys.executable, str(TOOLS / "record_runs.py"), "--worker", spec["name"], "--worker-mode", mode, "--dest", str(dest)]
    if source is not None:
        command += ["--source", str(source)]
    if trace:
        command.append("--trace")
    completed = subprocess.run(command, env=run_environment(spec, render_url), cwd=REPO,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log = completed.stdout
    logs = RUNS / "_logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / f"{spec['name']}.{mode}.log").write_text(log, encoding="utf-8")
    return {"run": spec["name"], "mode": mode, "code": completed.returncode, "seconds": round(time.monotonic() - started, 1),
            "tail": log[-3000:] if completed.returncode else ""}


def record_one(spec: Dict[str, Any], render_url: str, scratch: pathlib.Path) -> Dict[str, Any]:
    dest = RUNS / spec["name"]
    if dest.exists():
        shutil.rmtree(dest)
    first = spawn(spec, "record", dest, None, render_url)
    if first["code"] != 0:
        return {**first, "ok": False, "problems": ["first recording failed"]}
    second_dir = scratch / spec["name"]
    second = spawn(spec, "record", second_dir, None, render_url)
    if second["code"] != 0:
        return {**second, "ok": False, "problems": ["second recording failed"]}
    problems = compare_dirs(dest, second_dir)
    shutil.rmtree(second_dir, ignore_errors=True)
    summary = summarize(dest)
    if summary["success"] is not True and summary.get("error_type") not in ACCEPTED_FAILURES and not spec.get("expect_failure"):
        problems.insert(0, f"pipeline did not succeed: {summary.get('error')}")
    return {"run": spec["name"], "ok": not problems, "problems": problems[:20],
            "seconds": first["seconds"] + second["seconds"], **summary}


def replay_one(spec: Dict[str, Any], render_url: str, scratch: pathlib.Path) -> Dict[str, Any]:
    source = RUNS / spec["name"]
    dest = scratch / f"replay-{spec['name']}"
    outcome = spawn(spec, "replay", dest, source, render_url)
    problems = [] if outcome["code"] == 0 else [f"replay exited {outcome['code']}"]
    if (dest / "mismatch.json").exists():
        problems.append("cassette mismatch: " + (dest / "mismatch.json").read_text(encoding="utf-8")[:600])
    if dest.exists():
        problems += compare_dirs(source, dest)
    shutil.rmtree(dest, ignore_errors=True)
    return {"run": spec["name"], "ok": not problems, "problems": problems[:20], "seconds": outcome["seconds"],
            "tail": outcome.get("tail", "")}


def summarize(directory: pathlib.Path) -> Dict[str, Any]:
    entries = [json.loads(line) for line in (directory / "cassette.jsonl").read_text(encoding="utf-8").splitlines() if line]
    snapshots = (directory / "snapshots.jsonl").read_text(encoding="utf-8").count("\n")
    callers: Dict[str, int] = {}
    for entry in entries:
        callers[entry["caller"]] = callers.get(entry["caller"], 0) + 1
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    return {
        "llm_calls": len(entries),
        "callers": callers,
        "sources": sorted({entry.get("source") for entry in entries}),
        "snapshots": snapshots,
        "artifacts": len(json.loads((directory / "artifacts.json").read_text(encoding="utf-8"))),
        "success": (result.get("result") or {}).get("success"),
        "error": (result.get("result") or {}).get("error") or result.get("error"),
        "error_type": (result.get("result") or {}).get("error_type"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", action="append", help="substring of run names (repeatable)")
    parser.add_argument("--replay", action="store_true", help="replay recorded runs from their cassettes and compare")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--render-url", default=os.environ.get("EXCALIDRAW_RENDER_URL", DEFAULT_RENDER_URL))
    parser.add_argument("--worker")
    parser.add_argument("--worker-mode", choices=["record", "replay"])
    parser.add_argument("--dest")
    parser.add_argument("--source")
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args()

    if args.worker:
        spec = next(s for s in RUN_SPECS if s["name"] == args.worker)
        return worker(spec, args.worker_mode, pathlib.Path(args.dest),
                      pathlib.Path(args.source) if args.source else None, args.trace)

    if ":3000" in args.render_url:
        raise SystemExit("refusing to use the port-3000 renderer; use 3001")
    specs = [s for s in RUN_SPECS if not args.run or any(part in s["name"] for part in args.run)]
    if args.list:
        for spec in specs:
            print(f"{spec['name']:40} {spec['mode']:10} {spec['notes']}")
        return 0
    RUNS.mkdir(parents=True, exist_ok=True)
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="evodesign-record-"))
    job = replay_one if args.replay else record_one
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {pool.submit(job, spec, args.render_url, scratch): spec for spec in specs}
        for future in concurrent.futures.as_completed(futures):
            outcome = future.result()
            results.append(outcome)
            status = "OK  " if outcome["ok"] else "FAIL"
            print(f"{status} {outcome['run']:40} {outcome.get('seconds')}s {'; '.join(outcome.get('problems', [])[:3])}", flush=True)
            if not outcome["ok"] and outcome.get("tail"):
                print(outcome["tail"][-1500:], flush=True)
    results.sort(key=lambda item: item["run"])
    report = RUNS / ("_replay.json" if args.replay else "_index.json")
    if not args.run:
        report.write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    else:  # merge partial recordings into the index
        existing = json.loads(report.read_text(encoding="utf-8")) if report.exists() else []
        names = {spec["name"] for spec in RUN_SPECS}
        merged = {item["run"]: item for item in existing if item["run"] in names}
        merged.update({item["run"]: item for item in results})
        report.write_text(json.dumps([merged[k] for k in sorted(merged)], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    shutil.rmtree(scratch, ignore_errors=True)
    failed = [item["run"] for item in results if not item["ok"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} runs {'replayed identically' if args.replay else 'recorded twice identically'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
