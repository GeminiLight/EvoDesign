from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.canvas import CanvasLibrary, normalize_canvas_library_value


class DiagramGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_icons: bool = Field(default=False, strict=True, description="Add small semantic icons to key nodes")
    diagram_type: str | None = Field(default=None, description="Explicit diagram type; omit for automatic selection")
    context: str = Field(..., description="Input context text")
    requirements: Optional[str] = Field(default=None, description="Generation requirements")
    locked_nodes: list[str] = Field(default_factory=list, description="Locked nodes")
    project_id: Optional[str] = Field(default=None, description="Existing project ID, can be empty")
    current_schema: Optional[dict[str, Any]] = Field(default=None, description="Current diagram schema")
    canvas_library: CanvasLibrary = Field(
        ...,
        description="Canvas type: excalidraw/tldraw",
    )

    @field_validator("canvas_library", mode="before")
    @classmethod
    def normalize_canvas_library(cls, value: Any) -> CanvasLibrary:
        return normalize_canvas_library_value(value)


    @field_validator("diagram_type", mode="before")
    @classmethod
    def normalize_diagram_type(cls, value: Any) -> str | None:
        if value is None or value == "automated":
            return None
        from app.core.evo_imports import ensure_evo_diagram_importable
        ensure_evo_diagram_importable()
        from evo_diagram.agentic_system.common.diagram_types import normalize_supported_diagram_type
        return normalize_supported_diagram_type(value)


class DiagramGenerateResponse(BaseModel):
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
    selected_node_ids: list[str] = Field(..., description="IDs of nodes to modify")
    instruction: str = Field(..., description="User's modification instruction")
    canvas_library: CanvasLibrary = Field(..., description="Canvas type: excalidraw/tldraw")
    project_id: Optional[str] = Field(default=None, description="For context only, no snapshot created")

    @field_validator("canvas_library", mode="before")
    @classmethod
    def normalize_canvas_library(cls, value: Any) -> CanvasLibrary:
        return normalize_canvas_library_value(value)


class DiagramLocalEditResponse(BaseModel):
    request_id: str
    modified_nodes: dict[str, Any] = Field(..., description="Delta: only changed nodes")
    operation_type: Literal["update", "delete", "add"] = Field(..., description="Type of modification")
    summary: str = Field(..., description="Brief description of changes")
