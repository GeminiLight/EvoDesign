import json
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.canvas import CanvasLibrary, normalize_canvas_library_value

# Input caps keep one request from monopolising the LLM pipeline or memory.
MAX_CONTEXT_CHARS = 100_000
MAX_REQUIREMENTS_CHARS = 50_000
MAX_INSTRUCTION_CHARS = 10_000
MAX_NODE_ID_LIST_ITEMS = 2_000
MAX_NODE_ID_CHARS = 256
MAX_CURRENT_SCHEMA_BYTES = 5 * 1024 * 1024
NodeId = Annotated[str, Field(max_length=MAX_NODE_ID_CHARS)]


def _require_schema_size(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Reject canvas schemas whose compact JSON exceeds MAX_CURRENT_SCHEMA_BYTES."""
    if value is None:
        return value
    try:
        size = len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValueError("current_schema must be JSON serializable") from exc
    if size > MAX_CURRENT_SCHEMA_BYTES:
        raise ValueError(
            f"current_schema is too large ({size} bytes; limit {MAX_CURRENT_SCHEMA_BYTES})"
        )
    return value


class DiagramGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_icons: bool = Field(default=True, strict=True, description="Add small semantic icons to key nodes by default")
    diagram_type: str | None = Field(default=None, description="Explicit diagram type; omit for automatic selection")
    context: str = Field(..., max_length=MAX_CONTEXT_CHARS, description="Input context text")
    requirements: Optional[str] = Field(
        default=None, max_length=MAX_REQUIREMENTS_CHARS, description="Generation requirements"
    )
    locked_nodes: list[NodeId] = Field(
        default_factory=list, max_length=MAX_NODE_ID_LIST_ITEMS, description="Locked nodes"
    )
    project_id: Optional[str] = Field(default=None, description="Existing project ID, can be empty")
    base_version: int | None = Field(default=None, ge=1)
    current_schema: Optional[dict[str, Any]] = Field(default=None, description="Current diagram schema")
    canvas_library: CanvasLibrary = Field(
        ...,
        description="Canvas type: excalidraw/tldraw",
    )

    @model_validator(mode="after")
    def require_project_version(self):
        if "use_icons" not in self.model_fields_set:
            if self.canvas_library != "excalidraw":
                self.use_icons = False
            else:
                elements = (self.current_schema or {}).get("elements")
                if isinstance(elements, list):
                    live = [e for e in elements if isinstance(e, dict) and not e.get("isDeleted")]
                    if live:
                        self.use_icons = any(e.get("type") == "image" and
                            isinstance(e.get("customData"), dict) and e["customData"].get("evoDesignIcon")
                            for e in live)
        if self.project_id and not self.project_id.startswith("guest_") and self.base_version is None:
            raise ValueError("base_version is required when generating into an existing project")
        return self

    @field_validator("canvas_library", mode="before")
    @classmethod
    def normalize_canvas_library(cls, value: Any) -> CanvasLibrary:
        return normalize_canvas_library_value(value)

    @field_validator("current_schema")
    @classmethod
    def limit_current_schema_size(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return _require_schema_size(value)

    @field_validator("diagram_type", mode="before")
    @classmethod
    def normalize_diagram_type(cls, value: Any) -> str | None:
        if value is None or value == "automated":
            return None
        from app.core.evo_imports import ensure_evodesign_importable
        ensure_evodesign_importable()
        from evodesign.agentic_system.common.diagram_types import normalize_supported_diagram_type
        return normalize_supported_diagram_type(value)


class DiagramGenerateResponse(BaseModel):
    proposal_id: str | None = None
    persist_error: bool = False
    request_id: str
    project_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    version: int | None = None
    schema_blob: dict[str, Any]
    thought_trace: Optional[dict[str, Any]] = None
    metrics_scores: Optional[dict[str, Any]] = None
    summary: Optional[str] = None
    thumbnail_url: Optional[str] = None


class DiagramLocalEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_schema: dict[str, Any] = Field(..., description="Full canvas JSON (excalidraw or tldraw)")
    selected_node_ids: list[NodeId] = Field(
        ..., max_length=MAX_NODE_ID_LIST_ITEMS, description="IDs of nodes to modify"
    )
    instruction: str = Field(..., max_length=MAX_INSTRUCTION_CHARS, description="User's modification instruction")
    canvas_library: CanvasLibrary = Field(..., description="Canvas type: excalidraw/tldraw")
    project_id: Optional[str] = Field(default=None, description="For context only, no snapshot created")

    @field_validator("canvas_library", mode="before")
    @classmethod
    def normalize_canvas_library(cls, value: Any) -> CanvasLibrary:
        return normalize_canvas_library_value(value)

    @field_validator("current_schema")
    @classmethod
    def limit_current_schema_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _require_schema_size(value)


class DiagramLocalEditResponse(BaseModel):
    request_id: str
    modified_nodes: dict[str, Any] = Field(..., description="Delta: only changed nodes")
    operation_type: Literal["update", "delete", "add"] = Field(..., description="Type of modification")
    summary: str = Field(..., description="Brief description of changes")
