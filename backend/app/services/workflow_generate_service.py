"""Backend diagram generation service."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import uuid
from typing import Any, AsyncGenerator, Optional

from app.config import Settings, get_settings
from app.services.diagram_generation_contract import normalize_canvas_library
from app.services.dna_design_expertise import load_dna_design_expertise
from app.services.llm_client import create_backend_llm
from app.services.workflow_engine_adapter import WorkflowEngineAdapter, WorkflowRunRequest


class WorkflowGenerateService:
    """Coordinate backend settings, LLM construction, and EvoDiagram engine calls."""

    def __init__(
        self,
        settings: Settings | None = None,
        engine_adapter: WorkflowEngineAdapter | None = None,
    ):
        self.settings = settings or get_settings()
        self.engine_adapter = engine_adapter

    def _create_llm(self):
        return create_backend_llm(settings=self.settings)

    def _get_engine_adapter(self) -> WorkflowEngineAdapter:
        return self.engine_adapter or WorkflowEngineAdapter(results_dir=self.settings.results_dir)

    def _build_run_request(
        self,
        *,
        context: str,
        requirements: Optional[str],
        locked_nodes: list[str],
        current_schema: Optional[dict[str, Any]],
        canvas_library: str,
        request_id: str,
        user_tier: str | None,
        design_expertise: str = "",
        user_id: str | None = None,
        use_icons: bool = False,
        diagram_type: str | None = None,
    ) -> WorkflowRunRequest:
        normalized_canvas_library = normalize_canvas_library(canvas_library)
        return WorkflowRunRequest(
            context=context,
            requirements=requirements,
            locked_nodes=locked_nodes,
            current_schema=current_schema,
            canvas_library=normalized_canvas_library,
            user_tier=user_tier,
            request_id=request_id,
            design_expertise=design_expertise,
            use_icons=use_icons,
            diagram_type=diagram_type,
            enable_refiner=self.settings.auto_refine_enabled,
            refiner_max_iterations=self.settings.auto_refine_max_iterations,
            enable_design_memory=self.settings.design_memory_enabled,
            design_memory_path=str(Path(self.settings.design_memory_path) / (
                hashlib.sha256(user_id.encode()).hexdigest()[:24] if user_id else "guest"
            )),
            design_memory_seed_path=self.settings.design_memory_seed_path,
            design_memory_model=self.settings.design_memory_model,
            design_memory_top_k=self.settings.design_memory_top_k,
            learn_design_memory=bool(user_id and self.settings.design_memory_learning),
            retain_artifacts=self.settings.retain_generation_artifacts,
        )

    async def generate_without_render(
        self,
        context: str,
        requirements: Optional[str],
        locked_nodes: list[str],
        current_schema: Optional[dict[str, Any]],
        canvas_library: str,
        user_tier: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        use_icons: bool = False,
        diagram_type: str | None = None,
    ) -> dict[str, Any]:
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        design_expertise = await load_dna_design_expertise(
            user_id=user_id,
            project_id=project_id,
        )
        result = await asyncio.to_thread(
            self._run_workflow_without_render_sync,
            context,
            requirements,
            locked_nodes,
            current_schema,
            canvas_library,
            request_id,
            user_tier,
            design_expertise,
            user_id,
            use_icons,
            diagram_type,
        )
        return result

    async def generate_without_render_streaming(
        self,
        context: str,
        requirements: Optional[str],
        locked_nodes: list[str],
        current_schema: Optional[dict[str, Any]],
        canvas_library: str,
        user_tier: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        use_icons: bool = False,
        diagram_type: str | None = None,
    ) -> AsyncGenerator[str, None]:
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        design_expertise = await load_dna_design_expertise(
            user_id=user_id,
            project_id=project_id,
        )
        request = self._build_run_request(
            context=context,
            requirements=requirements,
            locked_nodes=locked_nodes,
            current_schema=current_schema,
            canvas_library=canvas_library,
            request_id=request_id,
            user_tier=user_tier,
            design_expertise=design_expertise,
            use_icons=use_icons,
            diagram_type=diagram_type,
            user_id=user_id,
        )
        model = self._create_llm()
        async for chunk in self._get_engine_adapter().stream_without_render(
            model=model,
            request=request,
        ):
            yield chunk

    def _run_workflow_without_render_sync(
        self,
        context: str,
        requirements: Optional[str],
        locked_nodes: list[str],
        current_schema: Optional[dict[str, Any]],
        canvas_library: str,
        request_id: str,
        user_tier: str | None = None,
        design_expertise: str = "",
        user_id: str | None = None,
        use_icons: bool = False,
        diagram_type: str | None = None,
    ) -> dict[str, Any]:
        request = self._build_run_request(
            context=context,
            requirements=requirements,
            locked_nodes=locked_nodes,
            current_schema=current_schema,
            canvas_library=canvas_library,
            request_id=request_id,
            user_tier=user_tier,
            design_expertise=design_expertise,
            use_icons=use_icons,
            diagram_type=diagram_type,
            user_id=user_id,
        )
        return self._get_engine_adapter().run_without_render_sync(
            model=self._create_llm(),
            request=request,
        )
