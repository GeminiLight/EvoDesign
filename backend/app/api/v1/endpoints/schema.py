from fastapi import APIRouter, Depends, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.api.errors import (
    ApiErrorMapping,
    ApiErrorPolicy,
    raise_api_error,
)
from app.core.exceptions import ProjectNotFoundException
from app.db.session import get_db
from app.schemas.schema import SchemaSyncRequest, SchemaSyncResponse
from app.services.schema_service import (
    SchemaService,
    SchemaSyncError,
    VersionConflictError,
)


router = APIRouter(prefix="/schema", tags=["Schema"])
SCHEMA_SYNC_ERROR_DETAIL = "schema sync failed"
SCHEMA_SYNC_ERROR_POLICY = ApiErrorPolicy(
    mappings=(
        ApiErrorMapping(VersionConflictError, status.HTTP_409_CONFLICT),
        ApiErrorMapping(ProjectNotFoundException, status.HTTP_404_NOT_FOUND),
        ApiErrorMapping(SchemaSyncError, status.HTTP_400_BAD_REQUEST),
    ),
    fallback_status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    fallback_detail=SCHEMA_SYNC_ERROR_DETAIL,
)


@router.patch("/sync", response_model=SchemaSyncResponse, status_code=status.HTTP_200_OK)
async def sync_schema(
    request: SchemaSyncRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    schema_service = SchemaService(db)

    try:
        project, snapshot = await schema_service.sync_schema(
            user_id=user_id,
            project_id=request.project_id,
            schema_patch=request.schema_patch,
            editor=request.editor,
            base_snapshot_id=request.base_snapshot_id,
            create_snapshot=request.create_snapshot,
            version=request.version,
        )
    except Exception as exc:
        raise_api_error(
            exc,
            policy=SCHEMA_SYNC_ERROR_POLICY,
            logger=logger,
            log_message="Schema sync failed",
        )

    return SchemaSyncResponse(
        project_id=project.project_id,
        snapshot_id=snapshot.snapshot_id,
        latest_schema=project.latest_schema or {},
        edit_source="HUMAN",
        version=project.version,
    )
