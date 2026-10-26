"""
LayoutAgent Implementation (Combined One-Shot)

Stage 3 of the pipeline. Uses the shared skill system prompt and the layout
task with complete, validated Structure + Styling artifacts from workflow state.

Input:
    - structure_instantiation / styling_instantiation and their specifications:
      canonical upstream context, also used by the geometry merge.
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
    build_stage_messages,
    parse_stage_output,
    unwrap_structure_instantiation,
)
from evo_diagram.agentic_system.common.layout_contract import (
    is_layout_edge_entry,
    validate_layout_instantiation,
)
from evo_diagram.agentic_system.common.semantic_ids import ICON_SUFFIX
from evo_diagram.agentic_system.generation_stage.layout.prompts import (
    LAYOUT_TASK_PROMPT, COMPACT_FLOW_LAYOUT_TASK_PROMPT,
)
from evo_diagram.agentic_system.generation_stage.layout.viewport_profile import (
    choose_layout_viewport,
)
from evo_diagram.core.base_agent import BaseAgent, _render_template
from .state import WorkflowState
from ..compact_decisions import expand_layout_output, use_compact_decisions
from .flow_grid import supports_flow_grid, expand_flow_grid

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

        Generates directly from canonical Structure + Styling context in one
        LLM call, without replaying their earlier task instructions.

        Args:
            state: Current workflow state with upstream specifications and
                instantiations, also used for the post-run geometry merge.

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
            "viewport_plan": choose_layout_viewport(
                state.structure_instantiation
            ).to_prompt(),
        }

        # Render task prompt
        compact = use_compact_decisions(state.structure_instantiation, state.canvas_library)
        task = COMPACT_FLOW_LAYOUT_TASK_PROMPT if compact else LAYOUT_TASK_PROMPT
        grid = compact and supports_flow_grid(
            unwrap_structure_instantiation(state.structure_instantiation),
            state.styling_instantiation, state.runtime_directives or '',
        )
        if grid:
            from .prompts import FLOW_GRID_LAYOUT_TASK_PROMPT
            task = FLOW_GRID_LAYOUT_TASK_PROMPT
        rendered_task = _render_template(task, input_dict)

        messages = build_stage_messages(self._system_prompt, rendered_task, [
            ("Structure", state.structure_specification, state.structure_instantiation),
            ("Styling", state.styling_specification, state.styling_instantiation),
        ])

        logger.info("[LayoutAgent] Invoking LLM...")
        raw_output = self.invoke_with_history(messages)

        if compact:
            if grid:
                raw_output = expand_flow_grid(raw_output, state.structure_instantiation, state.styling_instantiation)
            raw_output = expand_layout_output(raw_output, state.structure_instantiation)

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
        Merge validated geometry with styling, resolving exact group aliases.
        """
        merged_instantiation = copy.deepcopy(styling_instantiation)

        if not isinstance(layout_instantiation, dict):
            raise ValueError(
                "LayoutAgent expected layout instantiation to be a JSON object; "
                f"got {type(layout_instantiation).__name__}"
            )

        # A logical group and its :background identify the same container.
        # Models sometimes position the logical ID even when Styling emitted
        # only the background. Reconcile that exact alias before strict ID and
        # geometry validation; do not invent geometry or accept unknown IDs.
        layout_instantiation = copy.deepcopy(layout_instantiation)
        structure = unwrap_structure_instantiation(structure_instantiation)
        for group in structure.get("groups", []) or []:
            group_id = group["id"]
            background_id = group_id + ":background"
            if (group_id not in styling_instantiation and background_id in styling_instantiation
                    and group_id in layout_instantiation):
                geometry = layout_instantiation.pop(group_id)
                layout_instantiation.setdefault(background_id, geometry)

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

        self._inject_edge_labels_from_structure(
            merged_instantiation,
            structure_instantiation,
        )

        return merged_instantiation

    @staticmethod
    def _inject_edge_labels_from_structure(
        merged_instantiation: Dict[str, Any],
        structure_instantiation: Optional[Dict[str, Any]],
    ) -> None:
        """Backfill Structure edge labels onto layout edge entries in place.

        The renderer reads edge labels from the layout entry only (see
        ``relations_from_edge_data``), and Styling edge entries are colour-only
        by contract, so this is the single place a Structure edge label can
        survive into the render. Nodes already have a deterministic label
        fallback; without this, a Layout LLM that forgets ``label`` silently
        drops decision-branch conditions such as ``<18`` / ``>=18``.

        Only fills gaps: an explicit Layout label always wins, and an edge that
        Structure left unlabelled stays unlabelled (the "edge labels are
        forbidden by default" rule).
        """
        structure = unwrap_structure_instantiation(structure_instantiation)

        for edge in structure.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            edge_id = edge.get("id")
            label_text = edge.get("label")
            if not isinstance(edge_id, str) or not edge_id:
                continue
            if not isinstance(label_text, str) or not label_text.strip():
                continue

            entry = merged_instantiation.get(edge_id)
            if not isinstance(entry, dict):
                continue

            existing = entry.get("label")
            if isinstance(existing, dict):
                text = existing.get("text")
                if isinstance(text, str) and text.strip():
                    continue
            elif isinstance(existing, str) and existing.strip():
                continue

            entry["label"] = {**(existing if isinstance(existing, dict) else {}), "text": label_text}

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
