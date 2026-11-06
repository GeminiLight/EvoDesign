"""Synthesize LLM responses from examples/configured-model/<case>/ artifacts.

Each agent parses a specific output contract; the synthesizer answers in
exactly that contract, using the artifacts a real model produced for the case:

* RouterAgent           ``{"diagram_type", "palette_key", "reasoning", "retrieval_query"}``
                        (diagram type = 1_structure chart_type, palette = 2_styling palette_name)
* StructureAgent        ``{"specification", "instantiation"}`` from 1_structure/
* StylingAgent          same, from 2_styling/
* LayoutAgent           same, from 3_layout/ (``layout_format`` may re-encode it
                        as the compact ``[x,y,w,h]`` / ``[side,side]`` tuples)
* UnifiedGenerator      excalidraw clipboard + ``_meta.structure_instantiation`` /
                        ``_meta.id_map`` built from 4_render/diagram_manifest.json
* VerifierCriticAgent   the critique in 6_verification/ (8_final_verification/
                        for the second verification), scores overridable
* RefinerLLMAgent       a JSON array of the ``llm_edits`` the case's
                        7_refiner/refiner_report.json recorded per iteration

A run spec can inject deliberate faults (``faults``): malformed JSON that
exercises BaseAgent's JSON-repair turn, the critic/refiner resample loop and
the native-scene continuation path. Faults are matched by caller and by the
1-based call number of that caller.
"""
from __future__ import annotations

import copy
import json
import pathlib
from typing import Any, Dict, List, Optional

REPO = pathlib.Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "examples" / "configured-model"


def _load(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


class CaseArtifacts:
    def __init__(self, case: str, root: pathlib.Path = EXAMPLES) -> None:
        self.case = case
        self.dir = root / case
        if not self.dir.is_dir():
            raise FileNotFoundError(self.dir)
        self.structure_spec = _load(self.dir / "1_structure/structure_specification.json") or {}
        self.structure = _load(self.dir / "1_structure/structure_instantiation.json")
        self.styling_spec = _load(self.dir / "2_styling/styling_specification.json") or {}
        self.styling = _load(self.dir / "2_styling/styling_instantiation.json")
        self.layout_spec = _load(self.dir / "3_layout/layout_specification.json") or {}
        self.layout = _load(self.dir / "3_layout/layout_instantiation.json")
        self.render_manifest = _load(self.dir / "4_render/diagram_manifest.json")
        self.verifier = _load(self.dir / "6_verification/verifier_report.json")
        self.final_verifier = _load(self.dir / "8_final_verification/verifier_report.json")
        self.refiner = _load(self.dir / "7_refiner/refiner_report.json")

    @property
    def chart_type(self) -> str:
        return (self.structure or {}).get("chart_type") or ""

    def palette(self) -> Optional[str]:
        system = self.styling_spec.get("color_and_stroke_system") if isinstance(self.styling_spec, dict) else None
        name = system.get("palette_name") if isinstance(system, dict) else None
        return name if isinstance(name, str) else None


def synthesize_input(case: CaseArtifacts) -> Dict[str, str]:
    """Deterministic dataset item text for a case.

    The original source texts are not in the repository; the run input is
    rebuilt from the case's own Structure evidence (fact_ledger evidence,
    then node labels), which is what the recorded Structure answer encodes.
    """
    lines: List[str] = []
    typology = case.structure_spec.get("semantic_typology") if isinstance(case.structure_spec, dict) else None
    for fact in (typology or {}).get("fact_ledger", []) or []:
        evidence = fact.get("evidence") if isinstance(fact, dict) else None
        if isinstance(evidence, str) and evidence.strip() and evidence.strip() not in lines:
            lines.append(evidence.strip())
    if not lines:
        for node in (case.structure or {}).get("nodes", []):
            label = node.get("label") if isinstance(node, dict) else None
            if isinstance(label, str) and label.strip() and label.strip() not in lines:
                lines.append(label.strip())
    return {
        "content": "\n".join(lines),
        "query": f"Draw this content as a clear {case.chart_type.replace('_', ' ')} diagram.",
    }


class SynthesisError(BaseException):
    """A synthesizer bug: must abort the run, never look like a model error."""


class Synthesizer:
    """Responder for llm_cassette.CassetteSession in record mode."""

    def __init__(self, case: CaseArtifacts, spec: Dict[str, Any]) -> None:
        self.case = case
        self.spec = spec
        self.calls: Dict[str, int] = {}
        self.answered: Dict[str, int] = {}  # well-formed answers per caller

    # -- public -------------------------------------------------------------
    def __call__(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        caller = entry["caller"]
        number = self.calls[caller] = self.calls.get(caller, 0) + 1
        for fault in self.spec.get("faults", []):
            if fault["caller"] == caller and fault["call"] == number:
                return self._fault(fault, caller, entry)
        handler = getattr(self, f"_answer_{caller}", None)
        if handler is None:
            raise SynthesisError(f"no synthesizer for caller {caller!r}")
        try:
            content = handler(entry)
        except Exception as exc:  # noqa: BLE001
            raise SynthesisError(f"{caller}: {type(exc).__name__}: {exc}") from exc
        self.answered[caller] = self.answered.get(caller, 0) + 1
        return {"response": {"content": content}, "source": "synthesized"}

    # -- faults -------------------------------------------------------------
    def _fault(self, fault: Dict[str, Any], caller: str, entry: Dict[str, Any]) -> Dict[str, Any]:
        kind = fault["kind"]
        try:
            good = getattr(self, f"_answer_{caller}")(entry)
        except Exception as exc:  # noqa: BLE001
            raise SynthesisError(f"{caller}: {type(exc).__name__}: {exc}") from exc
        note = f"fault:{kind}"
        if kind == "fenced_prose":       # prose + fenced JSON: strict parse fails
            content = "Here is the result.\n```json\n" + good + "\n```\nLet me know if you need changes."
        elif kind == "trailing_comma":   # invalid JSON
            content = good.rstrip().rstrip("}").rstrip() + ",\n}"
        elif kind == "truncated":        # cut mid-value
            content = good[: max(1, len(good) // 2)]
        elif kind == "not_json":
            content = "I cannot produce JSON for this request."
        elif kind == "empty":
            content = ""
        elif kind == "stream_interrupted":
            # Native scene: provider stream breaks after a partial body.
            cut = fault.get("cut", 0.6)
            partial = good[: int(len(good) * cut)]
            return {
                "response": {"error": {"type": "ConnectionError", "message": "stream interrupted (cassette fault)", "partial": partial}},
                "source": "synthesized-error", "note": note,
            }
        elif kind == "continuation":
            # Answer to a continuation request: the missing suffix of the scene.
            prefix = _assistant_prefix(entry)
            content = good[len(prefix):] if prefix and good.startswith(prefix) else good
            self.answered[caller] = self.answered.get(caller, 0) + 1
            return {"response": {"content": content}, "source": "synthesized", "note": note}
        elif kind == "invalid_scene":
            scene = json.loads(good)
            scene["_meta"]["id_map"].pop(next(iter(scene["_meta"]["id_map"])))
            content = _dumps(scene)
        elif kind == "edit_schema_drift":  # refiner: one item uses a drifted field
            edits = json.loads(good)
            edits.append({"op": "set_position", "id": "drifted", "payload": {"x": 0, "y": 0}, "reason": "drift"})
            content = _dumps(edits)
            self.answered[caller] = self.answered.get(caller, 0) + 1
        else:
            raise ValueError(kind)
        return {"response": {"content": content}, "source": "synthesized-malformed", "note": note}

    # -- answers ------------------------------------------------------------
    def _answer_RouterAgent(self, entry: Dict[str, Any]) -> str:
        router = self.spec.get("router_answer") or {}
        palette = router.get("palette_key") or self.case.palette() or "blush_sage"
        from evodesign.agentic_system.generation_stage.styling.colorful import PALETTE_KEYS

        if palette not in PALETTE_KEYS:
            palette = "blush_sage"
        return _dumps({
            "diagram_type": router.get("diagram_type") or self.case.chart_type,
            "palette_key": palette,
            "reasoning": f"The source describes a {self.case.chart_type} ({self.case.case}).",
            "retrieval_query": f"{self.case.chart_type} diagram layout",
        })

    def _answer_StructureAgent(self, entry: Dict[str, Any]) -> str:
        return _dumps({"specification": self.case.structure_spec, "instantiation": self.case.structure})

    def _answer_StylingAgent(self, entry: Dict[str, Any]) -> str:
        return _dumps({"specification": self.case.styling_spec, "instantiation": self.case.styling})

    def _answer_LayoutAgent(self, entry: Dict[str, Any]) -> str:
        layout = copy.deepcopy(self.case.layout)
        if self.spec.get("layout_format") == "compact":
            layout = _compact_layout(layout, self.case.structure)
        return _dumps({"specification": self.case.layout_spec, "instantiation": layout})

    def _answer_UnifiedGenerator(self, entry: Dict[str, Any]) -> str:
        return _dumps(self.unified_scene())

    def unified_scene(self) -> Dict[str, Any]:
        manifest = copy.deepcopy(self.case.render_manifest)
        meta = manifest.get("_meta") or {}
        id_map = dict(meta.get("id_map") or {})
        # The render manifest keeps arrow ownership on the arrows themselves;
        # the native contract wants it in _meta.id_map as well.
        for element in manifest["elements"]:
            element_meta = element.get("meta") or {}
            if element.get("type") == "arrow" and element_meta.get("semantic_edge_id"):
                for edge_id in [element_meta["semantic_edge_id"], *(element_meta.get("merged_semantic_edge_ids") or [])]:
                    id_map.setdefault(edge_id, element["id"])
        meta = {**meta, "id_map": id_map}
        scene = {
            "type": "excalidraw/clipboard",
            "elements": manifest["elements"],
            "files": manifest.get("files") or {},
            "appState": {"viewBackgroundColor": "#FFFFFF", "gridSize": None},
            "_meta": {
                "structure_instantiation": copy.deepcopy(self.case.structure),
                "id_map": meta.get("id_map") or {},
            },
        }
        return scene

    def _answer_VerifierCriticAgent(self, entry: Dict[str, Any]) -> str:
        number = self.answered.get("VerifierCriticAgent", 0) + 1
        report = self.case.verifier if number == 1 else (self.case.final_verifier or self.case.verifier)
        critique = copy.deepcopy(((report or {}).get("subjective") or {}).get("critique") or (report or {}).get("subjective") or {})
        critique = {key: critique[key] for key in ("structure", "styling", "layout", "overall_score", "summary", "constraint_violations") if key in critique}
        if not critique:
            critique = {
                "structure": {"score": 8, "strengths": [], "weaknesses": [], "suggestions": []},
                "styling": {"score": 8, "strengths": [], "weaknesses": [], "suggestions": []},
                "layout": {"score": 8, "strengths": [], "weaknesses": [], "suggestions": []},
                "overall_score": 8, "summary": "Synthesized critique.", "constraint_violations": [],
            }
        scores = self.spec.get("critic_scores") or []
        if number <= len(scores) and scores[number - 1] is not None:
            critique["overall_score"] = scores[number - 1]
        return _dumps(critique)

    def _answer_RefinerLLMAgent(self, entry: Dict[str, Any]) -> str:
        number = self.answered.get("RefinerLLMAgent", 0) + 1
        custom = self.spec.get("refiner_edits")
        if custom is not None:
            edits = custom[number - 1] if number <= len(custom) else []
            return _dumps(edits)
        iterations = (self.case.refiner or {}).get("iterations") or []
        edits: List[Dict[str, Any]] = []
        if number <= len(iterations):
            for item in iterations[number - 1].get("llm_edits") or []:
                edit = item.get("edit") if isinstance(item, dict) else None
                if isinstance(edit, dict):
                    edits.append({k: v for k, v in edit.items() if k != "source"})
        return _dumps(edits)


def _assistant_prefix(entry: Dict[str, Any]) -> str:
    for message in reversed(entry["request"]["messages"]):
        if message["type"] == "ai" and isinstance(message["content"], str):
            return message["content"]
    return ""


def _compact_layout(layout: Dict[str, Any], structure: Dict[str, Any]) -> Dict[str, Any]:
    """Re-encode boxes as [x,y,w,h] and plain side-to-side edges as [side, side]."""
    edges = {edge["id"]: edge for edge in (structure or {}).get("edges", [])}
    compact: Dict[str, Any] = {}
    for key, value in layout.items():
        if not isinstance(value, dict):
            compact[key] = value
            continue
        if key in edges:
            start, end = value.get("start") or {}, value.get("end") or {}
            extra = set(value) - {"start", "end"}
            if (set(start) <= {"elementId", "side"} and set(end) <= {"elementId", "side"}
                    and start.get("side") and end.get("side") and not extra):
                compact[key] = [start["side"], end["side"]]
                continue
        elif set(value) == {"x", "y", "w", "h"}:
            compact[key] = [value["x"], value["y"], value["w"], value["h"]]
            continue
        compact[key] = value
    return compact
