"""Export parity fixtures from the Python render engine.

Two fixture kinds, both JSON, written under ``fixtures/`` (gitignored):

* ``stages/<case>.json`` — the Excalidraw render workflow run node by node on
  every example run directory: the initial state and the manifest after each
  node. The TS workflow must reproduce every snapshot.
* ``functions/<python.module>/<function>.jsonl`` — call vectors recorded by
  tracing every function of the migrated modules while the stage runs and the
  engine's own unit tests execute: arguments, return value, arguments after
  the call (functions mutate inputs in place), or the raised exception.

Usage (repo root):
    PYTHONPATH=. .venv/bin/python packages/render-engine/tools/export_fixtures.py
"""
from __future__ import annotations

import dataclasses
import enum
import functools
import hashlib
import importlib
import inspect
import json
import logging
import math
import os
import pathlib
import sys
from copy import deepcopy
from typing import Any, Dict, List

REPO = pathlib.Path(__file__).resolve().parents[3]
OUT = REPO / "packages/render-engine/fixtures"
EXAMPLES = REPO / "examples"

# Python modules whose functions are traced. Keep in sync with MODULE_MAP.md.
TRACED_MODULES = [
    "evodesign.agentic_system.common.semantic_ids",
    "evodesign.agentic_system.common.spec_utils",
    "evodesign.agentic_system.common.diagram_types",
    "evodesign.agentic_system.common.design_constraints",
    "evodesign.agentic_system.common.layout_contract",
    "evodesign.agentic_system.common.node_icons",
    "evodesign.agentic_system.common.icon_assets",
    "evodesign.agentic_system.common.tldraw_utils",
    "evodesign.agentic_system.generation_stage.layout.element_shape_estimator",
    "evodesign.agentic_system.render_engine.shared.order_keys",
    "evodesign.agentic_system.render_engine.shared.label_geometry",
    "evodesign.agentic_system.render_engine.shared.edge_routing",
    "evodesign.agentic_system.render_engine.shared.edge_crossing_detector",
    "evodesign.agentic_system.render_engine.shared.normalization",
    "evodesign.agentic_system.render_engine.shared.icon_url_adder",
    "evodesign.agentic_system.render_engine.shared.render_audit",
    "evodesign.agentic_system.render_engine.excalidraw.converter",
    "evodesign.agentic_system.render_engine.excalidraw.normalizer",
    "evodesign.agentic_system.render_engine.excalidraw.shape_size_fitter",
    "evodesign.agentic_system.render_engine.excalidraw.group_fitter",
    "evodesign.agentic_system.render_engine.excalidraw.group_alignment_normalizer",
    "evodesign.agentic_system.render_engine.excalidraw.layered_layout_compactor",
    "evodesign.agentic_system.render_engine.excalidraw.radial_concept_compactor",
    "evodesign.agentic_system.render_engine.excalidraw.sequence_layout",
    "evodesign.agentic_system.render_engine.excalidraw.edge_router",
    "evodesign.agentic_system.render_engine.excalidraw.arrow_routing.context",
    "evodesign.agentic_system.render_engine.excalidraw.arrow_routing.geometry",
    "evodesign.agentic_system.render_engine.excalidraw.arrow_routing.grid_router",
    "evodesign.agentic_system.render_engine.excalidraw.arrow_routing.detours",
    "evodesign.agentic_system.render_engine.excalidraw.arrow_routing.ports",
    "evodesign.agentic_system.render_engine.excalidraw.arrow_routing.passes",
    "evodesign.agentic_system.render_engine.excalidraw.arrow_routing.labels",
    "evodesign.agentic_system.render_engine.excalidraw.arrow_adder",
    "evodesign.agentic_system.render_engine.excalidraw.architecture_style_normalizer",
    "evodesign.agentic_system.render_engine.excalidraw.architecture_design_system",
    "evodesign.agentic_system.render_engine.excalidraw.caption_placer",
    "evodesign.agentic_system.render_engine.excalidraw.design_theme",
    "evodesign.agentic_system.render_engine.excalidraw.zorder_repair",
    "evodesign.agentic_system.render_engine.excalidraw.validator",
]

FIRST_CALLS = 25          # always keep the first N calls of a function
SAMPLE_EVERY = 97         # then keep every call whose index hashes into 1/N
MAX_PER_FUNCTION = 120
MAX_RECORD_BYTES = 1_500_000


class Unserializable(Exception):
    pass


def encode(value: Any) -> Any:
    """JSON-safe encoding that keeps the Python types TS must distinguish.

    Tuples, sets and non-string-keyed dicts are tagged; non-finite floats and
    -0.0 are tagged; everything else is plain JSON.
    """
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # JSON keeps 1.0 vs 1 apart but JS does not; only values JSON cannot
        # carry are tagged. Hash payload vectors expose any int/float reliance.
        if math.isnan(value) or math.isinf(value) or (value == 0.0 and math.copysign(1.0, value) < 0):
            return {"__float__": repr(value)}
        return value
    if isinstance(value, tuple):
        return {"__tuple__": [encode(item) for item in value]}
    if isinstance(value, list):
        return [encode(item) for item in value]
    if isinstance(value, (set, frozenset)):
        try:
            items = sorted(value)
        except TypeError:
            items = sorted(value, key=repr)
        return {"__set__": [encode(item) for item in items]}
    if isinstance(value, dict):
        if all(isinstance(key, str) for key in value):
            if any(key.startswith("__") and key.endswith("__") for key in value):
                return {"__dict__": [[key, encode(item)] for key, item in value.items()]}
            return {key: encode(item) for key, item in value.items()}
        return {"__dict__": [[encode(key), encode(item)] for key, item in value.items()]}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {"__dataclass__": type(value).__name__,
                "fields": {f.name: encode(getattr(value, f.name)) for f in dataclasses.fields(value)}}
    # Phase 2 encodings (decoded by test/harness/fixtures.ts decode()).
    message = _encode_message(value)
    if message is not None:
        return message
    if isinstance(value, pathlib.PurePath):
        return {"__path__": str(value)}
    if isinstance(value, enum.Enum):
        return {"__enum__": type(value).__name__, "value": encode(value.value)}
    if hasattr(value, "model_dump") and not isinstance(value, type):
        # pydantic v2 model: declared fields only (private attrs excluded).
        return {"__model__": type(value).__name__, "fields": encode(value.model_dump())}
    raise Unserializable(type(value).__name__)


def _encode_message(value: Any) -> Any:
    """langchain BaseMessage → {"__message__": type, "fields": {...}}.

    Only the fields a prompt depends on are kept (content verbatim, plus
    name / tool_calls / tool_call_id when present). Run ids, response metadata
    and usage are provider/transport noise and are dropped.
    """
    BaseMessage = _langchain_message_class()
    if BaseMessage is None or not isinstance(value, BaseMessage):
        return None
    fields: Dict[str, Any] = {"content": encode(value.content)}
    if getattr(value, "name", None):
        fields["name"] = value.name
    tool_calls = getattr(value, "tool_calls", None)
    if tool_calls:
        fields["tool_calls"] = [
            {"name": call.get("name"), "args": encode(call.get("args")), "id": call.get("id")}
            for call in tool_calls
        ]
    if value.type == "tool":
        fields["tool_call_id"] = getattr(value, "tool_call_id", None)
    return {"__message__": value.type, "fields": fields}


_MESSAGE_CLASS: List[Any] = []


def _langchain_message_class():
    if not _MESSAGE_CLASS:
        try:
            from langchain_core.messages import BaseMessage
        except ImportError:  # pragma: no cover - langchain is a project dependency
            BaseMessage = None
        _MESSAGE_CLASS.append(BaseMessage)
    return _MESSAGE_CLASS[0]


class Tracer:
    def __init__(self, modules: List[str] | None = None, *, first_calls: int = FIRST_CALLS,
                 max_per_function: int = MAX_PER_FUNCTION) -> None:
        self.counts: Dict[str, int] = {}
        self.records: Dict[str, List[str]] = {}
        self.source = "examples"
        self.signatures: Dict[str, Any] = {}
        self.modules = list(TRACED_MODULES if modules is None else modules)
        self.first_calls = first_calls
        self.max_per_function = max_per_function

    def keep(self, key: str) -> bool:
        index = self.counts.get(key, 0)
        self.counts[key] = index + 1
        if len(self.records.get(key, ())) >= self.max_per_function:
            return False
        if index < self.first_calls:
            return True
        digest = hashlib.sha1(f"{key}:{index}".encode()).digest()
        return digest[0] * 256 + digest[1] < 65536 // SAMPLE_EVERY

    def wrap(self, key: str, func):
        tracer = self

        @functools.wraps(func)
        def traced(*args, **kwargs):
            if not tracer.keep(key):
                return func(*args, **kwargs)
            try:
                before = {"args": encode(list(args)), "kwargs": encode(kwargs)}
            except Unserializable:
                return func(*args, **kwargs)
            except RecursionError:
                return func(*args, **kwargs)
            except Exception:  # noqa: BLE001 - encoding must never change behavior
                return func(*args, **kwargs)
            try:
                result = func(*args, **kwargs)
            except Exception as exc:  # recorded, then re-raised unchanged
                tracer.add(key, {**before, "raises": type(exc).__name__, "message": str(exc)[:300]})
                raise
            try:
                record = {
                    **before,
                    "result": encode(result),
                    "args_after": encode(list(args)),
                    "kwargs_after": encode(kwargs),
                }
            except Exception:  # noqa: BLE001 - Unserializable, RecursionError, model_dump errors
                return result
            tracer.add(key, record)
            return result

        traced.__wrapped_original__ = func
        return traced

    def add(self, key: str, record: Dict[str, Any]) -> None:
        record["source"] = self.source
        line = json.dumps(record, ensure_ascii=False, allow_nan=False)
        if len(line) <= MAX_RECORD_BYTES:
            self.records.setdefault(key, []).append(line)

    def signature(self, key: str, func) -> None:
        try:
            params = inspect.signature(func).parameters.values()
        except (TypeError, ValueError):
            return
        self.signatures[key] = [
            {"name": p.name, "kind": p.kind.name, "has_default": p.default is not inspect.Parameter.empty}
            for p in params
        ]

    def install(self) -> None:
        originals: Dict[int, Any] = {}
        for name in self.modules:
            module = importlib.import_module(name)
            for attr, obj in list(vars(module).items()):
                if inspect.isfunction(obj) and obj.__module__ == name:
                    self.signature(f"{name}/{attr}", obj)
                    wrapped = self.wrap(f"{name}/{attr}", obj)
                    originals[id(obj)] = wrapped
                    setattr(module, attr, wrapped)
                elif inspect.isclass(obj) and obj.__module__ == name:
                    for method_name, method in list(vars(obj).items()):
                        if inspect.isfunction(method) and not method_name.startswith("__"):
                            self.signature(f"{name}/{attr}.{method_name}", method)
                            setattr(obj, method_name, self.wrap(f"{name}/{attr}.{method_name}", method))
        # Rebind names other modules imported with ``from x import f``.
        for module in list(sys.modules.values()):
            if not getattr(module, "__name__", "").startswith("evodesign"):
                continue
            for attr, obj in list(vars(module).items()):
                if inspect.isfunction(obj) and id(obj) in originals:
                    setattr(module, attr, originals[id(obj)])

    def write(self) -> None:
        root = OUT / "functions"
        for key, lines in self.records.items():
            module, func = key.split("/", 1)
            path = root / module / f"{func}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        summary = {key: {"calls": self.counts[key], "vectors": len(self.records.get(key, []))}
                   for key in sorted(self.counts)}
        (OUT / "functions" / "_summary.json").write_text(json.dumps(summary, indent=1))
        (OUT / "functions" / "_signatures.json").write_text(json.dumps(self.signatures, indent=1))

    # ── phase 2: per-run partial traces merged by the exporter ──
    def write_partial(self, path: pathlib.Path) -> None:
        path.write_text(json.dumps({"counts": self.counts, "records": self.records,
                                    "signatures": self.signatures}, ensure_ascii=False), encoding="utf-8")

    def merge_partial(self, partial: Dict[str, Any], cap: int) -> None:
        for key, count in partial["counts"].items():
            self.counts[key] = self.counts.get(key, 0) + count
        for key, lines in partial["records"].items():
            bucket = self.records.setdefault(key, [])
            bucket.extend(lines[: max(0, cap - len(bucket))])
        self.signatures.update(partial["signatures"])

    def write_merged(self, modules: List[str]) -> None:
        """Write only ``modules``' directories; merge _summary/_signatures.

        Directories of other modules (phase 1) are never touched.
        """
        root = OUT / "functions"
        wanted = set(modules)
        for module in modules:
            directory = root / module
            if directory.is_dir():
                for stale in directory.glob("*.jsonl"):
                    stale.unlink()
        for key, lines in self.records.items():
            module, func = key.split("/", 1)
            if module not in wanted or not lines:
                continue
            path = root / module / f"{func}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        summary_path, signatures_path = root / "_summary.json", root / "_signatures.json"
        summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
        signatures = json.loads(signatures_path.read_text()) if signatures_path.exists() else {}
        for key in list(summary):
            if key.split("/", 1)[0] in wanted:
                del summary[key]
        for key in list(signatures):
            if key.split("/", 1)[0] in wanted:
                del signatures[key]
        summary.update({key: {"calls": self.counts[key], "vectors": len(self.records.get(key, []))}
                        for key in sorted(self.counts) if key.split("/", 1)[0] in wanted})
        signatures.update({key: value for key, value in self.signatures.items() if key.split("/", 1)[0] in wanted})
        summary_path.write_text(json.dumps(dict(sorted(summary.items())), indent=1))
        signatures_path.write_text(json.dumps(dict(sorted(signatures.items())), indent=1))


def case_inputs():
    load = lambda path: json.loads(path.read_text(encoding="utf-8"))
    for layout in sorted(EXAMPLES.rglob("3_layout/layout_instantiation.json")):
        run = layout.parent.parent
        structure = load(run / "1_structure/structure_instantiation.json")
        spec = run / "3_layout/layout_specification.json"
        case = str(run.relative_to(EXAMPLES)).replace("/", "__")
        yield case, {
            "structure_instantiation": structure,
            "layout_instantiation": load(layout),
            "layout_specification": load(spec) if spec.exists() else None,
            "design_constraints": "",
        }


def export_stages(tracer: Tracer) -> None:
    from evodesign.agentic_system.render_engine.state import WorkflowState
    from evodesign.agentic_system.render_engine.workflow import RenderWorkflow

    workflow = RenderWorkflow(canvas_library="excalidraw")
    out = OUT / "stages"
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for case, inputs in case_inputs():
        state = WorkflowState(**deepcopy(inputs), canvas_library="excalidraw")
        snapshots = []
        error = None
        for node, run in workflow._excalidraw_nodes():
            try:
                state = run(state)
            except Exception as exc:
                error = {"node": node, "raises": type(exc).__name__, "message": str(exc)[:500]}
                break
            snapshots.append({
                "node": node,
                "layout_instantiation": deepcopy(state.layout_instantiation),
                "diagram_manifest": deepcopy(state.diagram_manifest),
                "validation_report": deepcopy(state.validation_report),
            })
        (out / f"{case}.json").write_text(json.dumps(
            {"case": case, "input": inputs, "snapshots": snapshots, "error": error},
            ensure_ascii=False,
        ), encoding="utf-8")
        index.append({"case": case, "chart_type": inputs["structure_instantiation"].get("chart_type"),
                      "nodes": len(snapshots), "error": error})
    (out / "_index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False))


def run_unit_tests(tracer: Tracer) -> int:
    import pytest

    tracer.source = "pytest"
    return pytest.main([
        "-q", "-p", "no:cacheprovider",
        str(REPO / "evodesign/tests/render_engine"),
        str(REPO / "evodesign/tests/refinement"),
    ])


def phase2_modules() -> List[str]:
    manifest = json.loads((REPO / "packages/render-engine/migration/modules.json").read_text(encoding="utf-8"))
    return [entry["python"] for entry in manifest["modules"] if entry.get("phase") == 2 and entry.get("python")]


PHASE2_TRACED_MODULES = phase2_modules()
PHASE2_TEST_DIRS = ["generation", "verification", "refinement", "core", "config", "utils", "common"]
PHASE2_RUN_CAP = 120      # vectors per function from the recorded runs
PHASE2_PYTEST_CAP = 60    # additional vectors per function from pytest


def export_phase2() -> None:
    """Phase-2 vectors: replay every recorded run under tracing, then pytest.

    Each run is replayed from its cassette in a subprocess (tools/record_runs.py
    worker, ``--trace``); the replay must reproduce the recorded fixtures
    exactly, otherwise tracing changed behavior and nothing is written. Then
    the phase-2 unit tests run in-process under the same tracer and must all
    pass. Only phase-2 module directories under fixtures/functions/ are
    rewritten; _summary.json/_signatures.json are merged.
    """
    import shutil
    import subprocess
    import tempfile

    sys.path.insert(0, str(REPO / "packages/render-engine/tools"))
    import record_runs

    modules = PHASE2_TRACED_MODULES
    tracer = Tracer(modules)
    runs_root = record_runs.RUNS
    specs = {spec["name"]: spec for spec in record_runs.RUN_SPECS}
    names = sorted(p.name for p in runs_root.iterdir() if (p / "cassette.jsonl").exists() and p.name in specs)
    if not names:
        raise SystemExit("no recorded runs under fixtures/runs; run tools/record_runs.py first")
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="evodesign-trace-"))
    render_url = os.environ.get("EXCALIDRAW_RENDER_URL", record_runs.DEFAULT_RENDER_URL)
    failures = []
    for name in names:
        dest = scratch / name
        outcome = record_runs.spawn(specs[name], "replay", dest, runs_root / name, render_url, trace=True)
        problems = [] if outcome["code"] == 0 else [f"exit {outcome['code']}: {outcome['tail'][-800:]}"]
        if dest.exists():
            problems += record_runs.compare_dirs(runs_root / name, dest)
        partial_path = dest / "_vectors.json"
        if not problems and partial_path.exists():
            partial = json.loads(partial_path.read_text(encoding="utf-8"))
            for key in partial["records"]:
                partial["records"][key] = [
                    json.dumps({**json.loads(line), "source": f"run:{name}"}, ensure_ascii=False, allow_nan=False)
                    for line in partial["records"][key]
                ]
            tracer.merge_partial(partial, PHASE2_RUN_CAP)
        if problems:
            failures.append((name, problems[:5]))
        print(f"{'OK  ' if not problems else 'FAIL'} traced replay {name}", flush=True)
    shutil.rmtree(scratch, ignore_errors=True)
    if failures:
        for name, problems in failures:
            print(name, problems)
        raise SystemExit("traced replays diverged from the recorded runs; vectors not written")

    import pytest

    tracer.install()
    tracer.source = "pytest"
    tracer.max_per_function = PHASE2_RUN_CAP + PHASE2_PYTEST_CAP
    code = pytest.main(["-q", "-p", "no:cacheprovider", *[str(REPO / "evodesign/tests" / d) for d in PHASE2_TEST_DIRS]])
    if code != 0:
        raise SystemExit("phase-2 unit tests failed under tracing; fixtures not written")
    tracer.write_merged(modules)
    covered = {key.split("/", 1)[0] for key, lines in tracer.records.items() if lines}
    print(f"phase-2 vectors written for {len(covered)}/{len(modules)} modules, "
          f"{sum(len(v) for v in tracer.records.values())} vectors")


def main() -> None:
    logging.disable(logging.CRITICAL)
    os.chdir(REPO)
    if "--phase2" in sys.argv[1:]:
        export_phase2()
        return
    tracer = Tracer()
    tracer.install()
    export_stages(tracer)
    if run_unit_tests(tracer) != 0:
        # Tracing must be invisible; a failing test means vectors are suspect.
        raise SystemExit("unit tests failed under tracing; fixtures not written")
    tracer.write()
    print(f"fixtures written to {OUT}")


if __name__ == "__main__":
    main()
