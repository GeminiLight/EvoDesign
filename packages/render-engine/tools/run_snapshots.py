"""Node snapshots for end-to-end run fixtures.

Two kinds of snapshot are recorded, in execution order, into
``snapshots.jsonl`` (one JSON object per line):

* ``scope: "workflow"`` — after every phase of the top-level orchestrator
  ``Text2DiagramWorkflow`` (it is plain Python, not a LangGraph graph; its
  phases are the "top-level nodes"): ``_run_generation_phase``,
  ``_render_generation_output``, ``_run_verification_phase``,
  ``_run_refinement_phase``, ``_run_final_verification_phase``,
  ``_finalize_outputs``, ``_build_state``. ``value`` is the phase's return value.
* ``scope: "graph"`` — after every node of every LangGraph ``StateGraph`` the
  run executes (structure / styling / layout stage graphs, unified
  ``generate_validate``, verifier ``load_inputs`` … ``build_report``,
  iterative refiner ``load_inputs`` / ``run_iteration`` / ``finalize``, and the
  render engine's own Excalidraw graph). ``graph`` is the state schema
  (``module.Class``), ``value`` is what the node returned.

Values use the fixture encoding of tools/export_fixtures.py (``__model__``,
``__dataclass__``, ``__message__``, ``__tuple__`` …) and then the run
normalization of tools/run_normalize.py. Every line also carries ``seq``.
"""
from __future__ import annotations

import functools
import inspect
import threading
from typing import Any, Callable, Dict, List

WORKFLOW_PHASES = (
    "_run_generation_phase",
    "_render_generation_output",
    "_run_verification_phase",
    "_run_refinement_phase",
    "_run_final_verification_phase",
    "_finalize_outputs",
    "_build_state",
)


class SnapshotRecorder:
    def __init__(self, encode: Callable[[Any], Any], normalize: Callable[[Any], Any]) -> None:
        self.encode = encode
        self.normalize = normalize
        self.records: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self.enabled = True

    def snapshot(self, scope: str, graph: str, node: str, value: Any) -> None:
        if not self.enabled:
            return
        encoded = self.normalize(safe_encode(self.encode, value))
        with self._lock:
            self.records.append({"seq": len(self.records), "scope": scope, "graph": graph, "node": node, "value": encoded})


def safe_encode(encode: Callable[[Any], Any], value: Any) -> Any:
    """Encode; values the fixture encoding cannot carry become a type tag."""
    try:
        return encode(value)
    except Exception:  # noqa: BLE001 - Unserializable or recursion
        pass
    if hasattr(value, "model_dump") and not isinstance(value, type):
        fields = {}
        for name in type(value).model_fields:
            fields[name] = safe_encode(encode, getattr(value, name, None))
        return {"__model__": type(value).__name__, "fields": fields}
    if isinstance(value, dict):
        return {str(k): safe_encode(encode, v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_encode(encode, v) for v in value]
    import dataclasses

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {"__dataclass__": type(value).__name__,
                "fields": {f.name: safe_encode(encode, getattr(value, f.name)) for f in dataclasses.fields(value)}}
    return {"__unserializable__": type(value).__name__}


def install(recorder: SnapshotRecorder) -> None:
    """Patch StateGraph.add_node and the orchestrator phases (process-wide)."""
    from langgraph.graph import StateGraph

    original_add_node = StateGraph.add_node

    def add_node(self, node, action=None, **kwargs):
        if action is None and not isinstance(node, str):
            name = getattr(node, "name", None) or getattr(node, "__name__", None)
            return original_add_node(self, _wrap_node(recorder, self, name, node), **kwargs)
        return original_add_node(self, node, _wrap_node(recorder, self, node, action), **kwargs)

    StateGraph.add_node = add_node

    from evodesign.agentic_system.workflow import Text2DiagramWorkflow

    for phase in WORKFLOW_PHASES:
        original = getattr(Text2DiagramWorkflow, phase)
        setattr(Text2DiagramWorkflow, phase, _wrap_phase(recorder, phase, original))


def _schema_name(graph: Any) -> str:
    schema = getattr(graph, "state_schema", None) or getattr(graph, "schema", None)
    if schema is None:
        return "<unknown>"
    return f"{schema.__module__}.{schema.__qualname__}"


def _wrap_node(recorder: SnapshotRecorder, graph: Any, name: str, action: Any) -> Any:
    if not callable(action) or inspect.iscoroutinefunction(action):
        return action
    schema = _schema_name(graph)

    @functools.wraps(action)
    def node(*args: Any, **kwargs: Any) -> Any:
        result = action(*args, **kwargs)
        recorder.snapshot("graph", schema, name, result)
        return result

    return node


def _wrap_phase(recorder: SnapshotRecorder, phase: str, original: Any) -> Any:
    @functools.wraps(original)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = original(self, *args, **kwargs)
        recorder.snapshot("workflow", "Text2DiagramWorkflow", phase, result)
        return result

    return wrapped
