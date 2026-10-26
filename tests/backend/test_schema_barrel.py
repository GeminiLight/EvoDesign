from __future__ import annotations

import pytest
from pydantic import ValidationError

import app.schemas as schemas
from app.schemas import auth, common, user
from app.schemas.auth import AuthResponse, CodeExchangeRequest
from app.schemas.diagram_generate import (
    DiagramGenerateRequest,
    DiagramGenerateResponse,
    DiagramLocalEditRequest,
    DiagramLocalEditResponse,
)
from app.schemas.dna import DnaAnalyzeResponse, DnaRulesPayload
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectListItem,
    ProjectListResponse,
    ProjectUpdateResponse,
)
from app.schemas.schema import SchemaSyncRequest


def test_schema_package_does_not_expose_compatibility_barrel_exports():
    assert not hasattr(schemas, "__all__")
    assert not hasattr(schemas, "AuthResponse")
    assert not hasattr(schemas, "DiagramGenerateRequest")
    assert not hasattr(schemas, "ProjectListResponse")


def test_schema_models_are_imported_from_owning_modules():
    expected_models = [
        AuthResponse,
        CodeExchangeRequest,
        DiagramGenerateRequest,
        DiagramGenerateResponse,
        DiagramLocalEditRequest,
        DiagramLocalEditResponse,
        DnaAnalyzeResponse,
        DnaRulesPayload,
        ProjectCreateRequest,
        ProjectListItem,
        ProjectListResponse,
        ProjectUpdateResponse,
        SchemaSyncRequest,
    ]
    for model in expected_models:
        assert model.__module__.startswith("app.schemas.")


def test_diagram_generate_request_does_not_expose_local_edit_mode():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DiagramGenerateRequest(context="A to B", canvas_library="excalidraw", edit_mode="local")

    assert "edit_mode" not in DiagramGenerateRequest.model_fields


def test_backend_schema_docs_do_not_reference_frontend_types():
    project_doc = ProjectListItem.__doc__ or ""
    schema_doc = str(SchemaSyncRequest.model_json_schema())

    assert "frontend" not in project_doc.lower()
    assert "frontend" not in schema_doc.lower()
    assert "RecentDiagram" not in project_doc
    assert "RecentDiagram" not in schema_doc


def test_legacy_schema_models_are_removed_from_owning_modules():
    legacy_models = {
        auth: ["TokenPayload"],
        common: ["ErrorResponse", "PaginationParams", "SuccessResponse"],
        user: ["UserBase", "UserCreate", "UserLogin", "UserWithToken"],
    }

    for module, model_names in legacy_models.items():
        for model_name in model_names:
            assert not hasattr(module, model_name)
