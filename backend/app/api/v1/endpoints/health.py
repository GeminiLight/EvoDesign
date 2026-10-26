from fastapi import APIRouter
from datetime import datetime, timezone

from app.schemas.common import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check"""
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc).isoformat()
    )
