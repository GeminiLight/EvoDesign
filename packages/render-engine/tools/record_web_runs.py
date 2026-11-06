"""Record (and replay) the backend web generation flow (``POST /diagram/generate/stream``).

Phase 3 (PHASE3_PLAN.md WP26): the browser runtime must emit exactly what the
backend's full-mode streaming endpoint emits. Every case in WEB_SPECS drives
the real backend code in-process:

    app.api.v1.endpoints.diagram.generate_diagram_stream (undecorated, guest)
      → WorkflowGenerateService.generate_without_render_streaming
      → WorkflowEngineAdapter.stream_without_render
      → workflow_runtime/* → Text2DiagramWorkflow (stepwise) / VerifierWorkflow / IterativeRefinerWorkflow
      → DiagramStreamService.rewrite_chunk (guest: pass-through, no persistence)
      → with_sse_keepalive (the StreamingResponse body iterator)

Recording conditions (PHASE3_PLAN.md WP26):

* **No database, no persistence** ("直接调用 adapter 层" option): the request is
  a guest request (``current_user=None``), so ``DiagramStreamService`` never
  persists and DNA rules are never loaded. The endpoint's ``db`` and
  ``guest_quota`` dependencies are stand-ins (commit/rollback no-ops, unlimited
  quota) exactly like tests/backend/test_diagram_endpoint.py; nothing touches
  a database file.
* **Design memory off**: ``design_memory_enabled=False``,
  ``design_memory_learning=False`` (memory stage reports ``status=disabled``).
* **Settings**: a ``Settings`` object built without any .env file
  (``_env_file=None``); every LLM field is a fixed non-secret placeholder.
  ``auto_refine_enabled`` / ``auto_refine_max_iterations`` come from the spec
  (backend default: enabled, 2), ``retain_generation_artifacts=False``
  (production default: the per-request directory is deleted at the end).
* **Model**: every chat model is the phase-2 cassette model
  (tools/llm_cassette.py; answers synthesized by tools/cassette_synth.py from
  ``examples/configured-model/<case>/`` in record mode, recorded answers in
  replay mode). Zero real LLM calls.
* **Renderer**: the normal renderer subprocess against
  ``EXCALIDRAW_RENDER_URL`` = http://127.0.0.1:3001/renderers/excalidraw.
* **Engine options**: the backend always builds ``Text2DiagramWorkflow`` with
  its defaults (multiagent, critic on). The unified (oneshot) and critic-off
  cases inject ``mode`` / ``enable_critic`` through the adapter's own
  dependency-injection point (``WorkflowEngineAdapter(streaming_dependency_loader=…)``
  returning the production ``StreamingEngineDependencies`` with
  ``workflow_cls = functools.partial(Text2DiagramWorkflow, **engine)``).
  No backend code is changed. NOTE: the backend streaming path supports the
  stepwise pipeline only, so a oneshot workflow ends in the generic
  ``error`` event — that *is* the backend behaviour being recorded.

Output per case, ``fixtures/web_runs/<case>/``::

    input.json        spec, HTTP request body, settings, engine options, environment
    cassette.jsonl    one line per LLM call (same format as fixtures/runs)
    images/           image parts sent to the model, by sha256
    events.jsonl      SSE events in order: {"index", "event", "llm_calls", "data"}; ``llm_calls`` =
                      LLM calls made before the event was emitted (keepalive comments dropped)
    result.json       {"result": <result event data> | null, "error": <error event data> | null}
    artifacts/        the request-scoped work directory just before the adapter
                      deletes it (normalized), + artifacts.json index — the
                      rendered PNG the frontend would show, manifests, reports
    frontend.json     what apiDiagramService.generateDiagramStream reads from the
                      result event (the fields mapped into DiagramResponse) and the
                      sequence of StreamCallbacks it would fire

Normalization: tools/run_normalize.py rules plus WebNormalizer below
(``req_<12 hex>`` request ids, wall-clock ``*_ms`` / ``timings_ms`` values).

Usage (repo root)::

    PYTHONPATH=. .venv/bin/python packages/render-engine/tools/record_web_runs.py            # record all twice + compare
    ... record_web_runs.py --run flow_x1                # one case (substring match)
    ... record_web_runs.py --replay                     # replay every case from its cassette, compare
    ... record_web_runs.py --list
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional

TOOLS = pathlib.Path(__file__).resolve().parent
PACKAGE = TOOLS.parent
REPO = TOOLS.parents[2]
BACKEND = REPO / "backend"
WEB_RUNS = PACKAGE / "fixtures" / "web_runs"
DEFAULT_RENDER_URL = "http://127.0.0.1:3001/renderers/excalidraw"

sys.path.insert(0, str(TOOLS))
from record_runs import CASSETTE_ENV, case_root, compare_dirs, png_info  # noqa: E402
from run_normalize import Normalizer  # noqa: E402

# Settings values that are not secrets but must look like real values
# (Settings rejects placeholders such as "changeme").
FIXED_SETTINGS: Dict[str, Any] = {
    "jwt_secret": "web-run-fixture-jwt-0f3a9c1e7b",
    "session_secret": "web-run-fixture-session-6d2b8e4a1c",
    "llm_model_name": "cassette-model",
    "llm_model_provider": "openai",
    "llm_api_key": "cassette-not-a-key",
    "llm_endpoint_url": "http://127.0.0.1:9/v1",
    "llm_temperature": 0.0,
    "llm_max_tokens": 16384,
    "llm_reasoning_effort": None,
    "llm_thinking": None,
    "canvas_library": "excalidraw",
    "design_memory_enabled": False,
    "design_memory_learning": False,
    "retain_generation_artifacts": False,
    "guest_daily_generation_limit": 10,
    # Never opened (guest requests do not persist); pinned because the
    # cassette environment blanks DB_TYPE/DB_NAME/HOST to keep the repo .env out.
    "db_type": "sqlite",
    "db_name": "web-run-fixture-unused",
    "host": "127.0.0.1",
}


def _web(name: str, case: str, **options: Any) -> Dict[str, Any]:
    spec = {
        "name": name,
        "case": case,
        "router": False,              # True: request diagram_type=null → RouterAgent runs
        "refiner": True,              # Settings.auto_refine_enabled (backend default True)
        "refiner_iterations": 2,      # Settings.auto_refine_max_iterations (backend default 2)
        "engine": {},                 # Text2DiagramWorkflow kwargs injected via the engine port
        "use_icons": None,            # None: true iff the case styling has :icon entries
        "dna": [],                    # extra requirement lines (frontend Design DNA section)
        "locked_nodes": [],
        "current_schema": None,       # "case" → the case's own diagram manifest as the current canvas
        "faults": [],
        "critic_scores": [],
        "refiner_edits": None,
        "layout_format": "full",
        "expect": "result",           # result | error (which terminal event the case must end with)
        "notes": "",
    }
    spec.update(options)
    return spec


# A refiner edit list that never settles: every iteration moves the same node
# (the refiner keeps finding new work and runs out of iterations).
_NEVER_SETTLES = [
    [{"op": "set_position", "id": "7c536a61fd38c319b571", "payload": {"x": 500, "y": 170},
      "rationale": "cassette: overlap a neighbour"}],
    [{"op": "set_position", "id": "7c536a61fd38c319b571", "payload": {"x": 520, "y": 190},
      "rationale": "cassette: still overlapping"}],
    [{"op": "set_position", "id": "7c536a61fd38c319b571", "payload": {"x": 540, "y": 210},
      "rationale": "cassette: still overlapping"}],
]

WEB_SPECS: List[Dict[str, Any]] = [
    # ── multiagent, explicit diagram type ──────────────────────────────────
    _web("flow_x1__web", "flow_x1", notes="flowchart, explicit type, backend defaults (refiner on)"),
    _web("paper_full_f2__web", "paper_full_f2", notes="architecture"),
    _web("t_er_ty__web", "t_er_ty", notes="er_diagram"),
    _web("t_orgchart_ty__web", "t_orgchart_ty", notes="orgchart"),
    _web("t_sequence_tz__web", "t_sequence_tz", notes="sequence_diagram"),
    _web("t_swimlane_ty__web", "t_swimlane_ty", notes="swimlane"),
    _web("cy_flywheel_ty2__web", "cy_flywheel_ty2", notes="cycle"),
    _web("plain_ecommerce__web_icons", "plain-ecommerce", use_icons=True, notes="architecture with groups, icons on"),
    _web("dp_k8s_ty1__web_dna", "dp_k8s_ty1",
         dna=["", "Apply these enabled user Design DNA rules when relevant. Treat them as preferences, not diagram content to render verbatim:",
              "Structure:", "- Group by layer: Keep control plane and workers apart",
              "Style:", "- Calm palette: Prefer muted fills"],
         notes="deployment; requirements carry a frontend Design DNA section"),
    _web("t_state_tz__web_locked", "t_state_tz", current_schema="case",
         locked_nodes=["7c536a61fd38c319b571", "9f935c092cbdc07814f7"],
         notes="state_diagram regenerated over the current canvas with locked nodes (runtime directives)"),
    # ── router (diagram_type omitted / 'automated') ─────────────────────────
    _web("flow_h1__web_router", "flow_h1", router=True, notes="flowchart through RouterAgent"),
    _web("quickstart_service__web_router", "quickstart-service", router=True, notes="architecture with groups via router"),
    _web("t_mindmap_ty__web_router", "t_mindmap_ty", router=True, notes="mindmap via router"),
    # ── settings / engine switches ──────────────────────────────────────────
    _web("kb_sprint_ty1__web_norefine", "kb_sprint_ty1", refiner=False,
         notes="kanban, AUTO_REFINE_ENABLED=false → refiner_skipped event"),
    _web("sm_course_ty1__web_nocritic", "sm_course_ty1", engine={"enable_critic": False},
         notes="story_map, critic off (engine enable_critic=False)"),
    _web("ls_web_ty2__web_nocritic_norefine", "ls_web_ty2", refiner=False, engine={"enable_critic": False},
         notes="layer_stack, critic off and refiner off"),
    # ── JSON repair inside generation ───────────────────────────────────────
    _web("t_funnel_ty__web_repair", "t_funnel_ty", router=True,
         faults=[{"caller": "RouterAgent", "call": 1, "kind": "trailing_comma"},
                 {"caller": "StructureAgent", "call": 1, "kind": "fenced_prose"},
                 {"caller": "LayoutAgent", "call": 1, "kind": "truncated"},
                 {"caller": "VerifierCriticAgent", "call": 1, "kind": "not_json"}],
         notes="funnel; malformed router/structure/layout/critic answers → JSON repair and resampling"),
    # ── verification fails → refinement ─────────────────────────────────────
    _web("hcai_demo__web_refine", "hcai_demo", notes="flowchart; critic below target → refinement with recorded LLM edits"),
    _web("t_class_tz__web_refine_resolved", "t_class_tz", critic_scores=[5.0, 8.0],
         notes="class_diagram; low critic score → refinement → final verification passes (status completed)"),
    _web("t_state_tz__web_refine_unresolved", "t_state_tz", refiner_iterations=2, critic_scores=[5.0, 5.0, 5.0],
         refiner_edits=_NEVER_SETTLES,
         notes="state_diagram; edits never settle → refiner not converged (status unresolved)"),
    _web("t_er_tz__web_refine_regress", "t_er_tz", critic_scores=[6.0, 4.0],
         notes="er_diagram; refined candidate scores lower → refine_error + status failed (base diagram kept)"),
    _web("t_swot_ty__web_refine_llm_error", "t_swot_ty",
         faults=[{"caller": "RefinerLLMAgent", "call": n, "kind": "llm_error"} for n in range(1, 7)],
         critic_scores=[5.0],
         notes="swot; refiner LLM keeps failing → refiner outcome recorded as-is"),
    _web("big_en_aes__web_refine", "big_en_aes", refiner_iterations=3,
         notes="architecture; refinement loop with recorded LLM edits (3 iterations)"),
    # ── unified / oneshot (engine mode injected) ────────────────────────────
    _web("ecommerce_aes__web_unified", "ecommerce_aes", engine={"mode": "oneshot"}, expect="error",
         notes="unified (oneshot) workflow: backend streaming supports the stepwise pipeline only → generation error event"),
    _web("flow_x2__web_unified_router", "flow_x2", engine={"mode": "oneshot"}, router=True, expect="error",
         notes="unified + router: same generation error event"),
    # ── generation stage errors ─────────────────────────────────────────────
    _web("t_timeline_ty__web_structure_error", "t_timeline_ty",
         faults=[{"caller": "StructureAgent", "call": n, "kind": "not_json"} for n in range(1, 9)],
         expect="error", notes="timeline; Structure never returns JSON → structure stage error event"),
    _web("t_matrix_ty__web_layout_error", "t_matrix_ty",
         faults=[{"caller": "LayoutAgent", "call": n, "kind": "not_json"} for n in range(1, 9)],
         expect="error", notes="matrix; Layout never returns JSON → layout stage error event"),
    _web("t_fishbone_ty__web_styling_llm_error", "t_fishbone_ty",
         faults=[{"caller": "StylingAgent", "call": n, "kind": "llm_error"} for n in range(1, 9)],
         expect="error", notes="fishbone; Styling model call raises → styling stage error event"),
]


# ── normalization ─────────────────────────────────────────────────────────

REQUEST_ID_RE = re.compile(r"req_[0-9a-f]{12}")


class WebNormalizer(Normalizer):
    """tools/run_normalize.py rules + web-only rules (test/harness/web_runs.ts mirrors these).

    7. ``req_<12 hex>`` request ids → ``req_<ID>`` (WorkflowGenerateService uses uuid4).
    8. Any JSON member whose key ends in ``_ms`` with a numeric value → 0, and
       every numeric value directly inside a ``timings_ms`` object → 0
       (stage_complete.duration_ms, generation report timings/optimizations).
    """

    def text(self, value: str) -> str:
        return REQUEST_ID_RE.sub("req_<ID>", super().text(value))

    def value(self, value: Any) -> Any:
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                numeric = isinstance(item, (int, float)) and not isinstance(item, bool)
                if numeric and (key.endswith("_ms") or key == "elapsed_seconds"):
                    out[key] = 0
                elif key == "timings_ms" and isinstance(item, dict):
                    out[key] = {k: (0 if isinstance(v, (int, float)) and not isinstance(v, bool) else self.value(v))
                                for k, v in item.items()}
                else:
                    out[key] = self.value(item)
            return out
        return super().value(value)


# ── worker (one case, in a subprocess) ────────────────────────────────────


def case_uses_icons(case: Any) -> bool:
    return any(str(key).endswith(":icon") for key in (case.styling or {}))


def build_request(spec: Dict[str, Any], case: Any) -> Dict[str, Any]:
    """The JSON body apiDiagramService.buildGenerateDiagramPayload would send."""
    from cassette_synth import synthesize_input

    text = synthesize_input(case)
    diagram_type = None if spec["router"] else case.chart_type
    requirements = "\n".join([f"Create a {diagram_type or 'automated'} diagram that visualizes the provided text.", *spec["dna"]])
    current_schema = None
    if spec["current_schema"] == "case":
        manifest = case.render_manifest or {}
        current_schema = {"type": "excalidraw", "version": 2, "elements": manifest.get("elements", []),
                          "appState": {"viewBackgroundColor": "#ffffff"}, "files": manifest.get("files") or {}}
    use_icons = case_uses_icons(case) if spec["use_icons"] is None else spec["use_icons"]
    return {
        "context": text["content"],
        "diagram_type": diagram_type,
        "use_icons": use_icons,
        "requirements": requirements,
        "locked_nodes": list(spec["locked_nodes"]),
        "project_id": None,
        "current_schema": current_schema,
        "canvas_library": "excalidraw",
    }


def build_settings(spec: Dict[str, Any], results_dir: str):
    from app.config import Settings

    return Settings(_env_file=None, **FIXED_SETTINGS, results_dir=results_dir,
                    auto_refine_enabled=bool(spec["refiner"]),
                    auto_refine_max_iterations=int(spec["refiner_iterations"]))


def settings_record(settings: Any) -> Dict[str, Any]:
    keys = ["llm_model_name", "llm_model_provider", "llm_endpoint_url", "llm_temperature", "llm_max_tokens",
            "llm_reasoning_effort", "llm_thinking", "canvas_library", "auto_refine_enabled", "auto_refine_max_iterations",
            "design_memory_enabled", "design_memory_learning", "retain_generation_artifacts", "results_dir"]
    record = {key: getattr(settings, key) for key in keys}
    record["llm_api_key"] = "<redacted>"
    return record


def run_environment(spec: Dict[str, Any], render_url: str) -> Dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "TMPDIR": os.environ.get("TMPDIR", tempfile.gettempdir()),
        "PYTHONPATH": os.pathsep.join([str(REPO), str(BACKEND), str(TOOLS)]),
        "EXCALIDRAW_RENDER_URL": render_url,
        "LANG": "en_US.UTF-8",
        **CASSETTE_ENV,
        # The backend reads settings from the Settings object built by the
        # worker; ENABLE_REFINER only matters for evodesign's own config and
        # is pinned so the repo .env cannot leak in.
        "ENABLE_REFINER": "true" if spec["refiner"] else "false",
    }
    for name in ("PLAYWRIGHT_BROWSERS_PATH", "NODE_PATH", "npm_config_cache"):
        if os.environ.get(name):
            env[name] = os.environ[name]
    return env


class _FixtureSession:
    """Request DB session stand-in: admission only commits/rolls back (no DB)."""

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _UnlimitedGuestQuota:
    async def consume(self, db: Any, *, client_ip: str, limit: int, secret: str) -> int:
        return 1


def _install_llm_error_fault() -> None:
    """Extend the synthesizer with an ``llm_error`` fault: the model call raises.

    Implemented here (not in cassette_synth.py, which phase 2 owns): the
    response is a recorded ``{"error": {"type": "ValueError", ...}}`` entry,
    replayed by both the Python cassette and test/harness/cassette.ts.
    """
    import cassette_synth

    original = cassette_synth.Synthesizer._fault

    def _fault(self, fault, caller, entry):
        if fault["kind"] == "llm_error":
            return {"response": {"error": {"type": "ValueError", "message": "provider rejected the request (cassette fault)"}},
                    "source": "synthesized-error", "note": "fault:llm_error"}
        return original(self, fault, caller, entry)

    cassette_synth.Synthesizer._fault = _fault


def worker(spec: Dict[str, Any], mode: str, dest: pathlib.Path, source: Optional[pathlib.Path]) -> int:
    import asyncio
    import functools
    import logging
    from dataclasses import replace

    import llm_cassette
    from cassette_synth import CaseArtifacts, Synthesizer

    os.chdir(REPO)
    for path in (str(BACKEND), str(REPO)):
        if path not in sys.path:
            sys.path.insert(0, path)
    _install_llm_error_fault()
    case = CaseArtifacts(spec["case"], root=case_root(spec["case"]).parent)
    work = pathlib.Path(tempfile.mkdtemp(prefix="evodesign-web-"))
    results_dir = work / "results"
    capture = work / "captured"
    normalizer = WebNormalizer(work)
    dest.mkdir(parents=True, exist_ok=True)

    if mode == "record":
        session = llm_cassette.CassetteSession(dest, mode="record", responder=Synthesizer(case, spec))
    else:
        assert source is not None
        session = llm_cassette.CassetteSession.load(source)
        session.directory = dest
        session.images = llm_cassette.ImageStore(dest)
    llm_cassette.install(session)

    from loguru import logger as loguru_logger

    loguru_logger.remove()
    loguru_logger.add(sys.stderr, level="WARNING")
    logging.getLogger().setLevel(logging.WARNING)

    from app.api.v1.endpoints.diagram import generate_diagram_stream
    from app.core.sse import parse_sse_event
    from app.schemas.diagram_generate import DiagramGenerateRequest
    from app.services import workflow_engine_adapter as adapter_module
    from app.services.diagram_stream_service import DiagramStreamService
    from app.services.workflow_engine_adapter import WorkflowEngineAdapter
    from app.services.workflow_engine_port import EvoDesignWorkflowEnginePort
    from app.services.workflow_generate_service import WorkflowGenerateService

    # Keep a copy of the per-request directory right before the adapter deletes it.
    original_cleanup = adapter_module._cleanup_stream_dir
    cleaned: List[str] = []

    def capture_then_cleanup(save_dir: str) -> None:
        if os.path.isdir(save_dir) and not capture.exists():
            shutil.copytree(save_dir, capture)
        cleaned.append(save_dir)
        original_cleanup(save_dir)

    adapter_module._cleanup_stream_dir = capture_then_cleanup

    body_json = build_request(spec, case)
    body = DiagramGenerateRequest.model_validate(body_json)
    settings = build_settings(spec, str(results_dir))
    port = EvoDesignWorkflowEnginePort()
    loader = port.load_streaming_dependencies
    if spec["engine"]:
        def loader():  # noqa: F811 - engine options through the adapter's injection point
            deps = port.load_streaming_dependencies()
            return replace(deps, workflow_cls=functools.partial(deps.workflow_cls, **spec["engine"]))
    adapter = WorkflowEngineAdapter(results_dir=settings.results_dir, streaming_dependency_loader=loader)
    workflow_service = WorkflowGenerateService(settings=settings, engine_adapter=adapter)

    async def drive() -> List[Any]:
        response = await generate_diagram_stream.__wrapped__(
            request=object(), body=body, current_user=None, db=_FixtureSession(), settings=settings,
            guest_quota=_UnlimitedGuestQuota(), workflow_service=workflow_service,
            stream_service=DiagramStreamService(),
        )
        assert response.media_type == "text/event-stream"
        chunks: List[Any] = []
        async for chunk in response.body_iterator:
            # LLM calls made before this chunk reached the client: fixes the
            # interleaving of model calls and events (the adapter generator is
            # suspended between chunks, so the count is exact).
            chunks.append((chunk if isinstance(chunk, str) else chunk.decode("utf-8"), len(session.entries)))
        return chunks

    harness_error: Optional[str] = None
    try:
        chunks = asyncio.run(drive())
    except llm_cassette.CassetteMismatch as exc:
        harness_error = f"CassetteMismatch: {exc}"
        chunks = []

    events: List[Dict[str, Any]] = []
    keepalives = 0
    for chunk, llm_calls in chunks:
        if chunk == ": keepalive\n\n":
            keepalives += 1
            continue
        parsed = parse_sse_event(chunk)
        if parsed is None or not chunk.endswith("\n\n"):
            harness_error = harness_error or f"unparseable SSE chunk: {chunk[:200]!r}"
            continue
        events.append({"index": len(events), "event": parsed.event, "llm_calls": llm_calls, "data": normalizer.value(parsed.data)})

    result_event = next((e["data"] for e in events if e["event"] == "result"), None)
    error_event = next((e["data"] for e in events if e["event"] == "error"), None)

    # ── write fixture directory ──
    session.write(dest)
    with open(dest / "events.jsonl", "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    (dest / "result.json").write_text(json.dumps({"result": result_event, "error": error_event}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (dest / "frontend.json").write_text(json.dumps(frontend_view(events), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_artifacts(capture, dest, normalizer)
    (dest / "input.json").write_text(json.dumps(normalizer.value({
        "run": spec["name"],
        "spec": spec,
        "endpoint": "POST /api/v1/diagram/generate/stream",
        "user": None,
        "request": body_json,
        "settings": settings_record(settings),
        "engine": spec["engine"],
        "env": {k: v for k, v in run_environment(spec, os.environ.get("EXCALIDRAW_RENDER_URL", DEFAULT_RENDER_URL)).items()
                if k not in {"PATH", "HOME", "TMPDIR", "PYTHONPATH", "LANG"}},
        "models_yaml": "configs/models.yaml",
        "settings_yaml": "configs/settings.yaml",
        "normalization": "tools/run_normalize.py + tools/record_web_runs.py WebNormalizer",
    }), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    meta = {"keepalives": keepalives, "work_dir_removed": bool(cleaned) and not any(os.path.exists(p) for p in cleaned),
            "harness_error": harness_error}
    (dest / "_meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    if session.mismatch:
        (dest / "mismatch.json").write_text(json.dumps(session.mismatch, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    if harness_error:
        print(harness_error, file=sys.stderr)
    return 2 if (session.mismatch or harness_error) else 0


def frontend_view(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """What frontend/src/services/apiDiagramService.ts generateDiagramStream does with the stream.

    ``callbacks``: the StreamCallbacks it fires, in order (``error`` ends the
    stream with an ApiError). ``response``: the result fields it maps into
    DiagramResponse (schema_blob is split into the Excalidraw payload there).
    """
    callback_names = {"stage_start": "onStageStart", "stage_complete": "onStageComplete", "refine_complete": "onRefineComplete",
                      "refine_error": "onRefineError", "refiner_skipped": "onRefinerSkipped", "result": "onResult", "error": "onError"}
    callbacks: List[str] = []
    for event in events:
        callbacks.append(callback_names.get(event["event"], f"<ignored {event['event']}>"))
        if event["event"] == "error":
            break
    result = next((e["data"] for e in events if e["event"] == "result"), None)
    response = None
    if result is not None and not any(e["event"] == "error" for e in events):
        response = {
            "generationReport": (result.get("metrics_scores") or {}).get("generation"),
            "requestId": result.get("request_id"),
            "projectId": result.get("project_id"),
            "snapshotId": result.get("snapshot_id"),
            "excalidraw": {"elements": len((result.get("schema_blob") or {}).get("elements") or []),
                           "files": sorted(((result.get("schema_blob") or {}).get("files") or {}).keys())},
            "summary": result.get("summary") or "Generated successfully",
            "persistError": result.get("persist_error") or False,
        }
    error = next((e["data"] for e in events if e["event"] == "error"), None)
    return {"callbacks": callbacks, "response": response,
            "throws": None if error is None else {"message": "Generation stage failed", "status": 500,
                                                  "detail": error.get("detail") or error.get("message"),
                                                  "code": "generation_stage_failed"}}


def write_artifacts(capture: pathlib.Path, dest: pathlib.Path, normalizer: WebNormalizer) -> None:
    artifacts_dir = dest / "artifacts"
    if artifacts_dir.exists():
        shutil.rmtree(artifacts_dir)
    index = []
    files = sorted(p for p in capture.rglob("*") if p.is_file()) if capture.exists() else []
    for path in files:
        rel = path.relative_to(capture).as_posix()
        target = artifacts_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        entry: Dict[str, Any] = {"path": rel}
        if path.suffix in {".json", ".excalidraw"}:
            data = normalizer.value(json.loads(path.read_text(encoding="utf-8")))
            target.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            entry["kind"] = "json"
        elif path.suffix in {".md", ".txt", ".log"}:
            target.write_text(normalizer.text(path.read_text(encoding="utf-8")), encoding="utf-8")
            entry["kind"] = "text"
        elif path.suffix == ".png":
            shutil.copyfile(path, target)
            entry.update(kind="png", **png_info(path))
        else:
            shutil.copyfile(path, target)
            entry["kind"] = "binary"
        entry["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        index.append(entry)
    (dest / "artifacts.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")


# ── driver ───────────────────────────────────────────────────────────────


def spawn(spec: Dict[str, Any], mode: str, dest: pathlib.Path, source: Optional[pathlib.Path], render_url: str) -> Dict[str, Any]:
    started = time.monotonic()
    command = [sys.executable, str(TOOLS / "record_web_runs.py"), "--worker", spec["name"], "--worker-mode", mode, "--dest", str(dest)]
    if source is not None:
        command += ["--source", str(source)]
    completed = subprocess.run(command, env=run_environment(spec, render_url), cwd=REPO,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log = completed.stdout
    logs = WEB_RUNS / "_logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / f"{spec['name']}.{mode}.log").write_text(log, encoding="utf-8")
    return {"run": spec["name"], "mode": mode, "code": completed.returncode, "seconds": round(time.monotonic() - started, 1),
            "tail": log[-3000:] if completed.returncode else ""}


def check_expectation(spec: Dict[str, Any], directory: pathlib.Path) -> List[str]:
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines() if line]
    if not events:
        return ["no SSE events"]
    last = events[-1]["event"]
    if last != spec["expect"]:
        return [f"expected the stream to end with {spec['expect']!r}, got {last!r}"]
    return []


def record_one(spec: Dict[str, Any], render_url: str, scratch: pathlib.Path) -> Dict[str, Any]:
    dest = WEB_RUNS / spec["name"]
    if dest.exists():
        shutil.rmtree(dest)
    first = spawn(spec, "record", dest, None, render_url)
    if first["code"] != 0:
        return {**first, "ok": False, "problems": ["first recording failed"]}
    second_dir = scratch / spec["name"]
    second = spawn(spec, "record", second_dir, None, render_url)
    if second["code"] != 0:
        return {**second, "ok": False, "problems": ["second recording failed"]}
    problems = check_expectation(spec, dest) + compare_dirs(dest, second_dir)
    shutil.rmtree(second_dir, ignore_errors=True)
    return {"run": spec["name"], "ok": not problems, "problems": problems[:20],
            "seconds": round(first["seconds"] + second["seconds"], 1), **summarize(dest)}


def replay_one(spec: Dict[str, Any], render_url: str, scratch: pathlib.Path) -> Dict[str, Any]:
    source = WEB_RUNS / spec["name"]
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
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines() if line]
    callers: Dict[str, int] = {}
    for entry in entries:
        callers[entry["caller"]] = callers.get(entry["caller"], 0) + 1
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    generation = (((result.get("result") or {}).get("metrics_scores") or {}).get("generation") or {})
    refine = next((e["data"] for e in events if e["event"] == "refine_complete"), None)
    return {
        "llm_calls": len(entries),
        "callers": callers,
        "sources": sorted({entry.get("source") for entry in entries}),
        "events": [e["event"] + (f":{e['data'].get('stage')}" if isinstance(e["data"], dict) and e["data"].get("stage") else "") for e in events],
        "artifacts": len(json.loads((directory / "artifacts.json").read_text(encoding="utf-8"))),
        "quality_status": generation.get("quality_status"),
        "refine_status": (refine or {}).get("status"),
        "error": result.get("error"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", action="append", help="substring of case names (repeatable)")
    parser.add_argument("--replay", action="store_true", help="replay recorded cases from their cassettes and compare")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--render-url", default=os.environ.get("EXCALIDRAW_RENDER_URL", DEFAULT_RENDER_URL))
    parser.add_argument("--worker")
    parser.add_argument("--worker-mode", choices=["record", "replay"])
    parser.add_argument("--dest")
    parser.add_argument("--source")
    args = parser.parse_args()

    if args.worker:
        spec = next(s for s in WEB_SPECS if s["name"] == args.worker)
        return worker(spec, args.worker_mode, pathlib.Path(args.dest), pathlib.Path(args.source) if args.source else None)

    if ":3000" in args.render_url:
        raise SystemExit("refusing to use the port-3000 renderer; use 3001")
    specs = [s for s in WEB_SPECS if not args.run or any(part in s["name"] for part in args.run)]
    if args.list:
        for spec in specs:
            print(f"{spec['name']:42} expect={spec['expect']:6} {spec['notes']}")
        return 0
    WEB_RUNS.mkdir(parents=True, exist_ok=True)
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="evodesign-web-record-"))
    job = replay_one if args.replay else record_one
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {pool.submit(job, spec, args.render_url, scratch): spec for spec in specs}
        for future in concurrent.futures.as_completed(futures):
            outcome = future.result()
            results.append(outcome)
            status = "OK  " if outcome["ok"] else "FAIL"
            print(f"{status} {outcome['run']:42} {outcome.get('seconds')}s {'; '.join(outcome.get('problems', [])[:3])}", flush=True)
            if not outcome["ok"] and outcome.get("tail"):
                print(outcome["tail"][-1500:], flush=True)
    results.sort(key=lambda item: item["run"])
    report = WEB_RUNS / ("_replay.json" if args.replay else "_index.json")
    names = {spec["name"] for spec in WEB_SPECS}
    existing = json.loads(report.read_text(encoding="utf-8")) if report.exists() and args.run else []
    merged = {item["run"]: item for item in existing if item["run"] in names}
    merged.update({item["run"]: {k: v for k, v in item.items() if k != "tail"} for item in results})
    report.write_text(json.dumps([merged[k] for k in sorted(merged)], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    shutil.rmtree(scratch, ignore_errors=True)
    failed = [item["run"] for item in results if not item["ok"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} cases {'replayed identically' if args.replay else 'recorded twice identically'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
