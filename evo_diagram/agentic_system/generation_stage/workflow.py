"""GeneratorWorkflow — mid-level abstraction for diagram generation.

Provides a common interface for two generation strategies:
- ``PipelineGeneratorWorkflow``: Structure → Styling → Layout (3 LLM calls)
- ``OneShotGeneratorWorkflow``: single LLM call produces the complete scene

Usage::

    generator = PipelineGeneratorWorkflow(model)
    outputs = generator.run(text_content="...", user_query="...")
    # outputs = {"structure_instantiation": ..., "layout_instantiation": ..., ...}

    generator = OneShotGeneratorWorkflow(model)
    outputs = generator.run(text_content="...", user_query="...")
    # outputs = {"structure_instantiation": ..., "diagram_manifest": ...}
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from langchain_core.language_models import BaseChatModel

from evo_diagram.canvas_runtime import normalize_canvas_library
from evo_diagram.config.settings import normalize_generation_mode
from evo_diagram.canvas_environment.capabilities import require_generation_capability
from evo_diagram.agentic_system.generation_stage.router.agent import (
    DEFAULT_PALETTE_KEY,
    RouterAgent,
)
from evo_diagram.agentic_system.common.diagram_types import (
    DiagramTypeValidationError,
    normalize_diagram_type,
    normalize_supported_diagram_type,
)
from evo_diagram.agentic_system.common.domain_knowledge_loader import (
    build_diagram_context,
    build_stage_knowledge,
    get_group_containment_reference,
)

logger = logging.getLogger(__name__)

PIPELINE_STAGE_SEQUENCE = ("structure", "styling", "layout")


class GeneratorWorkflow(ABC):
    """Base class for diagram generation workflows.

    Subclasses produce generation outputs from text input.  The returned
    dict keys depend on the strategy: pipeline mode returns intermediate
    structure/styling/layout dicts; one-shot returns ``diagram_manifest`` plus
    a Structure-shaped semantic sidecar in ``structure_instantiation``.
    """

    @abstractmethod
    def run(
        self,
        text_content: str,
        user_query: str,
        *,
        design_expertise: str = "",
        runtime_directives: str = "",
        diagram_type: Optional[str] = None,
        content_area: Optional[str] = None,
        save_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate diagram outputs from text.

        Returns:
            Dict with generation outputs.  Pipeline mode returns keys
            ``structure_instantiation``, ``structure_specification``,
            ``styling_instantiation``, ``styling_specification``,
            ``layout_instantiation``, ``layout_specification``.
            One-shot mode returns ``diagram_manifest`` and
            ``structure_instantiation``.
        """


def _save_stage_output(
    save_dir: str,
    stage_name: str,
    artifact_name: str,
    instantiation: Any,
    specification: Any = None,
) -> Dict[str, str]:
    """Persist one stage's output to disk."""
    import json
    import os

    stage_dir = os.path.join(save_dir, stage_name)
    os.makedirs(stage_dir, exist_ok=True)
    paths: Dict[str, str] = {}

    if instantiation is not None:
        instantiation_path = os.path.join(stage_dir, f"{artifact_name}_instantiation.json")
        with open(instantiation_path, "w", encoding="utf-8") as f:
            json.dump(instantiation, f, indent=2, ensure_ascii=False)
        paths[f"{artifact_name}_instantiation_path"] = instantiation_path

    if specification is not None:
        specification_path = os.path.join(stage_dir, f"{artifact_name}_specification.json")
        with open(specification_path, "w", encoding="utf-8") as f:
            json.dump(specification, f, indent=2, ensure_ascii=False)
        paths[f"{artifact_name}_specification_path"] = specification_path

    return paths


@dataclass
class PipelineGenerationRun:
    """Mutable state for an observable Structure -> Styling -> Layout run."""

    text_content: str
    user_query: str
    design_expertise: str = ""
    runtime_directives: str = ""
    content_area: Optional[str] = None
    effective_diagram_type: Optional[str] = None
    palette_key: str = DEFAULT_PALETTE_KEY
    artifact_paths: Dict[str, str] = field(default_factory=dict)
    structure_state: Any = None
    styling_state: Any = None
    layout_state: Any = None
    structure_instantiation: Any = None
    structure_specification: Any = None
    styling_instantiation: Any = None
    styling_specification: Any = None
    layout_instantiation: Any = None
    layout_specification: Any = None


class PipelineGeneratorWorkflow(GeneratorWorkflow):
    """Multi-stage generation: Structure → Styling → Layout.

    Wraps the three sub-workflows and threads state between them.
    """

    def __init__(
        self,
        model: BaseChatModel,
        canvas_library: str = "excalidraw",
        use_icons: bool = False,
        router_model: Optional[BaseChatModel] = None,
        full_domain_knowledge: bool = True,
    ) -> None:
        from .structure.workflow import StructureWorkflow
        from .styling.workflow import StylingWorkflow
        from .layout.workflow import LayoutWorkflow

        self.structure = StructureWorkflow(model)
        self.styling = StylingWorkflow(model, use_icons=use_icons)
        self.layout = LayoutWorkflow(model)
        self.canvas_library = normalize_canvas_library(canvas_library)
        self.full_domain_knowledge = full_domain_knowledge

        # Router uses a cheap/fast model for classification
        self._router: Optional[RouterAgent] = None
        if router_model is not None:
            self._router = RouterAgent(router_model)

    def resolve_generation_context(
        self,
        text_content: str,
        user_query: str,
        diagram_type: Optional[str] = None,
    ) -> tuple[Optional[str], str]:
        """Resolve router-derived context shared by every pipeline stage."""
        palette_key = DEFAULT_PALETTE_KEY
        effective_diagram_type = diagram_type

        if self._router is not None:
            logger.info("[PipelineGenerator] Running RouterAgent...")
            router_result = self._router.run(text_content, user_query)
            palette_key = router_result.get("palette_key", "")
            if not effective_diagram_type:
                effective_diagram_type = router_result.get("diagram_type")
            logger.info(
                "[PipelineGenerator] Router: diagram_type=%s, palette_key=%s",
                effective_diagram_type, palette_key,
            )

        if effective_diagram_type:
            try:
                effective_diagram_type = normalize_supported_diagram_type(
                    effective_diagram_type,
                    field_name="diagram_type",
                )
            except DiagramTypeValidationError as exc:
                raise ValueError(str(exc)) from exc

        return effective_diagram_type, palette_key

    def build_stage_context(
        self,
        stage_name: str,
        diagram_type: Optional[str],
    ) -> str:
        """Build the stage_knowledge block for a pipeline stage."""
        stage_knowledge = build_stage_knowledge(
            diagram_type,
            stage_name,
            full_mode=self.full_domain_knowledge,
        )
        diagram_context = build_diagram_context(diagram_type)
        if diagram_context:
            stage_knowledge = f"{diagram_context}\n\n{stage_knowledge}".strip()
        if stage_name == "Structure" and diagram_type == "architecture":
            group_ref = get_group_containment_reference()
            if group_ref:
                stage_knowledge += f"\n\n=== GROUP & CONTAINMENT REFERENCE ===\n{group_ref}"
        return stage_knowledge

    @staticmethod
    def _resolve_downstream_diagram_type(
        resolved_diagram_type: Optional[str],
        structure_instantiation: Any,
    ) -> Optional[str]:
        structure_chart_type = None
        if isinstance(structure_instantiation, dict):
            raw_chart_type = structure_instantiation.get("chart_type")
            if isinstance(raw_chart_type, str) and raw_chart_type.strip():
                structure_chart_type = raw_chart_type

        try:
            normalized_resolved = (
                normalize_supported_diagram_type(resolved_diagram_type)
                if resolved_diagram_type
                else ""
            )
            normalized_structure = (
                normalize_supported_diagram_type(structure_chart_type, field_name="chart_type")
                if structure_chart_type
                else ""
            )
        except DiagramTypeValidationError as exc:
            raise ValueError(str(exc)) from exc

        if normalized_resolved and normalized_structure:
            if normalized_resolved != normalized_structure:
                raise ValueError(
                    "Structure chart_type conflicts with resolved diagram_type: "
                    f"{structure_chart_type!r} vs {resolved_diagram_type!r}."
                )
            return normalized_structure

        return normalized_structure or normalized_resolved or normalize_diagram_type(resolved_diagram_type)

    @staticmethod
    def _record_stage_artifacts(
        artifact_paths: Dict[str, str],
        *,
        save_dir: Optional[str],
        stage_name: str,
        artifact_name: str,
        instantiation: Any,
        specification: Any,
    ) -> None:
        if not save_dir:
            return
        artifact_paths.update(
            _save_stage_output(
                save_dir,
                stage_name,
                artifact_name,
                instantiation,
                specification,
            )
        )

    @staticmethod
    def _raise_if_stage_failed(stage_name: str, stage_state: Any) -> None:
        status = getattr(stage_state, "status", None)
        errors = getattr(stage_state, "errors", None) or []

        if status == "failed" or errors:
            error_message = (
                "; ".join(str(error) for error in errors) or "no error details"
            )
            raise RuntimeError(
                f"Pipeline generation {stage_name} stage failed: {error_message}"
            )

    def _run_structure_stage(
        self,
        text_content: str,
        user_query: str,
        *,
        design_expertise: str = "",
        runtime_directives: str = "",
        diagram_type: Optional[str] = None,
        content_area: Optional[str] = None,
    ):
        from .structure.state import WorkflowState as StructureState

        logger.info("[PipelineGenerator] Running StructureWorkflow...")
        stage_knowledge = self.build_stage_context("Structure", diagram_type)
        state = StructureState(
            text_content=text_content,
            user_query=user_query,
            canvas_library=self.canvas_library,
            stage_knowledge=stage_knowledge,
            design_expertise=design_expertise,
            runtime_directives=runtime_directives,
            diagram_type=diagram_type,
            content_area=content_area,
        )
        return self.structure.run(state)

    def _run_styling_stage(
        self,
        *,
        text_content: str,
        user_query: str,
        structure_state: Any,
        structure_instantiation: Any,
        structure_specification: Any,
        design_expertise: str,
        runtime_directives: str,
        diagram_type: Optional[str],
        content_area: Optional[str],
        palette_key: str,
    ):
        from .styling.state import WorkflowState as StylingState

        logger.info("[PipelineGenerator] Running StylingWorkflow...")
        stage_knowledge = self.build_stage_context("Styling", diagram_type)
        state = StylingState(
            text_content=text_content,
            user_query=user_query,
            canvas_library=self.canvas_library,
            structure_instantiation=structure_instantiation,
            structure_specification=structure_specification,
            stage_knowledge=stage_knowledge,
            design_expertise=design_expertise,
            runtime_directives=runtime_directives,
            diagram_type=diagram_type,
            content_area=content_area,
            conversation_history=list(structure_state.conversation_history),
            palette_key=palette_key,
        )
        return self.styling.run(state)

    def _run_layout_stage(
        self,
        *,
        text_content: str,
        user_query: str,
        styling_state: Any,
        structure_instantiation: Any,
        structure_specification: Any,
        styling_instantiation: Any,
        styling_specification: Any,
        design_expertise: str,
        runtime_directives: str,
        diagram_type: Optional[str],
        content_area: Optional[str],
    ):
        from .layout.state import WorkflowState as LayoutState

        logger.info("[PipelineGenerator] Running LayoutWorkflow...")
        stage_knowledge = self.build_stage_context("Layout", diagram_type)
        state = LayoutState(
            text_content=text_content,
            user_query=user_query,
            structure_instantiation=structure_instantiation,
            styling_instantiation=styling_instantiation,
            structure_specification=structure_specification,
            styling_specification=styling_specification,
            stage_knowledge=stage_knowledge,
            design_expertise=design_expertise,
            runtime_directives=runtime_directives,
            diagram_type=diagram_type,
            content_area=content_area,
            canvas_library=self.canvas_library,
            conversation_history=list(styling_state.conversation_history),
        )
        return self.layout.run(state)

    def begin_pipeline_run(
        self,
        text_content: str,
        user_query: str,
        *,
        design_expertise: str = "",
        runtime_directives: str = "",
        diagram_type: Optional[str] = None,
        content_area: Optional[str] = None,
    ) -> PipelineGenerationRun:
        """Initialize a pipeline run that can be advanced one stage at a time."""
        effective_diagram_type, palette_key = self.resolve_generation_context(
            text_content,
            user_query,
            diagram_type,
        )
        return PipelineGenerationRun(
            text_content=text_content,
            user_query=user_query,
            design_expertise=design_expertise,
            runtime_directives=runtime_directives,
            content_area=content_area,
            effective_diagram_type=effective_diagram_type,
            palette_key=palette_key,
        )

    def run_pipeline_stage(
        self,
        run_state: PipelineGenerationRun,
        stage_name: str,
        *,
        save_dir: Optional[str] = None,
    ) -> None:
        """Advance one pipeline stage and record canonical artifacts."""
        if stage_name == "structure":
            structure_state = self._run_structure_stage(
                text_content=run_state.text_content,
                user_query=run_state.user_query,
                design_expertise=run_state.design_expertise,
                runtime_directives=run_state.runtime_directives,
                diagram_type=run_state.effective_diagram_type,
                content_area=run_state.content_area,
            )
            self._raise_if_stage_failed("structure", structure_state)
            run_state.structure_state = structure_state
            run_state.structure_instantiation = structure_state.structure_instantiation
            run_state.structure_specification = structure_state.structure_specification
            run_state.effective_diagram_type = self._resolve_downstream_diagram_type(
                run_state.effective_diagram_type,
                run_state.structure_instantiation,
            )
            self._record_stage_artifacts(
                run_state.artifact_paths,
                save_dir=save_dir,
                stage_name="1_structure",
                artifact_name="structure",
                instantiation=run_state.structure_instantiation,
                specification=run_state.structure_specification,
            )
            return

        if stage_name == "styling":
            if run_state.structure_state is None:
                raise RuntimeError("Structure stage must run before styling.")
            styling_state = self._run_styling_stage(
                text_content=run_state.text_content,
                user_query=run_state.user_query,
                structure_state=run_state.structure_state,
                structure_instantiation=run_state.structure_instantiation,
                structure_specification=run_state.structure_specification,
                design_expertise=run_state.design_expertise,
                runtime_directives=run_state.runtime_directives,
                diagram_type=run_state.effective_diagram_type,
                content_area=run_state.content_area,
                palette_key=run_state.palette_key,
            )
            self._raise_if_stage_failed("styling", styling_state)
            run_state.styling_state = styling_state
            run_state.styling_instantiation = styling_state.styling_instantiation
            run_state.styling_specification = styling_state.styling_specification
            self._record_stage_artifacts(
                run_state.artifact_paths,
                save_dir=save_dir,
                stage_name="2_styling",
                artifact_name="styling",
                instantiation=run_state.styling_instantiation,
                specification=run_state.styling_specification,
            )
            return

        if stage_name == "layout":
            if run_state.styling_state is None:
                raise RuntimeError("Styling stage must run before layout.")
            layout_state = self._run_layout_stage(
                text_content=run_state.text_content,
                user_query=run_state.user_query,
                styling_state=run_state.styling_state,
                structure_instantiation=run_state.structure_instantiation,
                structure_specification=run_state.structure_specification,
                styling_instantiation=run_state.styling_instantiation,
                styling_specification=run_state.styling_specification,
                design_expertise=run_state.design_expertise,
                runtime_directives=run_state.runtime_directives,
                diagram_type=run_state.effective_diagram_type,
                content_area=run_state.content_area,
            )
            self._raise_if_stage_failed("layout", layout_state)
            run_state.layout_state = layout_state
            run_state.layout_instantiation = layout_state.layout_instantiation
            run_state.layout_specification = layout_state.layout_specification
            self._record_stage_artifacts(
                run_state.artifact_paths,
                save_dir=save_dir,
                stage_name="3_layout",
                artifact_name="layout",
                instantiation=run_state.layout_instantiation,
                specification=run_state.layout_specification,
            )
            return

        raise ValueError(f"Unknown pipeline generation stage: {stage_name}")

    @staticmethod
    def pipeline_outputs(run_state: PipelineGenerationRun) -> Dict[str, Any]:
        """Return the canonical pipeline output dict for a completed run."""
        return {
            "structure_instantiation": run_state.structure_instantiation,
            "structure_specification": run_state.structure_specification,
            "styling_instantiation": run_state.styling_instantiation,
            "styling_specification": run_state.styling_specification,
            "layout_instantiation": run_state.layout_instantiation,
            "layout_specification": run_state.layout_specification,
            "artifact_paths": dict(run_state.artifact_paths),
        }

    def run(
        self,
        text_content: str,
        user_query: str,
        *,
        design_expertise: str = "",
        runtime_directives: str = "",
        diagram_type: Optional[str] = None,
        content_area: Optional[str] = None,
        save_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        run_state = self.begin_pipeline_run(
            text_content,
            user_query,
            design_expertise=design_expertise,
            runtime_directives=runtime_directives,
            diagram_type=diagram_type,
            content_area=content_area,
        )

        for stage_name in PIPELINE_STAGE_SEQUENCE:
            self.run_pipeline_stage(run_state, stage_name, save_dir=save_dir)

        return self.pipeline_outputs(run_state)


class OneShotGeneratorWorkflow(GeneratorWorkflow):
    """Single-shot generation: one LLM call produces the complete scene.

    Optionally runs a lightweight RouterAgent first to classify diagram_type
    and palette_key, then injects those into the UnifiedGenerator so it
    receives the same type-specific knowledge (diagram context, stage rules,
    palette) that the pipeline mode enjoys.
    """

    def __init__(
        self,
        model: BaseChatModel,
        canvas_library: str = "excalidraw",
        router_model: Optional[BaseChatModel] = None,
        full_domain_knowledge: bool = True,
    ) -> None:
        canvas_library = normalize_canvas_library(canvas_library)
        require_generation_capability(canvas_library=canvas_library, mode="oneshot")
        self.canvas_library = canvas_library
        from .unified.workflow import UnifiedGeneratorWorkflow
        self.unified = UnifiedGeneratorWorkflow(
            model=model,
            full_domain_knowledge=full_domain_knowledge,
        )

        self._router: Optional[RouterAgent] = None
        if router_model is not None:
            self._router = RouterAgent(router_model)

    def run(
        self,
        text_content: str,
        user_query: str,
        *,
        design_expertise: str = "",
        runtime_directives: str = "",
        diagram_type: Optional[str] = None,
        content_area: Optional[str] = None,
        save_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        import json
        import os

        from .unified.state import UnifiedWorkflowState

        # --- Router (lightweight classification) ---
        palette_key = DEFAULT_PALETTE_KEY
        effective_diagram_type = diagram_type

        if self._router is not None:
            logger.info("[OneShotGenerator] Running RouterAgent...")
            router_result = self._router.run(text_content, user_query)
            palette_key = router_result.get("palette_key", "")
            if not effective_diagram_type:
                effective_diagram_type = router_result.get("diagram_type")
            logger.info(
                "[OneShotGenerator] Router: diagram_type=%s, palette_key=%s",
                effective_diagram_type, palette_key,
            )

        if effective_diagram_type:
            try:
                effective_diagram_type = normalize_supported_diagram_type(
                    effective_diagram_type,
                    field_name="diagram_type",
                )
            except DiagramTypeValidationError as exc:
                raise ValueError(str(exc)) from exc

        logger.info("[OneShotGenerator] Running UnifiedGeneratorWorkflow...")
        state = UnifiedWorkflowState(
            text_content=text_content,
            user_query=user_query,
            design_expertise=design_expertise,
            runtime_directives=runtime_directives,
            diagram_type=effective_diagram_type,
            palette_key=palette_key,
            content_area=content_area,
        )
        state = self.unified.run(state)

        # Persist the manifest when save_dir is provided (parity with pipeline).
        if save_dir and state.diagram_manifest:
            stage_dir = os.path.join(save_dir, "1_unified")
            os.makedirs(stage_dir, exist_ok=True)
            manifest_path = os.path.join(stage_dir, "diagram_manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(state.diagram_manifest, f, indent=2, ensure_ascii=False)
            artifact_paths = {"unified_manifest_path": manifest_path}
            if state.structure_instantiation:
                structure_path = os.path.join(stage_dir, "structure_instantiation.json")
                with open(structure_path, "w", encoding="utf-8") as f:
                    json.dump(
                        state.structure_instantiation,
                        f,
                        indent=2,
                        ensure_ascii=False,
                    )
                artifact_paths["structure_instantiation_path"] = structure_path
            if state.raw_llm_output:
                raw_path = os.path.join(stage_dir, "raw_llm_output.txt")
                with open(raw_path, "w", encoding="utf-8") as f:
                    f.write(state.raw_llm_output)
                artifact_paths["raw_llm_output_path"] = raw_path
        else:
            artifact_paths = {}

        return {
            "structure_instantiation": state.structure_instantiation,
            "diagram_manifest": state.diagram_manifest,
            "artifact_paths": artifact_paths,
        }


def create_generator(
    mode: str,
    model: BaseChatModel,
    *,
    canvas_library: str = "excalidraw",
    use_icons: bool = False,
    router_model: Optional[BaseChatModel] = None,
    full_domain_knowledge: bool = True,
) -> GeneratorWorkflow:
    """Factory: create a GeneratorWorkflow by mode name.

    Args:
        mode: ``"multiagent"`` (Structure → Styling → Layout) or ``"oneshot"``
            (single LLM call, experimental).
        model: LLM instance.
        canvas_library: Canvas target used by layout-stage prompts and validation.
        use_icons: Add Material Design icons to diagram nodes.
        router_model: Optional cheap model for the Router classifier. When
            provided, pre-determines diagram_type and palette_key before the
            main pipeline or unified agent runs. When ``None``, the router is
            skipped.
        full_domain_knowledge: When ``True``, every pipeline stage receives
            **all** stage rules (structure + styling + layout) instead of only
            the current stage's delta. Useful for experiments that need
            cross-stage context.

    Returns:
        A GeneratorWorkflow instance.
    """
    normalized_mode = normalize_generation_mode(mode)
    canvas_library = normalize_canvas_library(canvas_library)
    if normalized_mode == "multiagent":
        return PipelineGeneratorWorkflow(
            model,
            canvas_library=canvas_library,
            use_icons=use_icons,
            router_model=router_model,
            full_domain_knowledge=full_domain_knowledge,
        )
    return OneShotGeneratorWorkflow(
        model,
        canvas_library=canvas_library,
        router_model=router_model,
        full_domain_knowledge=full_domain_knowledge,
    )
