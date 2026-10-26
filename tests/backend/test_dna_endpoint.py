from __future__ import annotations

import inspect
import threading
from datetime import datetime
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_current_user_id
from app.api.v1.endpoints import dna
from app.db.base import Base
from app.models import DnaRule, OAuthCode, Project, Snapshot, Subscription, User  # noqa: F401
from app.schemas.dna import DnaRulesPayload
from app.services.dna_analysis_service import (
    DNA_IMAGE_EMPTY_DETAIL,
    DNA_IMAGE_INVALID_DETAIL,
    DNA_IMAGE_READ_FAILED_DETAIL,
    DNA_IMAGE_TOO_LARGE_DETAIL,
    DNA_IMAGE_UNSUPPORTED_TYPE_DETAIL,
    DnaAnalysisError,
    DnaAnalysisService,
    DnaExtractionError,
    DnaExtractorUnavailableError,
    DnaImageValidationError,
    DnaRuleCandidate,
)


def _upload(data: bytes = b"image") -> UploadFile:
    return UploadFile(filename="reference.png", file=BytesIO(data))


async def _analyze(file, dna_service, *, request=object(), user_id="user-1"):
    """Call the undecorated handler; the route itself is rate limited."""
    return await dna.analyze_dna_image.__wrapped__(
        request=request,
        file=file,
        user_id=user_id,
        dna_service=dna_service,
    )


@pytest.mark.asyncio
async def test_analyze_dna_image_maps_candidates():
    class FakeService:
        def analyze_image(self, image_bytes: bytes, mime_type: str):
            assert image_bytes == b"image"
            assert mime_type == "image/png"
            return [
                DnaRuleCandidate(
                    cabin_id="structure",
                    title="Layered groups",
                    preview="Group related nodes into tiers.",
                )
            ]

    response = await _analyze(_upload(), FakeService())

    assert len(response.candidates) == 1
    assert response.candidates[0].temp_id == 1
    assert response.candidates[0].cabin_id == "structure"


@pytest.mark.asyncio
async def test_analyze_dna_image_maps_empty_upload_to_400():
    class FakeService:
        def analyze_image(self, image_bytes: bytes, mime_type: str):
            raise DnaImageValidationError(
                DNA_IMAGE_EMPTY_DETAIL,
                public_detail=DNA_IMAGE_EMPTY_DETAIL,
            )

    with pytest.raises(HTTPException) as exc_info:
        await _analyze(_upload(b""), FakeService())

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Uploaded image is empty"


@pytest.mark.asyncio
async def test_analyze_dna_image_maps_upload_read_failures_to_400():
    class BrokenUpload:
        filename = "reference.png"
        content_type = "image/png"

        async def read(self, size: int = -1):
            raise RuntimeError("upload secret-token leaked")

    with pytest.raises(HTTPException) as exc_info:
        await _analyze(BrokenUpload(), None)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == DNA_IMAGE_READ_FAILED_DETAIL
    assert "secret-token" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_analyze_dna_image_rejects_unsupported_content_type_before_service():
    class TextUpload:
        filename = "reference.txt"
        content_type = "text/plain"

        async def read(self, size: int = -1):
            pytest.fail("unsupported uploads should be rejected before reading bytes")

    with pytest.raises(HTTPException) as exc_info:
        await _analyze(TextUpload(), None)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == DNA_IMAGE_UNSUPPORTED_TYPE_DETAIL


@pytest.mark.asyncio
async def test_analyze_dna_image_rejects_oversized_upload_before_service(monkeypatch):
    monkeypatch.setattr(dna, "MAX_DNA_UPLOAD_BYTES", 3)

    with pytest.raises(HTTPException) as exc_info:
        await _analyze(_upload(b"abcd"), None)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == DNA_IMAGE_TOO_LARGE_DETAIL


@pytest.mark.asyncio
async def test_analyze_dna_image_normalizes_supported_content_type():
    class JpegUpload:
        filename = "reference.jpg"
        content_type = "IMAGE/JPEG; charset=binary"

        async def read(self, size: int = -1):
            return b"jpeg"

    class FakeService:
        def analyze_image(self, image_bytes: bytes, mime_type: str):
            assert image_bytes == b"jpeg"
            assert mime_type == "image/jpeg"
            return []

    response = await _analyze(JpegUpload(), FakeService())

    assert response.candidates == []


def test_analyze_dna_image_requires_an_authenticated_user():
    user_id_param = inspect.signature(
        dna.analyze_dna_image.__wrapped__
    ).parameters["user_id"]

    assert user_id_param.default.dependency is get_current_user_id


@pytest.mark.asyncio
async def test_analyze_dna_image_keeps_the_blocking_vlm_call_off_the_event_loop():
    calling_threads = []

    class FakeService:
        def analyze_image(self, image_bytes: bytes, mime_type: str):
            calling_threads.append(threading.current_thread())
            return []

    await _analyze(_upload(), FakeService())

    assert calling_threads[0] is not threading.main_thread()


def test_get_dna_analysis_service_returns_service_instance():
    assert isinstance(dna.get_dna_analysis_service(), DnaAnalysisService)


@pytest.mark.asyncio
async def test_analyze_dna_image_hides_validation_error_details():
    class FakeService:
        def analyze_image(self, image_bytes: bytes, mime_type: str):
            raise DnaImageValidationError("provider secret-token")

    with pytest.raises(HTTPException) as exc_info:
        await _analyze(_upload(), FakeService())

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == DNA_IMAGE_INVALID_DETAIL
    assert "secret-token" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_analyze_dna_image_hides_unexpected_value_errors():
    class FakeService:
        def analyze_image(self, image_bytes: bytes, mime_type: str):
            raise ValueError("provider secret-token")

    with pytest.raises(HTTPException) as exc_info:
        await _analyze(_upload(), FakeService())

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "DNA analysis failed"
    assert "secret-token" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_analyze_dna_image_maps_extractor_failure_to_503():
    class FakeService:
        def analyze_image(self, image_bytes: bytes, mime_type: str):
            raise DnaAnalysisError("DNA extractor is not available")

    with pytest.raises(HTTPException) as exc_info:
        await _analyze(_upload(), FakeService())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "DNA analysis failed"


@pytest.mark.asyncio
async def test_analyze_dna_image_uses_analysis_error_public_detail():
    class FakeService:
        def analyze_image(self, image_bytes: bytes, mime_type: str):
            raise DnaAnalysisError(
                "provider secret-token",
                public_detail="public DNA dependency issue",
            )

    with pytest.raises(HTTPException) as exc_info:
        await _analyze(_upload(), FakeService())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "public DNA dependency issue"
    assert "secret-token" not in exc_info.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_detail"),
    [
        (
            DnaExtractorUnavailableError("DNA extractor is not available"),
            "DNA extractor is not available",
        ),
        (DnaExtractionError("DNA extraction failed"), "DNA analysis failed"),
    ],
)
async def test_analyze_dna_image_maps_analysis_error_subclasses_to_503(
    error,
    expected_detail,
):
    class FakeService:
        def analyze_image(self, image_bytes: bytes, mime_type: str):
            raise error

    with pytest.raises(HTTPException) as exc_info:
        await _analyze(_upload(), FakeService())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == expected_detail


@pytest.mark.asyncio
async def test_analyze_dna_image_hides_analysis_error_details():
    class FakeService:
        def analyze_image(self, image_bytes: bytes, mime_type: str):
            raise DnaExtractionError("provider secret-token")

    with pytest.raises(HTTPException) as exc_info:
        await _analyze(_upload(), FakeService())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "DNA analysis failed"
    assert "secret-token" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_dna_rules_delegates_to_rule_service(monkeypatch):
    class FakeRuleService:
        def __init__(self, db):
            self.db = db

        async def get_rules(self, *, user_id: str, project_id: str | None):
            assert self.db == "db"
            assert user_id == "user-1"
            assert project_id == "project-1"
            return DnaRulesPayload(project_id=project_id)

    monkeypatch.setattr(dna, "DnaRuleService", FakeRuleService)

    response = await dna.get_dna_rules(
        project_id="project-1",
        user_id="user-1",
        db="db",
    )

    assert response.project_id == "project-1"


@pytest.mark.asyncio
async def test_get_dna_rules_response_carries_stored_rule_ids():
    """GET /dna/rules must expose the persisted rule_id for stable identities.

    The frontend keys rule edits and deletions by this id, so the wire shape
    (response_model=DnaRulesPayload) is validated explicitly here.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            session.add(
                DnaRule(
                    rule_id="stored-rule-1",
                    user_id="user-1",
                    project_id=None,
                    cabin_id="structure",
                    title="Layered flow",
                    preview="Group related nodes into tiers.",
                    source="manual",
                    enabled=True,
                    pinned=False,
                    usage_count=3,
                    created_at=datetime(2026, 1, 1),
                    updated_at=datetime(2026, 1, 2),
                )
            )
            await session.commit()

        async with session_factory() as session:
            payload = await dna.get_dna_rules(
                project_id=None,
                user_id="user-1",
                db=session,
            )

        wire = DnaRulesPayload.model_validate(payload).model_dump(mode="json")
    finally:
        await engine.dispose()

    assert wire["project_id"] is None
    assert wire["structure"][0]["rule_id"] == "stored-rule-1"
    assert wire["structure"][0]["title"] == "Layered flow"
    assert wire["structure"][0]["usage_count"] == 3
    assert wire["style"] == []
    assert wire["layout"] == []


@pytest.mark.asyncio
async def test_save_dna_rules_delegates_to_rule_service(monkeypatch):
    payload = DnaRulesPayload(project_id=None)

    class FakeRuleService:
        def __init__(self, db):
            self.db = db

        async def replace_rules(self, *, user_id: str, payload: DnaRulesPayload):
            assert self.db == "db"
            assert user_id == "user-1"
            assert payload.project_id is None
            return payload

    monkeypatch.setattr(dna, "DnaRuleService", FakeRuleService)

    response = await dna.save_dna_rules(
        payload=payload,
        user_id="user-1",
        db="db",
    )

    assert response is payload
