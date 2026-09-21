"""Text2Diagram Orchestrator — 5-phase pipeline.

Phase 1: Generate  — Structure → Styling → Layout
Phase 2: Render    — manifest JSON + PNG via canvas_environment
Phase 3: Verify    — objective checks + optional VLM critic
Phase 4: Refine    — deterministic + LLM fix loop (optional)
Phase 5: Finalize  — save outputs, report
"""

import os
import logging
import shutil
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from langchain_core.language_models import BaseChatModel

from evo_diagram.canvas_environment.capabilities import (
    require_generation_capability,
    require_refiner_capability,
)
from evo_diagram.agentic_system.config import AgenticSystemConfig
from evo_diagram.canvas_environment import (
    RenderResult,
    render_manifest,
    render_png_result,
)
from evo_diagram.canvas_runtime import normalize_canvas_library
from evo_diagram.config.settings import normalize_generation_mode
from evo_diagram.agentic_system.common.icon_assets import require_icon_assets_available
from evo_diagram.agentic_system.common.layout_contract import (
    LayoutValidationError,
    validate_layout_instantiation,
)
from evo_diagram.agentic_system.generation_stage.workflow import create_generator
from evo_diagram.agentic_system.generation_stage.structure.schemas import (
    StructureValidationError,
    validate_structure_instantiation,
)
from evo_diagram.agentic_system.generation_stage.styling.schemas import (
    StylingValidationError,
    validate_styling_instantiation,
)
from evo_diagram.agentic_system.verification_stage.workflow import VerifierWorkflow
from evo_diagram.agentic_system.iterative_workflow import IterativeRefinerWorkflow

from evo_diagram.utils.env_loader import ensure_env_loaded
from evo_diagram.utils.path_manager import EXPERIMENTS_DIR

ensure_env_loaded()

logger = logging.getLogger(__name__)
_DEFAULT_SAVE_DIR = object()
DEFAULT_WORKFLOW_SAVE_DIR = str(EXPERIMENTS_DIR)


def _save_json(filepath: str, data: Any) -> None:
    """Save JSON data to file, creating parent dirs as needed."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        import json
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved: {filepath}")


def _optional_str(value: Any) -> Optional[str]:
    return str(value) if value is not None else None


def _optional_bool(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _optional_int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _refinement_regression_reason(
    initial: Any, candidate: Any, *, compare_visual_scores: bool = True,
) -> Optional[str]:
    """Keep the baseline when verified refinement provides weaker evidence."""
    if initial is None or candidate is None:
        return None
    if _has_blocking_verification_errors(candidate):
        return "Candidate verification has blocking errors."
    before = getattr(initial, "objective_summary", None)
    after = getattr(candidate, "objective_summary", None)
    if not isinstance(before, dict) or not isinstance(after, dict):
        return None
    severities = ("critical", "major", "minor", "info")
    original_counts = tuple(int(before.get(key, 0) or 0) for key in severities)
    candidate_counts = tuple(int(after.get(key, 0) or 0) for key in severities)
    if candidate_counts > original_counts:
        return f"Objective findings regressed: {original_counts} -> {candidate_counts}."
    if candidate_counts < original_counts:
        return None
    if not compare_visual_scores:
        # Independent scores drift even on almost identical renders. When
        # paired comparison is enabled, let it judge the actual two images.
        return None
    original_score = getattr(getattr(initial, "critique", None), "overall_score", None)
    candidate_score = getattr(getattr(candidate, "critique", None), "overall_score", None)
    if isinstance(original_score, (float, int)) and candidate_score is None:
        return "Candidate critic was unavailable and objective findings did not improve."
    if isinstance(original_score, (float, int)) and isinstance(candidate_score, (float, int)):
        if original_score - candidate_score >= 0.5:
            return f"Critic score fell from {original_score:.1f} to {candidate_score:.1f} without fewer objective findings."
    return None


def _optional_string_list(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    return None


def _optional_int_dict(value: Any) -> Optional[Dict[str, int]]:
    if not isinstance(value, dict):
        return None
    result: Dict[str, int] = {}
    for key, item in value.items():
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            result[str(key)] = item
        elif isinstance(item, float) and item.is_integer():
            result[str(key)] = int(item)
    return result


def _has_error_values(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, (list, tuple)):
        return bool(value)
    return False


def _has_blocking_verification_errors(verifier_state: Any) -> bool:
    """Return whether verifier failures make refinement unsafe to run."""
    if verifier_state is None:
        return False

    has_blocking_errors = getattr(verifier_state, "has_blocking_errors", None)
    if has_blocking_errors is True:
        return True
    if has_blocking_errors is False:
        return False

    blocking_errors = getattr(verifier_state, "blocking_errors", None)
    if isinstance(blocking_errors, (list, tuple)):
        return bool(blocking_errors)
    if isinstance(blocking_errors, str):
        return bool(blocking_errors)

    return getattr(verifier_state, "has_errors", False) is True


def _finding_summary(finding: Any) -> Dict[str, Any]:
    if hasattr(finding, "model_dump"):
        return finding.model_dump()
    if isinstance(finding, dict):
        return dict(finding)
    return {"message": str(finding)}


def _refiner_findings_summary(refiner_state: Any) -> Optional[List[Dict[str, Any]]]:
    if refiner_state is None:
        return None
    latest_findings = getattr(refiner_state, "latest_findings", None)
    if not isinstance(latest_findings, list):
        return None
    return [_finding_summary(finding) for finding in latest_findings]


# ---------------------------------------------------------------------------
# Orchestrator state
# ---------------------------------------------------------------------------


class WorkflowState(BaseModel):
    """Top-level state for the full Text2Diagram pipeline."""

    text_content: str
    user_query: str

    # Generation outputs
    structure_instantiation: Optional[Dict] = None
    structure_specification: Optional[Dict] = None
    styling_instantiation: Optional[Dict] = None
    styling_specification: Optional[Dict] = None
    layout_instantiation: Optional[Dict] = None
    layout_specification: Optional[Dict] = None

    # Render outputs
    diagram_manifest: Optional[Dict] = None
    manifest_path: Optional[str] = None
    png_path: Optional[str] = None

    # Refinement outputs
    refined_diagram_manifest: Optional[Dict] = None
    refined_manifest_path: Optional[str] = None
    refined_png_path: Optional[str] = None
    refiner_status: Optional[str] = None
    refiner_converged: Optional[bool] = None
    refiner_degraded: bool = False
    refiner_errors: Optional[List[str]] = None
    refiner_termination_reason: Optional[str] = None
    refiner_latest_findings_summary: Optional[List[Dict[str, Any]]] = None
    refiner_candidate_manifest_path: Optional[str] = None
    refiner_candidate_png_path: Optional[str] = None

    # Final artifacts selected for downstream consumers.
    final_diagram_manifest: Optional[Dict] = None
    final_manifest_path: Optional[str] = None
    final_png_path: Optional[str] = None
    verification_report_path: Optional[str] = None
    verification_status: Optional[str] = None
    verification_quality_passed: Optional[bool] = None
    verification_cli_exit_code: Optional[int] = None
    verification_objective_summary: Optional[Dict[str, int]] = None
    verification_errors: Optional[List[str]] = None
    refiner_report_path: Optional[str] = None
    artifact_paths: Optional[Dict[str, str]] = None


@dataclass
class _RunDirectories:
    save_dir: str
    final_dir: Optional[str]
    temp_dir: Optional[tempfile.TemporaryDirectory]


@dataclass
class _GenerationArtifacts:
    structure_instantiation: Optional[Dict[str, Any]]
    structure_specification: Optional[Dict[str, Any]]
    styling_instantiation: Optional[Dict[str, Any]]
    styling_specification: Optional[Dict[str, Any]]
    layout_instantiation: Optional[Dict[str, Any]]
    layout_specification: Optional[Dict[str, Any]]
    diagram_manifest: Optional[Dict[str, Any]]
    artifact_paths: Dict[str, str]


class GenerationContractError(ValueError):
    """Raised when a generator returns an incomplete or malformed result."""


@dataclass
class _VerificationPhaseResult:
    state: Any
    output_dir: str


@dataclass
class _RefinementPhaseResult:
    manifest: Optional[Dict[str, Any]]
    png_path: Optional[str]
    state: Optional[Any] = None


@dataclass
class _FinalizeResult:
    manifest: Dict[str, Any]
    manifest_path: Optional[str]
    png_path: Optional[str]


@dataclass(frozen=True)
class _WorkflowOptions:
    mode: str
    canvas_library: str
    enable_refiner: bool
    refiner_max_iterations: int
    enable_verifier: bool
    verification_only: bool
    enable_critic: bool
    use_icons: bool
    enable_user_memory: bool
    user_id: str
    memory_db_path: Optional[str]
    full_domain_knowledge: bool


def _require_mapping(
    outputs: Dict[str, Any],
    field_name: str,
    *,
    mode: str,
) -> Dict[str, Any]:
    value = outputs.get(field_name)
    if not isinstance(value, dict):
        raise GenerationContractError(
            f"{mode} generator result missing required object field "
            f"{field_name!r}; got {type(value).__name__}."
        )
    return value


def _optional_mapping(
    outputs: Dict[str, Any],
    field_name: str,
    *,
    mode: str,
) -> Optional[Dict[str, Any]]:
    value = outputs.get(field_name)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise GenerationContractError(
            f"{mode} generator result field {field_name!r} must be an object "
            f"when present; got {type(value).__name__}."
        )
    return value


def _coerce_artifact_paths(outputs: Dict[str, Any], *, mode: str) -> Dict[str, str]:
    value = outputs.get("artifact_paths")
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise GenerationContractError(
            f"{mode} generator result field 'artifact_paths' must be an object "
            f"when present; got {type(value).__name__}."
        )
    invalid_keys = [
        key
        for key, path in value.items()
        if not isinstance(key, str) or not isinstance(path, str)
    ]
    if invalid_keys:
        sample = ", ".join(repr(key) for key in invalid_keys[:5])
        raise GenerationContractError(
            f"{mode} generator result artifact_paths contains non-string "
            f"key/path entries: {sample}."
        )
    return dict(value)


def _validate_artifact_field(
    mode: str,
    field_name: str,
    validator,
):
    try:
        return validator()
    except (
        StructureValidationError,
        StylingValidationError,
        LayoutValidationError,
        ValueError,
    ) as exc:
        raise GenerationContractError(
            f"{mode} generator result field {field_name!r} violates "
            f"the generation contract: {exc}"
        ) from exc


def _coerce_generation_artifacts(
    mode: str,
    outputs: Any,
    *,
    canvas_library: str = "excalidraw",
) -> _GenerationArtifacts:
    if not isinstance(outputs, dict):
        raise GenerationContractError(
            f"{mode} generator result must be a dict; got {type(outputs).__name__}."
        )

    artifact_paths = _coerce_artifact_paths(outputs, mode=mode)

    if mode == "oneshot":
        structure_instantiation = _validate_artifact_field(
            mode,
            "structure_instantiation",
            lambda: validate_structure_instantiation(
                _require_mapping(
                    outputs,
                    "structure_instantiation",
                    mode=mode,
                )
            ),
        )
        return _GenerationArtifacts(
            structure_instantiation=structure_instantiation,
            structure_specification=None,
            styling_instantiation=None,
            styling_specification=None,
            layout_instantiation=None,
            layout_specification=None,
            diagram_manifest=_require_mapping(outputs, "diagram_manifest", mode=mode),
            artifact_paths=artifact_paths,
        )

    structure_instantiation = _validate_artifact_field(
        mode,
        "structure_instantiation",
        lambda: validate_structure_instantiation(
            _require_mapping(
                outputs,
                "structure_instantiation",
                mode=mode,
            )
        ),
    )
    styling_instantiation = _validate_artifact_field(
        mode,
        "styling_instantiation",
        lambda: validate_styling_instantiation(
            _require_mapping(
                outputs,
                "styling_instantiation",
                mode=mode,
            ),
            structure_instantiation,
            canvas_library=canvas_library,
        ),
    )
    layout_instantiation = _validate_artifact_field(
        mode,
        "layout_instantiation",
        lambda: validate_layout_instantiation(
            _require_mapping(outputs, "layout_instantiation", mode=mode),
            structure_instantiation=structure_instantiation,
            styling_instantiation=styling_instantiation,
        ),
    )

    return _GenerationArtifacts(
        structure_instantiation=structure_instantiation,
        structure_specification=_optional_mapping(
            outputs,
            "structure_specification",
            mode=mode,
        ),
        styling_instantiation=styling_instantiation,
        styling_specification=_optional_mapping(
            outputs,
            "styling_specification",
            mode=mode,
        ),
        layout_instantiation=layout_instantiation,
        layout_specification=_optional_mapping(
            outputs,
            "layout_specification",
            mode=mode,
        ),
        diagram_manifest=_optional_mapping(outputs, "diagram_manifest", mode=mode),
        artifact_paths=artifact_paths,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Text2DiagramWorkflow:
    """5-phase pipeline: Generate → Render → Verify → Refine → Finalize."""

    def __init__(
        self,
        model: BaseChatModel,
        config: Optional[AgenticSystemConfig] = None,
        *,
        # Individual params are used by tests and lightweight programmatic callers.
        save_dir: str = DEFAULT_WORKFLOW_SAVE_DIR,
        canvas_library: str = "excalidraw",
        mode: str = "multiagent",
        enable_refiner: bool = False,
        refiner_max_iterations: int = 3,
        enable_verifier: bool = True,
        verification_only: bool = False,
        enable_critic: bool = True,
        enable_user_memory: bool = False,
        user_id: str = "default_user",
        memory_db_path: Optional[str] = None,
        router_model: Optional[BaseChatModel] = None,
        full_domain_knowledge: bool = True,
    ):
        options = self._resolve_options(
            config,
            mode=mode,
            canvas_library=canvas_library,
            enable_refiner=enable_refiner,
            refiner_max_iterations=refiner_max_iterations,
            enable_verifier=enable_verifier,
            verification_only=verification_only,
            enable_critic=enable_critic,
            enable_user_memory=enable_user_memory,
            user_id=user_id,
            memory_db_path=memory_db_path,
            full_domain_knowledge=full_domain_knowledge,
        )
        self.mode = normalize_generation_mode(options.mode)
        self.canvas_library = normalize_canvas_library(options.canvas_library)
        self.enable_refiner = options.enable_refiner
        self.refiner_max_iterations = options.refiner_max_iterations
        self.enable_verifier = options.enable_verifier
        self.verification_only = options.verification_only
        self.enable_critic = options.enable_critic
        self.use_icons = options.use_icons
        self.enable_user_memory = options.enable_user_memory
        self.user_id = options.user_id
        self.memory_db_path = options.memory_db_path
        self.full_domain_knowledge = options.full_domain_knowledge

        require_generation_capability(
            canvas_library=self.canvas_library,
            mode=self.mode,
        )
        if self.enable_refiner:
            require_refiner_capability(
                canvas_library=self.canvas_library,
                mode=self.mode,
            )
        if self.use_icons:
            require_icon_assets_available()

        # Generation workflow (pipeline or one-shot)
        self.generator = create_generator(
            self.mode, model,
            canvas_library=self.canvas_library,
            use_icons=self.use_icons,
            router_model=router_model,
            full_domain_knowledge=self.full_domain_knowledge,
        )

        self.save_dir = save_dir

        self.memory_system = self._init_memory_system()

        logger.info(f"Canvas library: {self.canvas_library}")

    @staticmethod
    def _resolve_options(
        config: Optional[AgenticSystemConfig],
        *,
        mode: str,
        canvas_library: str,
        enable_refiner: bool,
        refiner_max_iterations: int,
        enable_verifier: bool,
        verification_only: bool,
        enable_critic: bool,
        enable_user_memory: bool,
        user_id: str,
        memory_db_path: Optional[str],
        full_domain_knowledge: bool,
    ) -> _WorkflowOptions:
        if config is not None:
            return _WorkflowOptions(
                mode=config.mode,
                canvas_library=config.canvas_library,
                enable_refiner=config.enable_refiner,
                refiner_max_iterations=config.refiner_iterations,
                enable_verifier=config.enable_verifier,
                verification_only=config.verification_only,
                enable_critic=config.enable_critic,
                use_icons=config.use_icons,
                enable_user_memory=config.enable_user_memory,
                user_id=config.user_id,
                memory_db_path=getattr(config, "memory_db_path", None),
                full_domain_knowledge=getattr(config, "full_domain_knowledge", True),
            )

        return _WorkflowOptions(
            mode=mode,
            canvas_library=canvas_library,
            enable_refiner=enable_refiner,
            refiner_max_iterations=refiner_max_iterations,
            enable_verifier=enable_verifier,
            verification_only=verification_only,
            enable_critic=enable_critic,
            use_icons=False,
            enable_user_memory=enable_user_memory,
            user_id=user_id,
            memory_db_path=memory_db_path,
            full_domain_knowledge=full_domain_knowledge,
        )

    def _init_memory_system(self) -> Any:
        if not self.enable_user_memory:
            return None
        try:
            from evo_diagram.user_memory.main import UserPreferenceMemorySystem

            memory_system = UserPreferenceMemorySystem(
                user_id=self.user_id,
                memory_db_path=self.memory_db_path,
            )
            logger.info(f"User memory enabled for user: {self.user_id}")
            return memory_system
        except ImportError as e:
            logger.warning(f"Failed to initialize user memory: {e}")
            self.enable_user_memory = False
            return None

    # ------------------------------------------------------------------
    # User memory helpers
    # ------------------------------------------------------------------

    def _retrieve_user_preferences(
        self,
        diagram_type: Optional[str],
        content_area: Optional[str],
        agent_category: Optional[str] = None,
    ) -> str:
        if not self.memory_system:
            return ""
        try:
            scope_parts = []
            if diagram_type:
                scope_parts.append(f"{diagram_type} diagrams")
            if content_area:
                scope_parts.append(f"in {content_area}")
            query_scope = " ".join(scope_parts).strip()
            query = (
                f"User preferences for {query_scope}"
                if query_scope
                else "User diagram preferences"
            )
            categories = (
                [agent_category] if agent_category else ["Structure", "Styling", "Layout"]
            )
            all_prefs = []
            for cat in categories:
                prefs = self.memory_system.retrieve_preferences(
                    query=query,
                    agent_category=cat,
                    diagram_type=diagram_type,
                    content_area=content_area,
                    min_confidence=0.7,
                    top_k=3,
                )
                all_prefs.extend(prefs)
            if not all_prefs:
                return ""
            return self.memory_system.format_preferences_for_prompt(all_prefs, max_length=1000)
        except Exception as e:
            logger.warning(f"Failed to retrieve user preferences: {e}")
            return ""

    def build_design_expertise(
        self,
        design_expertise: str,
        diagram_type: Optional[str],
        content_area: Optional[str],
    ) -> str:
        """Build design expertise string, optionally enriched with user memory."""
        if not (self.enable_user_memory and self.memory_system):
            return design_expertise
        user_prefs = self._retrieve_user_preferences(
            diagram_type=diagram_type,
            content_area=content_area,
        )
        if user_prefs:
            return f"{design_expertise}\n\n{user_prefs}" if design_expertise else user_prefs
        return design_expertise

    # ------------------------------------------------------------------
    # Stepwise generation API for streaming callers
    # ------------------------------------------------------------------

    def _require_stepwise_generator(self) -> Any:
        """Return the selected generator if it supports staged execution."""
        if not all(
            hasattr(self.generator, attr)
            for attr in ("begin_pipeline_run", "run_pipeline_stage")
        ):
            raise RuntimeError(
                "Stepwise generation currently supports pipeline mode only."
            )
        return self.generator

    def begin_generation_run(
        self,
        text_content: str,
        user_query: str,
        *,
        design_expertise: str = "",
        runtime_directives: str = "",
        diagram_type: Optional[str] = None,
        content_area: Optional[str] = None,
    ) -> Any:
        """Start an observable Structure -> Styling -> Layout generation run.

        Backend streaming and other incremental callers should use this
        workflow-level API instead of reaching into ``self.generator``. The
        generator remains an implementation detail of the workflow.
        """
        return self._require_stepwise_generator().begin_pipeline_run(
            text_content,
            user_query,
            design_expertise=design_expertise,
            runtime_directives=runtime_directives,
            diagram_type=diagram_type,
            content_area=content_area,
        )

    def run_generation_stage(
        self,
        run_state: Any,
        stage_name: str,
        *,
        save_dir: Optional[str] = None,
    ) -> None:
        """Advance one staged generation step through the workflow boundary."""
        self._require_stepwise_generator().run_pipeline_stage(
            run_state,
            stage_name,
            save_dir=save_dir,
        )

    # ------------------------------------------------------------------
    # Pipeline phase helpers
    # ------------------------------------------------------------------

    def _resolve_run_directories(
        self,
        save_dir: Any,
        final_dir: Optional[str],
    ) -> _RunDirectories:
        """Resolve persistence directories for one workflow run."""
        temp_dir = None
        if save_dir is _DEFAULT_SAVE_DIR:
            save_dir = self.save_dir
        elif save_dir is None:
            temp_dir = tempfile.TemporaryDirectory(prefix="evodiagram_")
            save_dir = temp_dir.name
            logger.info(
                "Intermediate persistence disabled; using temporary workflow dir: %s",
                save_dir,
            )

        if final_dir is None:
            final_dir = save_dir

        return _RunDirectories(save_dir=save_dir, final_dir=final_dir, temp_dir=temp_dir)

    def _run_generation_phase(
        self,
        *,
        text_content: Any,
        user_query: Any,
        design_expertise: str,
        runtime_directives: str,
        diagram_type: Optional[str],
        content_area: Optional[str],
        save_dir: str,
    ) -> _GenerationArtifacts:
        """Run the selected generator and normalize its output contract."""
        full_design_expertise = self.build_design_expertise(
            design_expertise, diagram_type, content_area,
        )

        gen_outputs = self.generator.run(
            text_content=text_content,
            user_query=user_query,
            design_expertise=full_design_expertise,
            runtime_directives=runtime_directives,
            diagram_type=diagram_type,
            content_area=content_area,
            save_dir=save_dir,
        )

        return _coerce_generation_artifacts(
            self.mode,
            gen_outputs,
            canvas_library=self.canvas_library,
        )

    def _render_generation_output(
        self,
        generation: _GenerationArtifacts,
        *,
        save_dir: str,
    ) -> RenderResult:
        """Render generator output to a manifest JSON and PNG."""
        logger.info("=" * 60)
        logger.info("[Phase 2] Rendering manifest + PNG...")
        render_dir = os.path.join(save_dir, "4_render")
        os.makedirs(render_dir, exist_ok=True)

        if self.mode == "oneshot":
            render_result = self._render_oneshot_manifest(
                generation.diagram_manifest,
                render_dir=render_dir,
            )
            logger.info("[Phase 2] One-shot render complete: %s", render_result.png_path)
            return render_result

        render_result = render_manifest(
            layout_instantiation=generation.layout_instantiation,
            structure_instantiation=generation.structure_instantiation,
            canvas_library=self.canvas_library,
            output_dir=render_dir,
        )
        if not render_result.png_path or not os.path.exists(render_result.png_path):
            raise RuntimeError(f"Render failed: PNG not found at {render_result.png_path}")
        logger.info("[Phase 2] Render complete: %s", render_result.png_path)
        return render_result

    def _render_oneshot_manifest(
        self,
        diagram_manifest: Optional[Dict[str, Any]],
        *,
        render_dir: str,
    ) -> RenderResult:
        """Persist and render the manifest produced by one-shot generation."""
        if not isinstance(diagram_manifest, dict):
            raise RuntimeError("One-shot generator produced no diagram_manifest")

        manifest_path = os.path.join(render_dir, "diagram_manifest.json")
        _save_json(manifest_path, diagram_manifest)
        png_path = os.path.join(render_dir, "diagram_manifest.png")
        render_result = render_png_result(
            diagram_manifest,
            png_path,
            canvas_library=self.canvas_library,
        )
        if not render_result.ok:
            detail = f": {render_result.error}" if render_result.error else ""
            raise RuntimeError(f"One-shot render failed: {png_path}{detail}")

        return RenderResult(
            manifest=diagram_manifest,
            manifest_path=manifest_path,
            png_path=png_path,
        )

    def _run_verification_phase(
        self,
        *,
        render_result: RenderResult,
        generation: _GenerationArtifacts,
        text_content: Any,
        save_dir: str,
        output_subdir: str = "6_verification",
        phase_label: str = "Phase 3",
        artifact_report_keys: tuple[str, ...] = ("verification_report_path",),
    ) -> _VerificationPhaseResult:
        """Run verification when enabled and return its state and output dir."""
        verification_dir = os.path.join(save_dir, output_subdir)

        if not self.enable_verifier:
            logger.info("[%s] Verification skipped (--no-verifier)", phase_label)
            return _VerificationPhaseResult(state=None, output_dir=verification_dir)

        logger.info("=" * 60)
        logger.info("[%s] Running verification...", phase_label)
        os.makedirs(verification_dir, exist_ok=True)

        structure_path = generation.artifact_paths.get("structure_instantiation_path")
        layout_path = generation.artifact_paths.get("layout_instantiation_path")
        if self.mode == "oneshot":
            # Unified mode carries a Structure-shaped semantic sidecar but has
            # no Layout IR, so keep structure_path when present and skip only
            # layout-dependent checks.
            layout_path = None

        verifier = VerifierWorkflow()
        verifier_state = verifier.run(
            manifest_path=render_result.manifest_path,
            image_path=render_result.png_path,
            canvas_library=self.canvas_library,
            structure_path=structure_path,
            layout_path=layout_path,
            source_text=text_content,
            output_dir=verification_dir,
            skip_critic=not self.enable_critic,
            skip_checks=["layout_audit"] if self.mode == "oneshot" else None,
            emit_markdown=True,
        )
        logger.info(
            "[%s] Verification complete: status=%s, findings=%s",
            phase_label,
            verifier_state.status,
            len(verifier_state.objective_findings),
        )
        if verifier_state.report_path:
            for key in artifact_report_keys:
                generation.artifact_paths[key] = verifier_state.report_path

        return _VerificationPhaseResult(state=verifier_state, output_dir=verification_dir)

    def _run_final_verification_phase(
        self,
        *,
        finalize: _FinalizeResult,
        generation: _GenerationArtifacts,
        text_content: Any,
        save_dir: str,
        initial_verification: _VerificationPhaseResult,
        refinement: _RefinementPhaseResult,
    ) -> _VerificationPhaseResult:
        """Verify immutable refinement artifacts before selecting the final pair."""
        if refinement.manifest is None and refinement.png_path is None:
            return initial_verification

        if not finalize.manifest_path or not finalize.png_path:
            raise RuntimeError("Candidate verification requires persisted refinement artifacts.")

        final_render_result = RenderResult(
            manifest=finalize.manifest,
            manifest_path=finalize.manifest_path,
            png_path=finalize.png_path,
        )
        return self._run_verification_phase(
            render_result=final_render_result,
            generation=generation,
            text_content=text_content,
            save_dir=save_dir,
            output_subdir="8_final_verification",
            phase_label="Phase 5 final",
            artifact_report_keys=(
                "verification_report_path",
                "final_verification_report_path",
            ),
        )

    def _should_refine(self) -> bool:
        should_run = (
            self.enable_refiner
            and not self.verification_only
        )
        return should_run

    def _run_refinement_phase(
        self,
        *,
        render_result: RenderResult,
        generation: _GenerationArtifacts,
        verification: _VerificationPhaseResult,
        save_dir: str,
    ) -> _RefinementPhaseResult:
        """Run optional deterministic + LLM refinement loop."""
        if self.verification_only:
            logger.info("[Phase 3] Verification-only mode. Skipping refinement.")

        if not self._should_refine():
            logger.info("[Phase 4] Refinement skipped.")
            return _RefinementPhaseResult(manifest=None, png_path=None)
        if _has_blocking_verification_errors(verification.state):
            logger.warning(
                "[Phase 4] Refinement skipped because verification reported "
                "blocking errors: %s",
                getattr(
                    verification.state,
                    "blocking_errors",
                    getattr(verification.state, "errors", []),
                ),
            )
            return _RefinementPhaseResult(
                manifest=None,
                png_path=None,
                state=None,
            )

        logger.info("=" * 60)
        logger.info("[Phase 4] Running refinement loop...")
        refiner_dir = os.path.join(save_dir, "7_refiner")
        os.makedirs(refiner_dir, exist_ok=True)

        refiner = IterativeRefinerWorkflow()
        verifier_report_path = (
            getattr(verification.state, "report_path", None)
            if verification.state
            else None
        )
        refiner_state = refiner.run(
            manifest_path=render_result.manifest_path,
            image_path=render_result.png_path,
            structure_path=generation.artifact_paths.get("structure_instantiation_path"),
            layout_path=generation.artifact_paths.get("layout_instantiation_path"),
            verifier_report_path=verifier_report_path,
            output_dir=refiner_dir,
            canvas_library=self.canvas_library,
            max_iterations=self.refiner_max_iterations,
            skip_checks=["layout_audit"] if self.mode == "oneshot" else None,
            emit_markdown=True,
        )
        refiner_converged = getattr(refiner_state, "converged", None)
        logger.info(
            "[Phase 4] Refinement complete: status=%s, iterations=%s, converged=%s",
            refiner_state.status,
            refiner_state.current_iteration,
            refiner_converged,
        )
        refiner_report_path = getattr(refiner_state, "refiner_report_path", None)
        if isinstance(refiner_report_path, str) and refiner_report_path:
            generation.artifact_paths["refiner_report_path"] = refiner_report_path

        if refiner_state.status == "failed":
            raise RuntimeError(
                "Refinement failed: "
                + "; ".join(refiner_state.errors or ["unknown refiner error"])
            )

        if refiner_converged is not True:
            candidate_manifest_path = getattr(refiner_state, "candidate_manifest_path", None)
            candidate_image_path = getattr(refiner_state, "candidate_image_path", None)
            if isinstance(candidate_manifest_path, str) and candidate_manifest_path:
                generation.artifact_paths["refiner_candidate_manifest_path"] = candidate_manifest_path
            if isinstance(candidate_image_path, str) and candidate_image_path:
                generation.artifact_paths["refiner_candidate_png_path"] = candidate_image_path
            logger.warning(
                "[Phase 4] Refinement did not converge (termination_reason=%s); "
                "keeping original render as final output.",
                getattr(refiner_state, "termination_reason", None),
            )
            return _RefinementPhaseResult(
                manifest=None,
                png_path=None,
                state=refiner_state,
            )

        if not refiner_state.refined_manifest_path:
            return _RefinementPhaseResult(
                manifest=None,
                png_path=None,
                state=refiner_state,
            )

        import json

        with open(refiner_state.refined_manifest_path, "r", encoding="utf-8") as f:
            refined_manifest = json.load(f)

        refined_png_path = refiner_state.refined_image_path
        if not refined_png_path:
            raise RuntimeError(
                "Refiner produced a refined manifest but no refined PNG; "
                "refusing to mix refined JSON with the original render."
            )

        generation.artifact_paths["refined_manifest_path"] = refiner_state.refined_manifest_path
        generation.artifact_paths["refined_png_path"] = refined_png_path

        return _RefinementPhaseResult(
            manifest=refined_manifest,
            png_path=refined_png_path,
            state=refiner_state,
        )

    def _finalize_outputs(
        self,
        *,
        render_result: RenderResult,
        refinement: _RefinementPhaseResult,
        generation: _GenerationArtifacts,
        final_dir: Optional[str],
    ) -> _FinalizeResult:
        """Select final artifacts and copy them to the run's final directory."""
        logger.info("=" * 60)
        logger.info("[Phase 5] Finalizing...")

        final_manifest = refinement.manifest or render_result.manifest
        final_source_png_path = refinement.png_path or render_result.png_path
        final_manifest_path = None
        final_png_path = None

        if final_dir:
            os.makedirs(final_dir, exist_ok=True)
            final_manifest_path = os.path.join(final_dir, "final_diagram_manifest.json")
            final_png_path = os.path.join(final_dir, "rendered_diagram.png")
            _save_json(final_manifest_path, final_manifest)
            if not final_source_png_path or not os.path.exists(final_source_png_path):
                raise RuntimeError(f"Final PNG source missing: {final_source_png_path}")
            if os.path.abspath(final_source_png_path) != os.path.abspath(final_png_path):
                shutil.copyfile(final_source_png_path, final_png_path)
            generation.artifact_paths["final_manifest_path"] = final_manifest_path
            generation.artifact_paths["final_png_path"] = final_png_path

        return _FinalizeResult(
            manifest=final_manifest,
            manifest_path=final_manifest_path,
            png_path=final_png_path,
        )

    def _build_state(
        self,
        *,
        text_content: Any,
        user_query: Any,
        generation: _GenerationArtifacts,
        render_result: RenderResult,
        verification: _VerificationPhaseResult,
        refinement: _RefinementPhaseResult,
        finalize: _FinalizeResult,
    ) -> WorkflowState:
        """Build the public WorkflowState from phase results."""
        verifier_state = verification.state
        refiner_state = refinement.state
        return WorkflowState(
            text_content=text_content,
            user_query=user_query,
            structure_instantiation=generation.structure_instantiation,
            structure_specification=generation.structure_specification,
            styling_instantiation=generation.styling_instantiation,
            styling_specification=generation.styling_specification,
            layout_instantiation=generation.layout_instantiation,
            layout_specification=generation.layout_specification,
            diagram_manifest=render_result.manifest,
            manifest_path=render_result.manifest_path,
            png_path=render_result.png_path,
            refined_diagram_manifest=refinement.manifest,
            refined_manifest_path=generation.artifact_paths.get("refined_manifest_path"),
            refined_png_path=refinement.png_path,
            refiner_status=_optional_str(getattr(refiner_state, "status", None)),
            refiner_converged=_optional_bool(getattr(refiner_state, "converged", None)),
            refiner_degraded=bool(
                refiner_state is not None
                and (
                    _has_error_values(getattr(refiner_state, "errors", None))
                    or getattr(refiner_state, "status", None) == "reported_degraded"
                )
            ),
            refiner_errors=_optional_string_list(getattr(refiner_state, "errors", None)),
            refiner_termination_reason=_optional_str(
                getattr(refiner_state, "termination_reason", None)
            ),
            refiner_latest_findings_summary=_refiner_findings_summary(refiner_state),
            refiner_candidate_manifest_path=_optional_str(
                generation.artifact_paths.get("refiner_candidate_manifest_path")
                or getattr(refiner_state, "candidate_manifest_path", None)
            ),
            refiner_candidate_png_path=_optional_str(
                generation.artifact_paths.get("refiner_candidate_png_path")
                or getattr(refiner_state, "candidate_image_path", None)
            ),
            final_diagram_manifest=finalize.manifest,
            final_manifest_path=finalize.manifest_path,
            final_png_path=finalize.png_path,
            verification_report_path=verifier_state.report_path if verifier_state else None,
            verification_status=_optional_str(getattr(verifier_state, "status", None)),
            verification_quality_passed=_optional_bool(
                getattr(verifier_state, "quality_passed", None)
            ),
            verification_cli_exit_code=_optional_int(
                getattr(verifier_state, "cli_exit_code", None)
            ),
            verification_objective_summary=_optional_int_dict(
                getattr(verifier_state, "objective_summary", None)
            ),
            verification_errors=_optional_string_list(
                getattr(verifier_state, "errors", None)
            ),
            refiner_report_path=generation.artifact_paths.get("refiner_report_path"),
            artifact_paths=generation.artifact_paths,
        )

    @staticmethod
    def _clear_temp_paths(
        state: WorkflowState,
        directories: _RunDirectories,
    ) -> None:
        """Remove file paths that point into an already-cleaned temp run dir."""
        temp_root = os.path.abspath(directories.save_dir)

        def _is_temp_path(path: Any) -> bool:
            if not isinstance(path, str) or not path:
                return False
            try:
                return os.path.commonpath([temp_root, os.path.abspath(path)]) == temp_root
            except ValueError:
                return False

        for field_name in (
            "manifest_path",
            "png_path",
            "refined_manifest_path",
            "refined_png_path",
            "refiner_candidate_manifest_path",
            "refiner_candidate_png_path",
            "verification_report_path",
            "refiner_report_path",
            "final_manifest_path",
            "final_png_path",
        ):
            if _is_temp_path(getattr(state, field_name)):
                setattr(state, field_name, None)

        if isinstance(state.artifact_paths, dict):
            state.artifact_paths = {
                key: value
                for key, value in state.artifact_paths.items()
                if not _is_temp_path(value)
            }

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    def _compare_refinement_visuals(
        self,
        initial_state: Any,
        candidate_state: Any,
        original_path: Optional[str],
        candidate_path: Optional[str],
        text_content: str,
        save_dir: str,
        artifact_paths: Dict[str, str],
    ) -> Optional[str]:
        """Require visible benefit when refinement ties objective quality."""
        if not self.enable_critic or not original_path or not candidate_path:
            return None
        before = getattr(initial_state, "objective_summary", None)
        after = getattr(candidate_state, "objective_summary", None)
        if not isinstance(before, dict) or not isinstance(after, dict):
            return None
        severities = ("critical", "major", "minor", "info")
        if any(int(before.get(key, 0) or 0) != int(after.get(key, 0) or 0) for key in severities):
            return None
        from .verification_stage.critic.comparison import compare_rendered_diagrams

        report: Dict[str, Any] = {
            "original_path": original_path, "candidate_path": candidate_path,
        }
        try:
            report.update(compare_rendered_diagrams(original_path, candidate_path, text_content))
            rejection = None if report["winner"] == "candidate" else (
                "Side-by-side comparison found no clear refinement improvement: " + report["reason"]
            )
        except Exception as exc:
            logger.warning("Refinement comparison unavailable: %s", exc)
            report.update({"winner": "original", "error": str(exc)})
            rejection = "Visual comparison unavailable; preserving the equally verified original."
        report_path = os.path.join(save_dir, "8_final_verification", "refinement_comparison.json")
        _save_json(report_path, report)
        artifact_paths["refiner_comparison_report_path"] = report_path
        return rejection

    def run(
        self,
        text_content: Any,
        user_query: Any,
        runtime_directives: Optional[str] = None,
        save_dir: Any = _DEFAULT_SAVE_DIR,
        final_dir: Optional[str] = None,
        design_expertise: Optional[str] = None,
        diagram_type: Optional[str] = None,
        content_area: Optional[str] = None,
    ) -> WorkflowState:
        """Run the full Text2Diagram pipeline."""
        directories = self._resolve_run_directories(save_dir, final_dir)
        state: Optional[WorkflowState] = None
        try:
            generation = self._run_generation_phase(
                text_content=text_content,
                user_query=user_query,
                design_expertise=design_expertise or "",
                runtime_directives=runtime_directives or "",
                diagram_type=diagram_type,
                content_area=content_area,
                save_dir=directories.save_dir,
            )
            render_result = self._render_generation_output(
                generation,
                save_dir=directories.save_dir,
            )
            generation.artifact_paths["render_manifest_path"] = render_result.manifest_path
            generation.artifact_paths["render_png_path"] = render_result.png_path

            verification = self._run_verification_phase(
                render_result=render_result,
                generation=generation,
                text_content=text_content,
                save_dir=directories.save_dir,
                artifact_report_keys=(
                    "pre_refine_verification_report_path",
                    "verification_report_path",
                ),
            )
            refinement = self._run_refinement_phase(
                render_result=render_result,
                generation=generation,
                verification=verification,
                save_dir=directories.save_dir,
            )
            # Verify immutable refinement artifacts before promoting them.
            # Reports must continue to point at the candidate even if it is
            # rejected; never overwrite the image that a report evaluated.
            candidate_artifacts = _FinalizeResult(
                manifest=refinement.manifest or render_result.manifest,
                manifest_path=(
                    generation.artifact_paths.get("refined_manifest_path")
                    or render_result.manifest_path
                ),
                png_path=refinement.png_path or render_result.png_path,
            )
            final_verification = self._run_final_verification_phase(
                finalize=candidate_artifacts,
                generation=generation,
                text_content=text_content,
                save_dir=directories.save_dir,
                initial_verification=verification,
                refinement=refinement,
            )
            rejection = _refinement_regression_reason(
                verification.state, final_verification.state,
                compare_visual_scores=not self.enable_critic,
            )
            if rejection is None and refinement.manifest is not None:
                rejection = self._compare_refinement_visuals(
                    verification.state, final_verification.state,
                    render_result.png_path, candidate_artifacts.png_path,
                    text_content, directories.save_dir, generation.artifact_paths,
                )
            if rejection and refinement.manifest is not None:
                logger.warning("[Phase 5] Rejecting refined candidate: %s", rejection)
                generation.artifact_paths["refiner_candidate_manifest_path"] = candidate_artifacts.manifest_path
                generation.artifact_paths["refiner_candidate_png_path"] = candidate_artifacts.png_path
                candidate_report = generation.artifact_paths.pop("final_verification_report_path", None)
                if candidate_report:
                    generation.artifact_paths["refiner_candidate_verification_report_path"] = candidate_report
                generation.artifact_paths.pop("refined_manifest_path", None)
                generation.artifact_paths.pop("refined_png_path", None)
                original_report = generation.artifact_paths.get("pre_refine_verification_report_path")
                if original_report:
                    generation.artifact_paths["verification_report_path"] = original_report
                refinement = _RefinementPhaseResult(
                    manifest=None, png_path=None, state=refinement.state,
                )
                final_verification = verification
            finalize = self._finalize_outputs(
                render_result=render_result,
                refinement=refinement,
                generation=generation,
                final_dir=directories.final_dir,
            )
            state = self._build_state(
                text_content=text_content,
                user_query=user_query,
                generation=generation,
                render_result=render_result,
                verification=final_verification,
                refinement=refinement,
                finalize=finalize,
            )
            logger.info("Workflow completed!")
            return state
        finally:
            if directories.temp_dir is not None:
                if state is not None:
                    self._clear_temp_paths(state, directories)
                directories.temp_dir.cleanup()
                logger.info("Cleaned temporary workflow dir: %s", directories.save_dir)
