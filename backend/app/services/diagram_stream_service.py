"""Streaming diagram generation result rewriting and persistence."""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import ProjectNotFoundException
from app.core.sse import format_sse_event, parse_sse_event
from app.db.session import create_db_session
from app.schemas.diagram_generate import DiagramGenerateRequest
from app.services.diagram_persistence_service import (
    DiagramPersistenceService,
    build_diagram_persistence_input,
)


SessionFactory = Callable[[], Any]
PersistenceServiceFactory = Callable[[Any], DiagramPersistenceService]
GENERIC_PERSISTENCE_ERROR_MESSAGE = "Diagram result could not be saved."
RESULT_CONTRACT_ERRORS = (KeyError, TypeError, ValueError)


class DiagramStreamService:
    """Persist streaming generation results and rewrite result SSE payloads."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory = create_db_session,
        persistence_service_factory: PersistenceServiceFactory = DiagramPersistenceService,
    ):
        self.session_factory = session_factory
        self.persistence_service_factory = persistence_service_factory

    async def persist_stream_result(
        self,
        *,
        user_id: str,
        request: DiagramGenerateRequest,
        result_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist a streaming generation result and annotate the emitted payload."""
        result_data = dict(result_data)

        async with self.session_factory() as persist_db:
            try:
                persisted = await self.persistence_service_factory(
                    persist_db
                ).persist_generation_result(
                    build_diagram_persistence_input(
                        user_id=user_id,
                        request=request,
                        workflow_result=result_data,
                    )
                )
                await persist_db.commit()
                result_data["project_id"] = persisted.project_id
                result_data["snapshot_id"] = persisted.snapshot_id
                result_data["version"] = persisted.version
                result_data["thumbnail_url"] = persisted.thumbnail_url
            except ProjectNotFoundException as exc:
                await persist_db.rollback()
                logger.warning("Persist rejected (HTTP 404): {}", exc)
                result_data["persist_error"] = True
                result_data["persist_error_message"] = exc.public_detail
            except SQLAlchemyError as exc:
                await persist_db.rollback()
                logger.warning("Failed to persist diagram result to DB: {}", exc)
                result_data["persist_error"] = True
                result_data["persist_error_message"] = GENERIC_PERSISTENCE_ERROR_MESSAGE
            except RESULT_CONTRACT_ERRORS:
                await persist_db.rollback()
                logger.exception(
                    "Streaming diagram result failed persistence contract validation"
                )
                raise

        return result_data

    async def rewrite_chunk(
        self,
        *,
        chunk: str,
        user_id: str | None,
        request: DiagramGenerateRequest,
    ) -> str:
        """Inject persistence metadata into result SSE chunks for logged-in users."""
        event = parse_sse_event(chunk)
        if event is None or event.event != "result" or user_id is None:
            return chunk

        result_data = await self.persist_stream_result(
            user_id=user_id,
            request=request,
            result_data=event.data,
        )
        return format_sse_event("result", result_data)
