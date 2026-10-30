from typing import Any

from pydantic import BaseModel, Field

from app.schemas.schema_contract import DEFAULT_SCHEMA_EDITOR, SchemaEditor


class SchemaSyncRequest(BaseModel):
    project_id: str = Field(..., description="Project ID")
    schema_patch: dict[str, Any] = Field(
        ...,
        description="Diagram schema patch or full editor payload",
    )
    editor: SchemaEditor = Field(
        default=DEFAULT_SCHEMA_EDITOR,
        description="Editor source",
    )
    base_snapshot_id: str | None = Field(default=None, description="Base snapshot ID")
    create_snapshot: bool = Field(default=False, description="Whether to create a new snapshot")
    version: int = Field(
        ..., ge=1,
        description="Expected project version for optimistic locking",
    )


class SchemaSyncResponse(BaseModel):
    project_id: str
    snapshot_id: str
    latest_schema: dict[str, Any]
    edit_source: str = "HUMAN"
    version: int = Field(..., description="Updated project version")
