import asyncio

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.api.errors import ApiErrorMapping, ApiErrorPolicy, raise_api_error
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.schemas.dna import DnaAnalyzeResponse, DnaCandidateOut, DnaRulesPayload
from app.services.dna_analysis_service import (
    DnaAnalysisError,
    DnaAnalysisService,
    DnaImageReadError,
    DnaImageTooLargeError,
    DnaImageUnsupportedTypeError,
    DnaImageValidationError,
)
from app.services.dna_rule_service import DnaRuleService


router = APIRouter(prefix="/dna", tags=["DNA"])
GENERIC_DNA_ANALYSIS_ERROR = "DNA analysis failed"
MAX_DNA_UPLOAD_BYTES = 8 * 1024 * 1024
SUPPORTED_DNA_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
DNA_ANALYSIS_ERROR_POLICY = ApiErrorPolicy(
    mappings=(
        ApiErrorMapping(DnaImageValidationError, status.HTTP_400_BAD_REQUEST),
        ApiErrorMapping(DnaAnalysisError, status.HTTP_503_SERVICE_UNAVAILABLE),
    ),
    fallback_status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    fallback_detail=GENERIC_DNA_ANALYSIS_ERROR,
)


def get_dna_analysis_service() -> DnaAnalysisService:
    """Provide the DNA analysis service behind a FastAPI override point."""
    return DnaAnalysisService()


async def _read_dna_upload(file: UploadFile) -> tuple[bytes, str]:
    """Read uploaded image bytes and keep read failures inside the DNA boundary."""
    mime_type = (file.content_type or "image/png").split(";", 1)[0].strip().lower()
    if mime_type not in SUPPORTED_DNA_IMAGE_TYPES:
        raise DnaImageUnsupportedTypeError("Unsupported DNA image upload type")

    try:
        image_bytes = await file.read(MAX_DNA_UPLOAD_BYTES + 1)
    except Exception as exc:
        logger.bind(filename=file.filename, content_type=file.content_type).opt(
            exception=exc
        ).warning("DNA image upload could not be read")
        raise DnaImageReadError("DNA upload stream read failed") from exc

    if len(image_bytes) > MAX_DNA_UPLOAD_BYTES:
        raise DnaImageTooLargeError("DNA upload exceeded maximum size")

    return image_bytes, mime_type


@router.post("/analyze", response_model=DnaAnalyzeResponse)
@limiter.limit("10/minute")
async def analyze_dna_image(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    dna_service: DnaAnalysisService = Depends(get_dna_analysis_service),
):
    """Upload a design/diagram image and extract DNA rule candidates via VLM."""
    try:
        image_bytes, mime_type = await _read_dna_upload(file)
        # analyze_image is a blocking VLM round trip; keep it off the event loop.
        rules = await asyncio.to_thread(
            dna_service.analyze_image,
            image_bytes,
            mime_type,
        )
    except Exception as exc:
        raise_api_error(
            exc,
            policy=DNA_ANALYSIS_ERROR_POLICY,
            logger=logger,
            log_message="DNA analysis failed unexpectedly",
        )

    candidates = [
        DnaCandidateOut(
            temp_id=i + 1,
            cabin_id=rule.cabin_id,
            title=rule.title,
            preview=rule.preview,
        )
        for i, rule in enumerate(rules)
    ]
    return DnaAnalyzeResponse(candidates=candidates)


@router.get("/rules", response_model=DnaRulesPayload)
async def get_dna_rules(
    project_id: str | None = Query(None),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Load user's DNA rules for a given scope (global or project-specific)."""
    return await DnaRuleService(db).get_rules(
        user_id=user_id,
        project_id=project_id,
    )


@router.put("/rules", response_model=DnaRulesPayload)
async def save_dna_rules(
    payload: DnaRulesPayload,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Replace all DNA rules for the given scope (global or project-specific)."""
    return await DnaRuleService(db).replace_rules(user_id=user_id, payload=payload)
