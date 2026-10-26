import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol

from app.core.exceptions import PublicErrorMixin
from app.services.diagram_generation_contract import (
    CanvasLibrary,
    normalize_canvas_library,
)
from app.services.llm_client import create_backend_llm
from app.services.local_edit_contract import LocalEditResponseError, normalize_local_edit

OperationType = Literal["update", "delete", "add"]
LlmFactory = Callable[[], Any]
LOCAL_EDIT_INVALID_REQUEST_DETAIL = "Local edit request is invalid"
LOCAL_EDIT_INVALID_SELECTION_DETAIL = "Selected nodes were not found"
LOCAL_EDIT_UNSUPPORTED_CANVAS_DETAIL = "Unsupported canvas library"
LOCAL_EDIT_INVALID_SCHEMA_DETAIL = "Current diagram schema is malformed"


class LocalEditValidationError(PublicErrorMixin, ValueError):
    """Raised when a local-edit request is invalid before LLM execution."""

    default_public_detail = LOCAL_EDIT_INVALID_REQUEST_DETAIL


class AsyncChatModel(Protocol):
    async def ainvoke(self, prompt: str) -> Any:
        """Return an LLM response for the given prompt."""
        ...


@dataclass(frozen=True)
class LocalEditResult:
    """Normalized result returned by a local edit operation."""

    modified_nodes: dict[str, Any]
    operation_type: OperationType
    summary: str


class LocalEditService:
    """Service for performing local edits on selected diagram nodes."""

    def __init__(
        self,
        llm: AsyncChatModel | None = None,
        llm_factory: LlmFactory | None = None,
    ):
        self._llm = llm
        self._llm_factory = llm_factory or self._create_llm

    def _create_llm(self):
        """Create an LLM instance using the same config as the workflow service."""
        return create_backend_llm(
            max_tokens=8192,
        )

    def _get_llm(self) -> AsyncChatModel:
        """Return the lazily constructed LLM used for local edits."""
        if self._llm is None:
            self._llm = self._llm_factory()
        return self._llm

    async def edit_local(
        self,
        current_schema: dict[str, Any],
        selected_node_ids: list[str],
        instruction: str,
        canvas_library: str,
    ) -> LocalEditResult:
        """Perform a local edit on selected nodes via a single LLM call."""
        canvas = self._validate_canvas_library(canvas_library)
        selected_nodes = self._extract_nodes(current_schema, selected_node_ids, canvas)

        if not self._has_selected_nodes(selected_nodes, canvas):
            raise LocalEditValidationError(
                f"No nodes found with IDs: {selected_node_ids}",
                public_detail=LOCAL_EDIT_INVALID_SELECTION_DETAIL,
            )

        prompt = self._build_prompt(selected_nodes, instruction, canvas)
        response = await self._get_llm().ainvoke(prompt)
        response_text = response.content if hasattr(response, "content") else str(response)

        modified_nodes = self._parse_response(response_text, canvas)
        modified_nodes = normalize_local_edit(modified_nodes, selected_nodes, current_schema, canvas)
        operation_type = self._detect_operation_type(selected_nodes, modified_nodes, canvas)

        return LocalEditResult(
            modified_nodes=modified_nodes,
            operation_type=operation_type,
            summary=f"Modified {len(selected_node_ids)} node(s): {instruction[:50]}",
        )

    @staticmethod
    def _validate_canvas_library(canvas_library: str) -> CanvasLibrary:
        try:
            return normalize_canvas_library(canvas_library)
        except ValueError as exc:
            raise LocalEditValidationError(
                f"Unsupported canvas library: {canvas_library}",
                public_detail=LOCAL_EDIT_UNSUPPORTED_CANVAS_DETAIL,
            ) from exc

    def _extract_nodes(
        self,
        schema: dict[str, Any],
        node_ids: list[str],
        canvas_library: CanvasLibrary,
    ) -> dict[str, Any]:
        """Extract selected nodes from full schema."""
        if canvas_library == "excalidraw":
            elements = schema.get("elements", [])
            if not isinstance(elements, list):
                raise LocalEditValidationError(
                    "Excalidraw schema 'elements' must be a list",
                    public_detail=LOCAL_EDIT_INVALID_SCHEMA_DETAIL,
                )
            selected = [
                el
                for el in elements
                if isinstance(el, dict) and el.get("id") in node_ids
            ]
            return {"elements": selected}

        document = schema.get("document")
        document_store = (
            document.get("store")
            if isinstance(document, dict) and isinstance(document.get("store"), dict)
            else None
        )
        document_records = (
            document.get("records")
            if isinstance(document, dict) and isinstance(document.get("records"), dict)
            else None
        )
        root_records = schema.get("store") or schema.get("records") or {}
        records = document_store or document_records or root_records
        if not isinstance(records, dict):
            raise LocalEditValidationError(
                "TLDraw records must be an object", public_detail=LOCAL_EDIT_INVALID_SCHEMA_DETAIL,
            )
        selected = {
            key: value
            for key, value in records.items()
            if (
                isinstance(value, dict)
                and value.get("typeName") == "shape"
                and (value.get("id") in node_ids or key in node_ids)
            )
        }
        return {"records": selected}

    @staticmethod
    def _has_selected_nodes(
        selected_nodes: dict[str, Any],
        canvas_library: CanvasLibrary,
    ) -> bool:
        if canvas_library == "excalidraw":
            return bool(selected_nodes.get("elements"))
        return bool(selected_nodes.get("records"))

    def _build_prompt(
        self,
        selected_nodes: dict[str, Any],
        instruction: str,
        canvas_library: CanvasLibrary,
    ) -> str:
        """Build LLM prompt with strict constraints."""
        selected_json = json.dumps(selected_nodes, indent=2, ensure_ascii=False)

        prompt = f"""You are a precise diagram editor. Your task is to modify ONLY the specified nodes according to the user's instruction.

CANVAS FORMAT: {canvas_library}

SELECTED NODES (JSON):
{selected_json}

USER INSTRUCTION:
{instruction}

STRICT CONSTRAINTS:
1. Modify ONLY the nodes listed above - do NOT touch any other nodes
2. Preserve all node IDs exactly as given
3. Return ONLY the modified nodes in valid {canvas_library} JSON format. Omitted nodes are UNCHANGED.
4. For position changes: update x, y coordinates
5. For style changes: update color, strokeColor, backgroundColor, fillStyle, etc.
6. For text changes: update text or label fields
7. For size changes: update width, height properties
8. Do NOT add new nodes unless explicitly requested
9. Delete ONLY when explicitly requested: list selected IDs in a top-level "deleted_ids" array. Never imply deletion by omission.
10. Maintain the same structure as the input

OUTPUT FORMAT:
Return a JSON object with the modified nodes in the same structure as the input.
- For excalidraw: {{"elements": [{{modified elements}}]}}
- For tldraw: {{"records": {{modified records}}}}

For deletions, include "deleted_ids": ["selected-id"] alongside the elements/records container.
Return ONLY valid JSON, no explanations or markdown code blocks."""

        return prompt

    def _parse_response(
        self,
        response_text: str,
        canvas_library: CanvasLibrary,
    ) -> dict[str, Any]:
        """Parse and validate LLM response."""
        parsed = self._extract_json_object(response_text)
        self._validate_response_shape(parsed, canvas_library)
        return parsed

    @staticmethod
    def _extract_json_object(response_text: str) -> dict[str, Any]:
        """Extract the first JSON object from raw text or a fenced code block."""
        candidates = [
            match.group(1)
            for match in re.finditer(
                r"```(?:json)?\s*(.*?)\s*```",
                response_text,
                re.DOTALL | re.IGNORECASE,
            )
        ]
        candidates.append(response_text)

        decoder = json.JSONDecoder()
        for candidate in candidates:
            for index, char in enumerate(candidate):
                if char != "{":
                    continue
                try:
                    parsed, _ = decoder.raw_decode(candidate[index:])
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed

        raise LocalEditResponseError("LLM response did not contain a valid JSON object")

    @staticmethod
    def _validate_response_shape(
        parsed: dict[str, Any],
        canvas_library: CanvasLibrary,
    ) -> None:
        """Validate that parsed JSON matches the expected canvas delta shape."""
        if canvas_library == "excalidraw":
            if "elements" not in parsed:
                raise LocalEditResponseError(
                    "LLM response missing 'elements' array for excalidraw"
                )
            if not isinstance(parsed["elements"], list):
                raise LocalEditResponseError("LLM response 'elements' must be an array")
            return

        if "records" not in parsed:
            raise LocalEditResponseError("LLM response missing 'records' object for tldraw")
        if not isinstance(parsed["records"], dict):
            raise LocalEditResponseError("LLM response 'records' must be an object")

    def _detect_operation_type(
        self,
        original_nodes: dict[str, Any],
        modified_nodes: dict[str, Any],
        canvas_library: CanvasLibrary,
    ) -> OperationType:
        """Classify explicit changes; missing records are not deletion signals."""
        if modified_nodes.get("deleted_ids"):
            return "delete"
        if canvas_library == "excalidraw":
            original_ids = {item["id"] for item in original_nodes["elements"]}
            modified_ids = {item["id"] for item in modified_nodes["elements"]}
        else:
            original_ids = set(original_nodes["records"])
            modified_ids = set(modified_nodes["records"])
        return "add" if modified_ids - original_ids else "update"
