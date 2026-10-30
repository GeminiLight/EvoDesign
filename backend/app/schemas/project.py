from datetime import datetime
from typing import Any

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
)

from app.core.canvas import CanvasLibrary, normalize_canvas_library_value


class ProjectSnapshotItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    snapshot_id: str
    project_id: str
    parent_id: str | None = None
    schema_blob: dict[str, Any]
    edit_source: str
    is_checkpoint: bool = False
    thought_trace: str | None = None
    metrics_scores: dict[str, Any] | None = None
    timestamp: datetime


class ProjectSnapshotListResponse(BaseModel):
    snapshots: list[ProjectSnapshotItem]
    page: int
    page_size: int
    total: int
    project_version: int | None = None


# ---- Project CRUD schemas ----


class ProjectListItem(BaseModel):
    """Project summary returned by the project list endpoint."""
    model_config = ConfigDict(from_attributes=True)

    project_id: str
    title: str | None = None
    diagram_type: str | None = None
    canvas_engine: str
    source_text: str | None = None
    latest_schema: dict[str, Any] | None = None
    thumbnail_url: str | None = None
    created_at: datetime
    updated_at: datetime
    snapshot_count: int = 0
    latest_snapshot_id: str | None = None
    version: int = 1

    @computed_field
    @property
    def canvas_library(self) -> str:
        """Canonical API name for the project's canvas runtime."""
        return self.canvas_engine


class ProjectListResponse(BaseModel):
    projects: list[ProjectListItem]
    total: int


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    diagram_type: str | None = "automated"
    canvas_engine: CanvasLibrary = Field(
        default="excalidraw",
        validation_alias=AliasChoices("canvas_engine", "canvas_library"),
    )
    source_text: str | None = None

    @field_validator("canvas_engine", mode="before")
    @classmethod
    def normalize_canvas_engine(cls, value: Any) -> CanvasLibrary:
        return normalize_canvas_library_value(value)


class ProjectCreateResponse(BaseModel):
    version: int = 1
    project_id: str
    created_at: datetime


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    version: int | None = Field(default=None, ge=1)
    diagram_type: str | None = None
    canvas_engine: CanvasLibrary | None = Field(
        default=None,
        validation_alias=AliasChoices("canvas_engine", "canvas_library"),
    )

    @field_validator("canvas_engine", mode="before")
    @classmethod
    def normalize_canvas_engine(cls, value: Any) -> CanvasLibrary | None:
        if value is None:
            return None
        return normalize_canvas_library_value(value)


class ProjectDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: str
    title: str | None = None
    diagram_type: str | None = None
    canvas_engine: str
    source_text: str | None = None
    latest_schema: dict[str, Any] | None = None
    current_snapshot_id: str | None = None
    thumbnail_url: str | None = None
    created_at: datetime
    updated_at: datetime
    version: int = 1

    @computed_field
    @property
    def canvas_library(self) -> str:
        """Canonical API name for the project's canvas runtime."""
        return self.canvas_engine


class ProjectUpdateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: str
    title: str | None = None
    diagram_type: str | None = None
    canvas_engine: str
    updated_at: datetime

    @computed_field
    @property
    def canvas_library(self) -> str:
        """Canonical API name for the project's canvas runtime."""
        return self.canvas_engine
