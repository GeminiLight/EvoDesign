"""
StylingAgent Implementation (Unified One-Shot)

Generates styling and icon decisions in a single LLM call.
"""

import logging
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.language_models import BaseChatModel

from evo_diagram.agentic_system.common.skill_loader import EVODIAGRAM_SKILL_SYSTEM_PROMPT
from evo_diagram.agentic_system.common.spec_utils import (
    build_assistant_content,
    build_stage_messages,
    parse_stage_output,
    unwrap_structure_instantiation,
)
from evo_diagram.agentic_system.common.icon_assets import (
    ICON_FALLBACK_NAME,
    icon_name_exists,
)
from evo_diagram.agentic_system.common.semantic_ids import (
    ICON_SUFFIX,
    TITLE_SUFFIX,
    companion_id,
)
from evo_diagram.agentic_system.generation_stage.styling.prompts import build_styling_task_prompt
from evo_diagram.agentic_system.generation_stage.router import DEFAULT_PALETTE_KEY
from evo_diagram.agentic_system.common.tldraw_utils import TLDrawColorValidator
from evo_diagram.core.base_agent import BaseAgent, _render_template
from .icon_colors import DEFAULT_ICON_COLOR, resolve_icon_color_name
from .schemas import StylingValidationError, validate_styling_instantiation
from .state import WorkflowState
from ..compact_decisions import expand_styling_output, use_compact_decisions
from evo_diagram.agentic_system.common.node_icons import bundled_icons

logger = logging.getLogger(__name__)

# Icon configuration
ICON_NAME_PATTERN = re.compile(r"[^a-z0-9_]")


class StylingAgent(BaseAgent):
    """
    Combined Styling Agent: Directly generates styling from semantic topology.

    Input: conversation_history (with Structure messages), structure_instantiation, text_content, user_query
    Output: styling_instantiation (styling JSON + normalized :icon entries)

    Note: Icon URLs are added later by render_engine/shared/icon_url_adder.py
    """

    def __init__(
        self,
        model: BaseChatModel,
        tools: Optional[List[Any]] = None,
        use_icons: bool = False,
        **kwargs: Any,
    ) -> None:
        self.use_icons = use_icons
        kwargs.setdefault("strict_json_output", True)
        super().__init__(
            model=model,
            system_prompt=EVODIAGRAM_SKILL_SYSTEM_PROMPT,
            task_prompt=build_styling_task_prompt(
                use_icons=use_icons,
                palette_key=DEFAULT_PALETTE_KEY,
            ),
            tools=tools,
            **kwargs,
        )

    def _normalize_icon_name(self, icon_name: Any) -> str:
        """Normalize icon name and ensure the icon file exists; fallback when invalid."""
        if not isinstance(icon_name, str):
            return ICON_FALLBACK_NAME

        normalized = icon_name.strip().lower().replace("-", "_").replace(" ", "_")
        normalized = ICON_NAME_PATTERN.sub("", normalized)
        if not normalized:
            return ICON_FALLBACK_NAME

        if icon_name_exists(normalized):
            return normalized
        return ICON_FALLBACK_NAME

    def _resolve_icon_name_and_color(
        self,
        icon_payload: Any,
        fallback_color: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Resolve icon name and color from flexible payload formats."""
        icon_name: Optional[str] = None
        icon_color: Optional[str] = None

        if isinstance(icon_payload, str):
            icon_name = icon_payload
        elif isinstance(icon_payload, dict):
            payload = icon_payload
            props = payload.get("props") if isinstance(payload.get("props"), dict) else payload

            icon_name = (
                props.get("icon")
                or props.get("icon_name")
                or props.get("name")
            )
            icon_color = props.get("color") or props.get("icon_color")

        normalized_name = self._normalize_icon_name(icon_name)
        normalized_color = resolve_icon_color_name(
            icon_color if icon_color else (fallback_color or DEFAULT_ICON_COLOR)
        )
        return normalized_name, normalized_color

    def _build_icon_entry(self, icon_payload: Any, host_element: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Build normalized :icon entry with icon name and color.

        ``props.color`` is an icon *asset directory* key, never a render colour:
        the renderer resolves it through ``icon_assets.color_to_icon_folder``.
        It therefore always holds a colour name, including on Excalidraw where
        the host node's ``strokeColor`` is a hex — writing the raw hex through
        made every Excalidraw icon fall back to the black directory.

        Note: Icon URLs are added later by render_engine/shared/icon_url_adder.py
        """
        # Prefer the host element's strokeColor as icon color — the LLM
        # often emits generic "black" instead of the actual palette color.
        host_color = None
        if isinstance(host_element, dict):
            host_color = host_element.get("strokeColor")
            if not host_color:
                props = host_element.get("props")
                if isinstance(props, dict):
                    host_color = props.get("color")

        icon_name, icon_color = self._resolve_icon_name_and_color(
            icon_payload, fallback_color=host_color,
        )

        # If the LLM provided a generic/default color but the host has a
        # palette color, prefer the host's color for visual coherence.
        if host_color and icon_color == DEFAULT_ICON_COLOR:
            icon_color = resolve_icon_color_name(host_color)

        return {
            "type": "icon",
            "props": {
                "icon": icon_name,
                "color": icon_color,
            },
        }

    def _is_icon_key(self, key: str) -> bool:
        return key.endswith(ICON_SUFFIX)

    def _postprocess_styling_json(self, styling_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize icon payloads into dedicated `<element_id>:icon` entries.

        Supports:
        1) Nested `props.icon` on element nodes.
        2) Direct canonical icon entries (`<id>:icon`).
        """
        processed: Dict[str, Any] = {}
        extracted_icons = 0
        normalized_icons = 0

        # Pass 1: copy non-icon entries and extract nested props.icon
        for element_id, element_data in styling_json.items():
            if self._is_icon_key(element_id):
                continue

            copied = deepcopy(element_data)
            processed[element_id] = copied

            if not isinstance(copied, dict):
                continue

            props = copied.get("props")
            if not isinstance(props, dict) or "icon" not in props:
                continue

            raw_icon = props.pop("icon")
            icon_entry_key = companion_id(element_id, ICON_SUFFIX)
            processed[icon_entry_key] = self._build_icon_entry(raw_icon, copied)
            extracted_icons += 1

        # Pass 2: normalize direct icon keys; direct icon output takes priority
        for element_id, element_data in styling_json.items():
            if not self._is_icon_key(element_id):
                continue

            base_key = element_id[: -len(ICON_SUFFIX)]
            processed[element_id] = self._build_icon_entry(element_data, processed.get(base_key))
            normalized_icons += 1

        if extracted_icons or normalized_icons:
            logger.info(
                "[StylingAgent] Post-processing: "
                f"extracted {extracted_icons} nested icons, "
                f"normalized {normalized_icons} direct icon entries"
            )

        return processed

    def _record_error(self, state: WorkflowState, message: str) -> None:
        """Record failures on states that expose Structure-style error hooks."""
        add_error = getattr(state, "add_error", None)
        if callable(add_error):
            add_error(message)

    def _collect_structure_edge_ids(
        self,
        structure_instantiation: Optional[Dict[str, Any]],
    ) -> set[str]:
        structure = unwrap_structure_instantiation(structure_instantiation)

        edge_ids: set[str] = set()
        for edge in structure.get("edges") or []:
            if isinstance(edge, dict) and isinstance(edge.get("id"), str):
                edge_ids.add(edge["id"])
        return edge_ids

    def _sanitize_edge_styling(
        self,
        styling_json: Dict[str, Any],
        canvas_library: str,
        structure_instantiation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Keep only edge color in styling output; layout owns all other edge fields."""
        sanitized: Dict[str, Any] = {}
        sanitized_edge_count = 0
        structure_edge_ids = self._collect_structure_edge_ids(structure_instantiation)

        for element_id, element_data in styling_json.items():
            is_structure_edge = isinstance(element_id, str) and element_id in structure_edge_ids
            is_edge_like = isinstance(element_id, str) and element_id.startswith("edge:")
            if not ((is_structure_edge or is_edge_like) and isinstance(element_data, dict)):
                sanitized[element_id] = element_data
                continue

            if canvas_library == "excalidraw":
                edge_entry: Dict[str, Any] = {}
                if isinstance(element_data.get("strokeColor"), str):
                    edge_entry["strokeColor"] = element_data["strokeColor"]
            else:
                edge_entry = {}
                props = element_data.get("props")
                if isinstance(props, dict) and isinstance(props.get("color"), str):
                    edge_entry["props"] = {
                        "color": TLDrawColorValidator.normalize_color(props["color"])
                    }

            sanitized[element_id] = edge_entry
            removed_fields = len(element_data.keys()) - len(edge_entry.keys())
            if removed_fields > 0:
                sanitized_edge_count += 1

        if sanitized_edge_count:
            logger.info(
                "[StylingAgent] Edge sanitization: "
                f"reduced {sanitized_edge_count} edge entries to color-only styling"
            )

        return sanitized

    def _inject_labels_from_structure(
        self,
        styling_json: Dict[str, Any],
        structure_instantiation: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Copy label strings from Structure output into matching styling entries.

        The renderer looks up labels at element_data.label.text.  If the LLM
        didn't provide one, we seed it from the semantic graph.

        Edge labels are deliberately NOT seeded here. Styling edge entries are
        colour-only by contract, so ``_sanitize_edge_styling`` strips any label
        written here within the same ``run()``. The edge-label fallback lives in
        ``LayoutAgent._merge_layout_with_styling`` instead, where the layout edge
        entry that the renderer actually reads is assembled.
        """
        if not isinstance(styling_json, dict) or not isinstance(structure_instantiation, dict):
            return styling_json

        structure_instantiation = unwrap_structure_instantiation(structure_instantiation)

        def _set_label(entry: Dict[str, Any], label_text: str) -> None:
            if not label_text:
                return
            existing = entry.get("label")
            if isinstance(existing, dict) and existing.get("text"):
                return  # Respect anything the LLM already set.
            entry["label"] = {**(existing if isinstance(existing, dict) else {}), "text": label_text}

        # Nodes
        for node in structure_instantiation.get("nodes", []) or []:
            if not isinstance(node, dict):
                continue
            node_id = node.get("id")
            if not isinstance(node_id, str):
                continue
            entry = styling_json.get(node_id)
            if isinstance(entry, dict):
                _set_label(entry, node.get("label", ""))

        # Groups: label attaches to the :title entry
        for group in structure_instantiation.get("groups", []) or []:
            if not isinstance(group, dict):
                continue
            group_id = group.get("id")
            if not isinstance(group_id, str):
                continue
            label_text = group.get("label", "")
            for candidate in (companion_id(group_id, TITLE_SUFFIX), group_id):
                entry = styling_json.get(candidate)
                if isinstance(entry, dict) and (entry.get("type") == "text" or entry.get("shape") == "text"):
                    _set_label(entry, label_text)
                    break

        # Edges: intentionally skipped — see the docstring. Layout owns the edge
        # entry the renderer reads, so the fallback belongs there.

        return styling_json

    def run(self, state: WorkflowState) -> WorkflowState:
        """
        Run the combined styling agent to generate styling JSON and icon entries.

        Args:
            state: Current workflow state with the canonical Structure output
                and specification for context and label/id reconciliation.

        Returns:
            Updated workflow state with styling_instantiation and an extended
            ``conversation_history``.
        """
        input_dict = {
            "text_content": state.text_content or "",
            "user_query": state.user_query or "N/A",
            "content_area": state.content_area or "N/A",
            "stage_knowledge": state.stage_knowledge or "",
            "design_expertise": state.design_expertise or "",
            "runtime_directives": state.runtime_directives or "",
        }

        compact = use_compact_decisions(state.structure_instantiation, state.canvas_library)

        # Render task prompt with the router-selected or explicit default
        # palette card. The prompt builder rejects missing/unknown palettes.
        rendered_task = build_styling_task_prompt(
            use_icons=self.use_icons,
            palette_key=state.palette_key or "",
            canvas_library=state.canvas_library,
            compact=compact,
        )
        rendered_task = _render_template(rendered_task, input_dict)

        messages = build_stage_messages(self._system_prompt, rendered_task, [
            ("Structure", state.structure_specification, state.structure_instantiation),
        ])

        logger.info("[StylingAgent] Invoking LLM...")
        raw_output = self.invoke_with_history(messages)

        try:
            if compact:
                raw_output = expand_styling_output(raw_output, state.structure_instantiation)
            parsed = parse_stage_output(
                raw_output,
                stage_name="Styling",
                require_instantiation_dict=True,
                require_flat_id_map=True,
                reject_error_key=True,
            )
        except ValueError as exc:
            self._record_error(state, str(exc))
            raise StylingValidationError(str(exc)) from exc

        specification = parsed.specification
        styling_json = parsed.instantiation

        if specification:
            state.update_stage("styling_specification", specification)

        styling_json = self._inject_labels_from_structure(
            styling_json,
            state.structure_instantiation,
        )
        styling_json = self._postprocess_styling_json(styling_json)
        # An unchecked option is a hard contract, even if the model or a
        # retrieved design memory happens to suggest decorative icons.
        structure = unwrap_structure_instantiation(state.structure_instantiation)
        node_ids = {n["id"] for n in structure.get("nodes", [])}
        for key in list(styling_json):
            if not key.endswith(ICON_SUFFIX):
                continue
            host = key[:-len(ICON_SUFFIX)]
            entry = styling_json[key]
            name = (entry.get("props") or {}).get("icon")
            eligible = self.use_icons and host in node_ids
            if state.canvas_library == "excalidraw":
                eligible = eligible and styling_json.get(host, {}).get("shape") in {"rectangle", "ellipse"} and name in bundled_icons()
            # Coverage is a design preference, not a safety limit. The prompt
            # prefers sparse icons, but explicit user coverage must survive.
            if not eligible:
                del styling_json[key]
        styling_json = self._sanitize_edge_styling(
            styling_json,
            canvas_library=state.canvas_library,
            structure_instantiation=state.structure_instantiation,
        )
        try:
            styling_json = validate_styling_instantiation(
                styling_json,
                state.structure_instantiation,
                canvas_library=state.canvas_library,
            )
        except StylingValidationError as exc:
            self._record_error(state, str(exc))
            raise

        state.update_stage("styling_instantiation", styling_json)

        # Save conversation history
        assistant_content = build_assistant_content(
            "Styling Design Specification",
            specification,
            styling_json,
        )
        messages.append({"role": "assistant", "content": assistant_content})
        state.conversation_history = messages

        return state
