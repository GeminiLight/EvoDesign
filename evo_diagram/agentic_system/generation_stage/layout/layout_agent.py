"""
LayoutAgent Implementation (Combined One-Shot)

Stage 3 of the pipeline. Uses the shared skill system prompt and the minimal
``LAYOUT_TASK_PROMPT``; upstream context (Structure + Styling) is passed via
the conversation thread on the workflow state.

Input:
    - conversation_history: multi-turn messages from Structure + Styling
    - structure_instantiation / styling_instantiation: still populated for the
      geometry merge step below; the agent itself no longer reads them for
      prompt composition.
    - user_query: User's intent
    - text_content: Original text

Output:
    - layout_instantiation: Final merged layout with coordinates
"""

import copy
import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.language_models import BaseChatModel

from evo_diagram.agentic_system.common.skill_loader import EVODIAGRAM_SKILL_SYSTEM_PROMPT
from evo_diagram.agentic_system.common.spec_utils import (
    build_assistant_content,
    parse_stage_output,
)
from evo_diagram.agentic_system.common.layout_contract import (
    is_layout_edge_entry,
    validate_layout_instantiation,
)
from evo_diagram.agentic_system.common.semantic_ids import ICON_SUFFIX
from evo_diagram.agentic_system.generation_stage.layout.prompts import LAYOUT_TASK_PROMPT
from evo_diagram.core.base_agent import BaseAgent, _render_template
from .state import WorkflowState

logger = logging.getLogger(__name__)


class LayoutAgent(BaseAgent):
    """
    One-shot layout agent that directly generates coordinates from the
    Structure + Styling conversation context.

    Input: conversation_history, structure_instantiation, styling_instantiation, user_query
    Output: layout_instantiation (merged coordinates JSON)
    """

    def __init__(
        self,
        model: BaseChatModel,
        tools: Optional[List[Any]] = None,
        **kwargs: Any,
    ) -> None:
        exclude_think = kwargs.pop("exclude_think", False)
        json_retry_attempts = kwargs.pop("json_retry_attempts", 5)
        kwargs.setdefault("strict_json_output", True)
        super().__init__(
            model=model,
            system_prompt=EVODIAGRAM_SKILL_SYSTEM_PROMPT,
            task_prompt=LAYOUT_TASK_PROMPT,
            tools=tools,
            exclude_think=exclude_think,
            json_retry_attempts=json_retry_attempts,
            **kwargs,
        )

    def run(self, state: WorkflowState) -> WorkflowState:
        """
        Run the combined layout agent to generate layout coordinates.

        Generates directly from upstream (Structure + Styling) context in one
        LLM call, using the conversation thread from the workflow state.

        Args:
            state: Current workflow state. Expects ``conversation_history``
                to contain Structure and Styling messages, and
                ``styling_instantiation`` for the post-run geometry merge.

        Returns:
            Updated workflow state with layout_instantiation
        """
        input_dict = {
            "text_content": state.text_content or "",
            "user_query": state.user_query or "N/A",
            "content_area": state.content_area or "N/A",
            "stage_knowledge": state.stage_knowledge or "",
            "design_expertise": state.design_expertise or "",
            "runtime_directives": state.runtime_directives or "",
            "size_hints": _build_size_hints_prompt(state.styling_instantiation),
        }

        # Render task prompt
        rendered_task = _render_template(LAYOUT_TASK_PROMPT, input_dict)

        # Continue conversation from styling. When this agent runs standalone
        # (e.g., during single-stage testing), ``conversation_history`` is empty
        # and we must seed the system prompt ourselves; otherwise the LLM call
        # would lack the EvoDiagram skill anchor entirely.
        messages = list(state.conversation_history)
        if not messages or messages[0].get("role") != "system":
            system_prompt = self._system_prompt
            messages.insert(0, {"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": rendered_task})

        logger.info("[LayoutAgent] Invoking LLM...")
        raw_output = self.invoke_with_history(messages)

        parsed = parse_stage_output(
            raw_output,
            stage_name="Layout",
            require_instantiation_dict=True,
            require_flat_id_map=True,
            reject_error_key=True,
        )
        specification = parsed.specification
        layout_instantiation = parsed.instantiation

        if specification:
            state.update_stage("layout_specification", specification)

        # Merge LLM-produced geometry onto the styled element map. The merge
        # has to run after the LLM call because styling owns colours while
        # layout owns x/y/w/h + edge routing — we reconcile both here.
        merged_instantiation = self._merge_layout_with_styling(
            layout_instantiation,
            state.styling_instantiation,
            canvas_library=state.canvas_library,
            structure_instantiation=state.structure_instantiation,
        )

        state.update_stage("layout_instantiation", merged_instantiation)

        # Save conversation history
        assistant_content = build_assistant_content(
            "Layout Design Specification",
            specification,
            merged_instantiation,
        )
        messages.append({"role": "assistant", "content": assistant_content})
        state.conversation_history = messages

        logger.info("[LayoutAgent] Layout generation completed")
        return state

    def _merge_layout_with_styling(
        self,
        layout_instantiation: Dict[str, Any],
        styling_instantiation: Dict[str, Any],
        canvas_library: str = "excalidraw",
        structure_instantiation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Merge LLM layout output with styling data without deterministic fallback rules.
        """
        merged_instantiation = copy.deepcopy(styling_instantiation)

        if not isinstance(layout_instantiation, dict):
            raise ValueError(
                "LayoutAgent expected layout instantiation to be a JSON object; "
                f"got {type(layout_instantiation).__name__}"
            )

        validate_layout_instantiation(
            layout_instantiation,
            structure_instantiation=structure_instantiation,
            styling_instantiation=styling_instantiation,
        )

        structure_edge_ids = {
            edge.get("id")
            for edge in (structure_instantiation or {}).get("edges", []) or []
            if isinstance(edge, dict) and isinstance(edge.get("id"), str)
        }

        for key, value in layout_instantiation.items():
            if key.endswith(ICON_SUFFIX):
                # Icon placement is handled by renderer-side logic.
                continue

            if is_layout_edge_entry(key, value, structure_edge_ids):
                existing_edge = merged_instantiation.get(key)
                edge_value = self._extract_edge_color_only_base(
                    existing_edge if isinstance(existing_edge, dict) else {},
                    canvas_library=canvas_library,
                )
                merged_instantiation[key] = edge_value

                if isinstance(value, dict):
                    if isinstance(value.get("props"), dict):
                        if "props" not in edge_value or not isinstance(edge_value["props"], dict):
                            edge_value["props"] = {}
                        edge_value["props"].update(value["props"])

                    for edge_key, edge_field in value.items():
                        if edge_key == "props":
                            continue
                        edge_value[edge_key] = edge_field
                else:
                    edge_value["value"] = value
                continue

            if key not in merged_instantiation or not isinstance(merged_instantiation[key], dict):
                merged_instantiation[key] = {}

            if not isinstance(value, dict):
                merged_instantiation[key]["value"] = value
                continue

            node_value = merged_instantiation[key]

            self._strip_layout_owned_fields(node_value)

            if "x" in value:
                node_value["x"] = value["x"]
            if "y" in value:
                node_value["y"] = value["y"]

            if canvas_library == "excalidraw":
                if "w" in value:
                    node_value["w"] = value["w"]
                if "h" in value:
                    node_value["h"] = value["h"]
            else:
                if "w" in value or "h" in value:
                    if "props" not in node_value or not isinstance(node_value["props"], dict):
                        node_value["props"] = {}
                    if "w" in value:
                        node_value["props"]["w"] = value["w"]
                    if "h" in value:
                        node_value["props"]["h"] = value["h"]

            if isinstance(value.get("props"), dict):
                if "props" not in node_value or not isinstance(node_value["props"], dict):
                    node_value["props"] = {}
                for prop_key in ("w", "h"):
                    if prop_key in value["props"]:
                        node_value["props"][prop_key] = value["props"][prop_key]

        return merged_instantiation

    @staticmethod
    def _strip_layout_owned_fields(element_value: Dict[str, Any]) -> None:
        """Remove transient size hints and stale geometry from styling data."""
        for field in ("x", "y", "w", "h", "width", "height", "min_width", "min_height"):
            element_value.pop(field, None)

        props = element_value.get("props")
        if isinstance(props, dict):
            for field in ("x", "y", "w", "h", "width", "height", "min_width", "min_height"):
                props.pop(field, None)

    def _extract_edge_color_only_base(
        self,
        edge_value: Dict[str, Any],
        canvas_library: str,
    ) -> Dict[str, Any]:
        """Preserve only styling-owned edge color before layout overwrites geometry."""
        if canvas_library == "excalidraw":
            if isinstance(edge_value.get("strokeColor"), str):
                return {"strokeColor": edge_value["strokeColor"]}
            return {}

        props = edge_value.get("props")
        if isinstance(props, dict) and isinstance(props.get("color"), str):
            return {"props": {"color": props["color"]}}
        return {"props": {}}


def _build_size_hints_prompt(styling_instantiation: Optional[Dict[str, Any]]) -> str:
    if not isinstance(styling_instantiation, dict):
        return "(none)"

    hints: Dict[str, Dict[str, int]] = {}
    for element_id, element_data in styling_instantiation.items():
        if not isinstance(element_id, str) or element_id.endswith(ICON_SUFFIX):
            continue
        if not isinstance(element_data, dict):
            continue
        min_width = element_data.get("min_width")
        min_height = element_data.get("min_height")
        if not isinstance(min_width, int) or not isinstance(min_height, int):
            continue
        hints[element_id] = {
            "min_width": min_width,
            "min_height": min_height,
        }

    if not hints:
        return "(none)"
    return json.dumps(hints, ensure_ascii=False, sort_keys=True)
