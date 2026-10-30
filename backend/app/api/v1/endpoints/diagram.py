import uuid
from dataclasses import dataclass
from typing import Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_or_guest
from app.api.errors import ApiErrorMapping, ApiErrorPolicy
from app.core.exceptions import ProjectNotFoundException
from app.db.session import get_db
from app.models.user import User
from app.core.rate_limit import limiter
from app.core.sse import with_sse_keepalive
from app.schemas.diagram_generate import (
    DiagramGenerateRequest,
    DiagramGenerateResponse,
    DiagramLocalEditRequest,
    DiagramLocalEditResponse,
)
from app.services.diagram_persistence_service import (
    DiagramPersistenceService,
    build_diagram_persistence_input,
)
from app.services.diagram_generation_contract import GenerationInputValidationError
from app.services.diagram_stream_service import DiagramStreamService
from app.services.llm_client import BackendLLMConfigurationError
from app.services.local_edit_service import (
    LocalEditResponseError,
    LocalEditService,
    LocalEditValidationError,
)
from app.services.workflow_generate_service import WorkflowGenerateService
from app.services.workflow_runtime.stream_errors import (
    GENERATION_STREAM_ERROR_TYPES,
    REWRITE_STREAM_ERROR_TYPES,
    _format_stream_error_payload,
    _generation_stream_error_payload,
    _log_generation_stream_error,
    _log_rewrite_stream_error,
    _rewrite_stream_error_payload,
)


router = APIRouter(prefix="/diagram", tags=["Diagram Workflow"])
GENERIC_GENERATION_ERROR = "Diagram generation failed"
GENERIC_LOCAL_EDIT_ERROR = "Local edit failed"
DIAGRAM_GENERATION_ERROR_POLICY = ApiErrorPolicy(
    mappings=(
        ApiErrorMapping(
            GenerationInputValidationError,
            status.HTTP_400_BAD_REQUEST,
        ),
    ),
    fallback_status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    fallback_detail=GENERIC_GENERATION_ERROR,
)
DIAGRAM_PERSISTENCE_ERROR_POLICY = ApiErrorPolicy(
    mappings=(
        ApiErrorMapping(ProjectNotFoundException, status.HTTP_404_NOT_FOUND),
    ),
    fallback_status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    fallback_detail=GENERIC_GENERATION_ERROR,
)
LOCAL_EDIT_ERROR_POLICY = ApiErrorPolicy(
    mappings=(
        ApiErrorMapping(LocalEditValidationError, status.HTTP_400_BAD_REQUEST),
    ),
    fallback_status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    fallback_detail=GENERIC_LOCAL_EDIT_ERROR,
)
ApiErrorLogLevel = Literal["exception", "warning"]


@dataclass(frozen=True)
class _ApiErrorLogMapping:
    error_type: type[BaseException]
    message: str
    level: ApiErrorLogLevel = "exception"


DIAGRAM_GENERATION_ERROR_LOGS = (
    _ApiErrorLogMapping(
        BackendLLMConfigurationError,
        "Diagram generation backend LLM configuration is invalid",
    ),
    _ApiErrorLogMapping(
        GenerationInputValidationError,
        "Diagram generation input rejected: {}",
        "warning",
    ),
    _ApiErrorLogMapping(
        ValueError,
        "Diagram generation failed with internal validation error",
    ),
)
DIAGRAM_PERSISTENCE_ERROR_LOGS = (
    _ApiErrorLogMapping(
        ProjectNotFoundException,
        "Diagram generation persistence rejected: {}",
        "warning",
    ),
)
LOCAL_EDIT_ERROR_LOGS = (
    _ApiErrorLogMapping(
        BackendLLMConfigurationError,
        "Local edit backend LLM configuration is invalid",
    ),
    _ApiErrorLogMapping(
        LocalEditValidationError,
        "Local edit validation error: {}",
        "warning",
    ),
    _ApiErrorLogMapping(
        LocalEditResponseError,
        "Local edit LLM response was invalid",
    ),
)


def _get_user_tier(user: User | None) -> str | None:
    """Return the generation tier supported by the current billing contract."""
    if user is None:
        return None
    sub = user.subscription
    if sub is None or sub.status not in ("active",):
        return None
    # Enterprise access requires an explicit billing mapping before it is enabled.
    return "pro"


def get_workflow_generate_service() -> WorkflowGenerateService:
    return WorkflowGenerateService()


def get_diagram_stream_service() -> DiagramStreamService:
    return DiagramStreamService()


def get_local_edit_service() -> LocalEditService:
    return LocalEditService()


def get_diagram_persistence_service(
    db: AsyncSession = Depends(get_db),
) -> DiagramPersistenceService:
    return DiagramPersistenceService(db)


def _log_api_error(
    exc: BaseException,
    *,
    log_mappings: tuple[_ApiErrorLogMapping, ...],
    fallback_log_message: str,
) -> None:
    """Log a diagram API error without leaking details to the response."""
    for mapping in log_mappings:
        if isinstance(exc, mapping.error_type):
            if mapping.level == "warning":
                logger.warning(mapping.message, exc)
            else:
                logger.exception(mapping.message)
            return

    logger.exception(fallback_log_message)


def _raise_diagram_api_error(
    exc: BaseException,
    *,
    policy: ApiErrorPolicy,
    log_mappings: tuple[_ApiErrorLogMapping, ...],
    fallback_log_message: str,
) -> NoReturn:
    """Raise a public HTTPException for a diagram API boundary failure."""
    _log_api_error(
        exc,
        log_mappings=log_mappings,
        fallback_log_message=fallback_log_message,
    )
    raise policy.to_http_exception(exc) from exc


async def _stream_client_disconnected(request: Request) -> bool:
    """Return whether the streaming client has disconnected.

    Tests call the undecorated endpoint with lightweight request stubs, so the
    check is deliberately duck-typed instead of assuming a Starlette Request.
    """
    is_disconnected = getattr(request, "is_disconnected", None)
    if not callable(is_disconnected):
        return False
    return bool(await is_disconnected())


@router.post("/generate", response_model=DiagramGenerateResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def generate_diagram(
    request: Request,
    body: DiagramGenerateRequest,
    current_user: User | None = Depends(get_current_user_or_guest),
    workflow_service: WorkflowGenerateService = Depends(get_workflow_generate_service),
    persistence_service: DiagramPersistenceService = Depends(
        get_diagram_persistence_service
    ),
):
    user_id = current_user.user_id if current_user else None
    user_tier = _get_user_tier(current_user)

    try:
        workflow_result = await workflow_service.generate_without_render(
            context=body.context,
            requirements=body.requirements,
            locked_nodes=body.locked_nodes,
            current_schema=body.current_schema,
            canvas_library=body.canvas_library,
            use_icons=body.use_icons,
            diagram_type=body.diagram_type,
            user_tier=user_tier,
            user_id=user_id,
            project_id=body.project_id or None,
        )
    except Exception as exc:
        _raise_diagram_api_error(
            exc,
            policy=DIAGRAM_GENERATION_ERROR_POLICY,
            log_mappings=DIAGRAM_GENERATION_ERROR_LOGS,
            fallback_log_message="Diagram generation failed",
        )

    if user_id is None:
        return DiagramGenerateResponse(
            request_id=workflow_result["request_id"],
            project_id=None,
            snapshot_id=None,
            schema_blob=workflow_result["schema_blob"],
            thought_trace=workflow_result.get("thought_trace"),
            metrics_scores=workflow_result.get("metrics_scores"),
            summary=workflow_result.get("summary"),
        )

    try:
        persisted = await persistence_service.persist_generation_result(
            build_diagram_persistence_input(
                user_id=user_id,
                request=body,
                workflow_result=workflow_result,
            )
        )
    except Exception as exc:
        _raise_diagram_api_error(
            exc,
            policy=DIAGRAM_PERSISTENCE_ERROR_POLICY,
            log_mappings=DIAGRAM_PERSISTENCE_ERROR_LOGS,
            fallback_log_message="Diagram generation result persistence failed",
        )

    return DiagramGenerateResponse(
        request_id=workflow_result["request_id"],
        project_id=persisted.project_id,
        snapshot_id=persisted.snapshot_id,
        version=persisted.version,
        schema_blob=workflow_result["schema_blob"],
        thought_trace=workflow_result.get("thought_trace"),
        metrics_scores=workflow_result.get("metrics_scores"),
        summary=workflow_result.get("summary"),
        thumbnail_url=persisted.thumbnail_url,
        proposal_id=getattr(persisted, "proposal_id", None),
        persist_error=bool(getattr(persisted, "proposal_id", None)),
    )


@router.post("/generate/stream")
@limiter.limit("10/minute")
async def generate_diagram_stream(
    request: Request,
    body: DiagramGenerateRequest,
    current_user: User | None = Depends(get_current_user_or_guest),
    workflow_service: WorkflowGenerateService = Depends(get_workflow_generate_service),
    stream_service: DiagramStreamService = Depends(get_diagram_stream_service),
):  # No db dependency here; the streaming generator manages its own session.
    user_id = current_user.user_id if current_user else None
    user_tier = _get_user_tier(current_user)

    async def event_generator():
        emitted_chunk = False
        try:
            if await _stream_client_disconnected(request):
                logger.info("Streaming diagram generation client disconnected before start")
                return

            async for chunk in workflow_service.generate_without_render_streaming(
                context=body.context,
                requirements=body.requirements,
                locked_nodes=body.locked_nodes,
                current_schema=body.current_schema,
                canvas_library=body.canvas_library,
                use_icons=body.use_icons,
                diagram_type=body.diagram_type,
                user_tier=user_tier,
                user_id=user_id,
                project_id=body.project_id or None,
            ):
                if await _stream_client_disconnected(request):
                    logger.info("Streaming diagram generation client disconnected")
                    return

                emitted_chunk = True
                try:
                    yield await stream_service.rewrite_chunk(
                        chunk=chunk,
                        user_id=user_id,
                        request=body,
                    )
                except REWRITE_STREAM_ERROR_TYPES as exc:
                    _log_rewrite_stream_error(exc)
                    yield _format_stream_error_payload(
                        _rewrite_stream_error_payload(exc)
                    )
                    return
                except Exception as exc:
                    _log_rewrite_stream_error(exc)
                    yield _format_stream_error_payload(
                        _rewrite_stream_error_payload(exc)
                    )
                    return
        except GENERATION_STREAM_ERROR_TYPES as exc:
            _log_generation_stream_error(exc, emitted_chunk=emitted_chunk)
            yield _format_stream_error_payload(
                _generation_stream_error_payload(exc, emitted_chunk=emitted_chunk)
            )
        except Exception as exc:
            _log_generation_stream_error(exc, emitted_chunk=emitted_chunk)
            yield _format_stream_error_payload(
                _generation_stream_error_payload(exc, emitted_chunk=emitted_chunk)
            )

    return StreamingResponse(
        with_sse_keepalive(event_generator()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/edit-local", response_model=DiagramLocalEditResponse, status_code=status.HTTP_200_OK)
@limiter.limit("20/minute")
async def edit_diagram_local(
    request: Request,
    body: DiagramLocalEditRequest,
    current_user: User | None = Depends(get_current_user_or_guest),
    service: LocalEditService = Depends(get_local_edit_service),
):
    """
    Perform local edit on selected nodes without full regeneration.
    Returns only the modified nodes as a delta.

    This endpoint:
    - Does NOT create snapshots
    - Does NOT run the full 5-stage workflow
    - Uses a single LLM call for selected-node edits
    - Suitable for iterative chat-based editing
    """
    try:
        result = await service.edit_local(
            current_schema=body.current_schema,
            selected_node_ids=body.selected_node_ids,
            instruction=body.instruction,
            canvas_library=body.canvas_library,
        )

        return DiagramLocalEditResponse(
            request_id=f"edit_{uuid.uuid4().hex[:12]}",
            modified_nodes=result.modified_nodes,
            operation_type=result.operation_type,
            summary=result.summary,
        )
    except Exception as exc:
        _raise_diagram_api_error(
            exc,
            policy=LOCAL_EDIT_ERROR_POLICY,
            log_mappings=LOCAL_EDIT_ERROR_LOGS,
            fallback_log_message="Local edit failed",
        )


@router.get("/learning/{job_id}")
async def get_design_learning_status(
    job_id: str,
    current_user: User | None = Depends(get_current_user_or_guest),
):
    """Only the account that generated the diagram can read its learning job."""
    if current_user is None:
        raise HTTPException(status_code=404, detail="Learning job not found")
    from app.config import get_settings
    from app.services.design_learning_jobs import private_memory_path, read_status
    directory = private_memory_path(get_settings().design_memory_path, current_user.user_id)
    result = read_status(directory, job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Learning job not found")
    return result
