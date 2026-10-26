"""
Excalidraw runner for the direct_llm baseline.

A thin function wrapping LLMFactory + DiagramGenerator + the Excalidraw
assembler. Designed to be called by scripts/research/run_round.py one
sample at a time; not a CLI.

Output layout for a single sample:
    output_dir/
        diagram.simplified.json     # LLM raw output (simplified shapes/arrows)
        diagram.excalidraw.json     # Full Excalidraw clipboard scene
        rendered_diagram.png        # Rendered PNG via Playwright

Returns a dict with `output_path`, `scene_path`, `simplified_path`, `errors`.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from baselines.direct_llm.diagram_generator import DiagramGenerator
from baselines.direct_llm.excalidraw_assembler import assemble_excalidraw_scene
from baselines.direct_llm.prompts_excalidraw import SYSTEM_PROMPT, TASK_PROMPT
from baselines.direct_llm.state import WorkflowState

from evo_diagram.canvas_environment import render_canvas_file
from evo_diagram.core.llm_factory import LLMFactory


logger = logging.getLogger(__name__)


def _build_model(model_config: Dict[str, Any]):
    return LLMFactory.create(
        model=model_config.get("model_name"),
        model_provider=model_config.get("provider", "openai"),
        base_url=model_config.get("base_url"),
        api_key=model_config.get("api_key"),
        temperature=model_config.get("temperature", 0.0),
        # Without an explicit max_tokens the provider default (commonly 4096)
        # truncates large scenes, so complex samples fail JSON parsing more
        # often than simple ones. Mirror the EvoDiagram generator instead.
        max_tokens=model_config.get("max_tokens", 16384),
        max_retries=model_config.get("max_retries", 6),
    )


class _ExcalidrawDiagramGenerator(DiagramGenerator):
    """Variant of DiagramGenerator that assembles an Excalidraw scene
    instead of a tldraw snapshot."""

    def run(self, state: WorkflowState) -> WorkflowState:
        try:
            state.status = "generating"
            input_dict = {
                "text_content": state.text_content,
                "user_query": getattr(state, "user_query", ""),
            }
            simplified = self.invoke(input_dict)
            scene = assemble_excalidraw_scene(simplified, seed=0)
            state.output = scene
            state.simplified_output = simplified
            state.status = "completed"
        except Exception as e:
            state.status = "failed"
            state.add_error(f"ExcalidrawDiagramGenerator error: {e}")
            logger.error("Excalidraw direct_llm generation failed", exc_info=True)
        return state


def run_excalidraw_baseline(
    text: str,
    output_dir: Path,
    model_config: Dict[str, Any],
    query: str = "",
) -> Dict[str, Any]:
    """Generate one diagram in Excalidraw form and render it to PNG.

    Parameters
    ----------
    text:
        Input text to visualise.
    output_dir:
        Directory to write artifacts into. Created if missing.
    model_config:
        Dict with `model_name`, `provider`, `base_url`, `api_key`,
        and optional `temperature`.
    query:
        Optional user query/intent string.

    Returns
    -------
    Dict with keys:
        - `simplified_path` -> path to the simplified JSON
        - `scene_path` -> path to the full Excalidraw scene
        - `output_path` -> path to the rendered PNG (or None on failure)
        - `errors` -> list of error strings (empty on success)
    """
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    simplified_path = output_dir / "diagram.simplified.json"
    scene_path = output_dir / "diagram.excalidraw.json"
    png_path = output_dir / "rendered_diagram.png"

    errors: List[str] = []

    model = _build_model(model_config)
    agent = _ExcalidrawDiagramGenerator(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        task_prompt=TASK_PROMPT,
    )

    state = WorkflowState(text_content=text, user_query=query, config=model_config)
    state = agent.run(state)

    if state.has_errors():
        errors.extend(state.get_errors())
    if state.output is None:
        errors.append("Generator returned empty output")
        return {
            "simplified_path": None,
            "scene_path": None,
            "output_path": None,
            "errors": errors,
        }

    with simplified_path.open("w", encoding="utf-8") as f:
        json.dump(state.simplified_output, f, indent=2, ensure_ascii=False)
    with scene_path.open("w", encoding="utf-8") as f:
        json.dump(state.output, f, indent=2, ensure_ascii=False)

    try:
        render_canvas_file(
            input_path=str(scene_path),
            output_path=str(png_path),
            canvas_library="excalidraw",
        )
        rendered: Optional[str] = str(png_path)
    except Exception as e:
        errors.append(f"render failed: {e}")
        logger.error("Excalidraw render failed for %s", output_dir, exc_info=True)
        rendered = None

    return {
        "simplified_path": str(simplified_path),
        "scene_path": str(scene_path),
        "output_path": rendered,
        "errors": errors,
    }
