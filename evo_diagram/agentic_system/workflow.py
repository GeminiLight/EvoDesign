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
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

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

# Markers that fence the retrieved design-memory block inside the assembled
# ``design_expertise`` string. The block has to stay one identifiable segment:
# ``WorkflowState.design_memory_retrieved_items`` is the provenance record for
# exactly this text, and interleaving it with caller-supplied expertise or user
# preferences would make that record unverifiable.
DESIGN_MEMORY_SECTION_HEADER = "=== RETRIEVED DESIGN KNOWLEDGE ==="
DESIGN_MEMORY_SECTION_FOOTER = "=== END RETRIEVED DESIGN KNOWLEDGE ==="

DEFAULT_DESIGN_MEMORY_TOP_K = 5
DEFAULT_DESIGN_MEMORY_SCORE_THRESHOLD = 0.0

# Process-wide cache of design-memory retrievers, keyed by the two inputs that
# decide which store is opened.
_DESIGN_MEMORY_CACHE: Dict[Tuple[Optional[str], Optional[str]], Tuple[Any, Optional[str]]] = {}
_DESIGN_MEMORY_CACHE_LOCK = threading.Lock()


def reset_design_memory_cache() -> None:
    """Drop the shared design-memory retrievers (tests, or after a rebuild)."""
    with _DESIGN_MEMORY_CACHE_LOCK:
        _DESIGN_MEMORY_CACHE.clear()


def _load_design_memory_retriever(
    vector_db_path: Optional[str],
    embedding_model_name: Optional[str],
) -> Tuple[Any, Optional[str]]:
    """Return ``(retriever, error_message)`` for the shared design-memory store.

    Constructing ``DiagramDesignMemory`` loads a sentence-transformer model and
    opens the Chroma collection, so it must happen once per process rather than
    once per generation. Caching on the workflow instance is not enough:
    ``agentic_system/main.py`` builds one ``Text2DiagramWorkflow`` per dataset
    item, which would pay the load cost for every example. Failures are cached
    too, so a missing optional dependency is diagnosed once instead of once per
    item.
    """
    key = (vector_db_path, embedding_model_name)
    with _DESIGN_MEMORY_CACHE_LOCK:
        cached = _DESIGN_MEMORY_CACHE.get(key)
        if cached is not None:
            return cached
        try:
            from evo_diagram.design_memory import (
                DiagramDesignMemory,
                DiagramDesignRetriever,
            )

            memory = DiagramDesignMemory(
                vector_db_path=vector_db_path,
                embedding_model_name=embedding_model_name,
            )
            result: Tuple[Any, Optional[str]] = (
                DiagramDesignRetriever(design_memory=memory),
                None,
            )
        except ImportError as exc:
            # chromadb / sentence-transformers are optional extras.
            result = (None, f"design memory dependencies unavailable: {exc}")
        except Exception as exc:  # noqa: BLE001 - includes the embedding-model /
            # distance-space consistency check, which raises RuntimeError on a
            # store built with a different metric or model.
            result = (None, f"design memory initialization failed: {exc}")
        _DESIGN_MEMORY_CACHE[key] = result
        return result


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
    from .quality_policy import refinement_rejection
    return refinement_rejection(initial, candidate)


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


def _optional_retrieved_items(value: Any) -> Optional[List[Dict[str, str]]]:
    """Normalize design-memory provenance records for the public state."""
    if not isinstance(value, (list, tuple)):
        return None
    items: List[Dict[str, str]] = [
        {str(key): str(item) for key, item in entry.items()}
        for entry in value
        if isinstance(entry, dict)
    ]
    return items or None


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
    quality_status: str = "unverified"
    verification_cli_exit_code: Optional[int] = None
    verification_objective_summary: Optional[Dict[str, int]] = None
    verification_errors: Optional[List[str]] = None
    refiner_report_path: Optional[str] = None
    user_memory_enabled: bool = False
    user_memory_degraded: bool = False
    user_memory_errors: Optional[List[str]] = None
    # Design memory observability. ``design_memory_enabled`` says design
    # knowledge was actually available for injection, ``design_memory_degraded``
    # says it was requested but could not be used (missing store, missing
    # dependency, failed consistency check, failed retrieval), and
    # ``design_memory_retrieved_items`` records which entries reached the prompt.
    design_memory_enabled: bool = False
    design_memory_degraded: bool = False
    design_memory_errors: Optional[List[str]] = None
    design_memory_retrieved_items: Optional[List[Dict[str, str]]] = None
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
    enable_design_memory: bool
    design_memory_db_path: Optional[str]
    design_memory_embedding_model: Optional[str]
    design_memory_top_k: int
    design_memory_score_threshold: float


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
        always_refine: bool = False,
        refiner_max_iterations: int = 3,
        enable_verifier: bool = True,
        verification_only: bool = False,
        enable_critic: bool = True,
        use_icons: bool = False,
        enable_user_memory: bool = False,
        user_id: str = "default_user",
        memory_db_path: Optional[str] = None,
        router_model: Optional[BaseChatModel] = None,
        full_domain_knowledge: bool = True,
        # Design memory is opt-in on this path and on by default only through
        # AgenticSystemConfig. Bare-kwarg callers include the backend request
        # path and knowledge_evolution's knowledge-free control run, which must
        # keep generating without retrieved knowledge for its baseline to mean
        # anything.
        enable_design_memory: bool = False,
        design_memory_db_path: Optional[str] = None,
        design_memory_embedding_model: Optional[str] = None,
        design_memory_top_k: int = DEFAULT_DESIGN_MEMORY_TOP_K,
        design_memory_score_threshold: float = DEFAULT_DESIGN_MEMORY_SCORE_THRESHOLD,
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
            use_icons=use_icons,
            enable_user_memory=enable_user_memory,
            user_id=user_id,
            memory_db_path=memory_db_path,
            full_domain_knowledge=full_domain_knowledge,
            enable_design_memory=enable_design_memory,
            design_memory_db_path=design_memory_db_path,
            design_memory_embedding_model=design_memory_embedding_model,
            design_memory_top_k=design_memory_top_k,
            design_memory_score_threshold=design_memory_score_threshold,
        )
        self.mode = normalize_generation_mode(options.mode)
        self.canvas_library = normalize_canvas_library(options.canvas_library)
        self.always_refine = always_refine
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
        self.enable_design_memory = options.enable_design_memory
        self.design_memory_db_path = options.design_memory_db_path
        self.design_memory_embedding_model = options.design_memory_embedding_model
        self.design_memory_top_k = options.design_memory_top_k
        self.design_memory_score_threshold = options.design_memory_score_threshold

        require_generation_capability(
            canvas_library=self.canvas_library,
            mode=self.mode,
        )
        if self.enable_refiner:
            require_refiner_capability(
                canvas_library=self.canvas_library,
                mode=self.mode,
            )
        if self.use_icons and self.canvas_library != "excalidraw":
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

        # User memory observability: set when preference retrieval fails so the
        # run does not silently pretend preferences were injected.
        self.user_memory_degraded = False
        self.user_memory_errors: List[str] = []
        self.memory_system = self._init_memory_system()

        # Same observability contract for design memory: a run must never look
        # like it used evolved design knowledge when it did not.
        self.design_memory_degraded = False
        self.design_memory_errors: List[str] = []
        self.design_memory_retrieved_items: List[Dict[str, str]] = []
        self.design_memory_retriever = self._init_design_memory()

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
        use_icons: bool,
        enable_user_memory: bool,
        user_id: str,
        memory_db_path: Optional[str],
        full_domain_knowledge: bool,
        enable_design_memory: bool,
        design_memory_db_path: Optional[str],
        design_memory_embedding_model: Optional[str],
        design_memory_top_k: int,
        design_memory_score_threshold: float,
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
                # getattr defaults keep config-shaped duck types (and older
                # pickled configs) working, as the fields above already do.
                enable_design_memory=bool(
                    getattr(config, "enable_design_memory", False)
                ),
                design_memory_db_path=getattr(config, "design_memory_db_path", None),
                design_memory_embedding_model=getattr(
                    config, "design_memory_embedding_model", None
                ),
                design_memory_top_k=int(
                    getattr(config, "design_memory_top_k", DEFAULT_DESIGN_MEMORY_TOP_K)
                ),
                design_memory_score_threshold=float(
                    getattr(
                        config,
                        "design_memory_score_threshold",
                        DEFAULT_DESIGN_MEMORY_SCORE_THRESHOLD,
                    )
                ),
            )

        return _WorkflowOptions(
            mode=mode,
            canvas_library=canvas_library,
            enable_refiner=enable_refiner,
            refiner_max_iterations=refiner_max_iterations,
            enable_verifier=enable_verifier,
            verification_only=verification_only,
            enable_critic=enable_critic,
            use_icons=use_icons,
            enable_user_memory=enable_user_memory,
            user_id=user_id,
            memory_db_path=memory_db_path,
            full_domain_knowledge=full_domain_knowledge,
            enable_design_memory=enable_design_memory,
            design_memory_db_path=design_memory_db_path,
            design_memory_embedding_model=design_memory_embedding_model,
            design_memory_top_k=design_memory_top_k,
            design_memory_score_threshold=design_memory_score_threshold,
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
    # Design memory
    # ------------------------------------------------------------------

    def _init_design_memory(self) -> Any:
        """Return the shared design-memory retriever, or ``None`` if unusable.

        Design knowledge is an enhancement, never a precondition. A missing
        vector store, a missing optional dependency (chromadb /
        sentence-transformers) and a failed embedding-model / distance-space
        consistency check all end the same way: no retriever, a recorded error,
        a warning, and a run that generates normally without design knowledge.
        """
        if not self.enable_design_memory:
            return None

        db_path = self.design_memory_db_path
        if db_path and not os.path.isdir(db_path):
            # Cheap pre-check. It keeps the heavy optional imports out of runs
            # that have no evolved knowledge yet, and stops an empty store from
            # being created where the evolution pipeline never wrote one.
            self._record_design_memory_error(
                f"design memory vector store not found: {db_path}"
            )
            logger.warning(
                "Design memory is enabled but no vector store exists at %s; "
                "generating without design knowledge.",
                db_path,
            )
            return None

        retriever, error = _load_design_memory_retriever(
            db_path,
            self.design_memory_embedding_model,
        )
        if retriever is None:
            self._record_design_memory_error(error or "design memory unavailable")
            logger.warning(
                "Design memory unavailable (%s); generating without design "
                "knowledge.",
                error,
            )
            return None

        logger.info("Design memory enabled (vector store: %s)", db_path)
        return retriever

    def _record_design_memory_error(self, message: str) -> None:
        """Mark design memory as degraded and keep the errors for the state."""
        self.design_memory_degraded = True
        errors = getattr(self, "design_memory_errors", None)
        if not isinstance(errors, list):
            errors = []
            self.design_memory_errors = errors
        if message not in errors:
            errors.append(message)

    def _design_memory_is_active(self) -> bool:
        """Whether evolved design knowledge can actually be retrieved."""
        return bool(
            getattr(self, "enable_design_memory", False)
            and getattr(self, "design_memory_retriever", None) is not None
        )

    def _retrieve_design_expertise(
        self,
        user_query: Optional[str],
        diagram_type: Optional[str],
        content_area: Optional[str],
        retrieval_query: str = "",
    ) -> Optional[str]:
        """Return prompt-ready design knowledge for this request.

        Returns ``""`` when design memory answered but holds nothing relevant,
        and ``None`` when retrieval itself failed. As with user memory, callers
        must treat ``None`` as "design memory did not take effect" rather than
        as an empty knowledge set.

        ``DiagramDesignRetriever.retrieve_design_expertise`` owns the rules that
        make retrieved knowledge safe to show a model (``active=True`` and
        ``polarity="positive"`` only). Those rules are deliberately not
        re-implemented here: rebuilding them would risk feeding archived
        tombstones or anti-pattern entries straight into a generator prompt.
        """
        retriever = getattr(self, "design_memory_retriever", None)
        if retriever is None:
            return ""

        query = str(user_query or "")
        retrieval_query = str(retrieval_query or "")
        if not (
            query.strip()
            or retrieval_query.strip()
            or diagram_type
            or content_area
        ):
            # With no query signal at all a similarity search returns arbitrary
            # knowledge rather than relevant knowledge, so skip it.
            logger.debug("Skipping design memory retrieval: empty query signal.")
            return ""

        try:
            expertise, retrieved_items = retriever.retrieve_design_expertise(
                query,
                diagram_type=diagram_type or "",
                content_area=content_area or "",
                retrieval_query=retrieval_query,
                top_k=getattr(self, "design_memory_top_k", DEFAULT_DESIGN_MEMORY_TOP_K),
                score_threshold=getattr(
                    self,
                    "design_memory_score_threshold",
                    DEFAULT_DESIGN_MEMORY_SCORE_THRESHOLD,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - vector stores raise freely
            self._record_design_memory_error(f"retrieve_design_expertise: {exc}")
            logger.error(
                "Design memory retrieval failed: %s", exc, exc_info=True
            )
            return None

        self.design_memory_retrieved_items = [
            {str(key): str(value) for key, value in item.items()}
            for item in (retrieved_items or [])
            if isinstance(item, dict)
        ]
        return expertise or ""

    # ------------------------------------------------------------------
    # User memory helpers
    # ------------------------------------------------------------------

    def _retrieve_user_preferences(
        self,
        diagram_type: Optional[str],
        content_area: Optional[str],
        agent_category: Optional[str] = None,
    ) -> Optional[str]:
        """Return formatted user preferences.

        Returns ``""`` when the memory system answered but holds nothing for the
        current scope, and ``None`` when retrieval itself failed. Callers must
        treat ``None`` as "user memory did not take effect" rather than as an
        empty preference set.
        """
        if not self.memory_system:
            return ""
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
        failed_categories: List[str] = []
        for cat in categories:
            # Query per category so one failing category cannot discard the
            # preferences the other categories already returned.
            try:
                prefs = self.memory_system.retrieve_preferences(
                    query=query,
                    agent_category=cat,
                    diagram_type=diagram_type,
                    content_area=content_area,
                    min_confidence=0.7,
                    top_k=3,
                )
            except Exception as e:  # noqa: BLE001 - storage backends raise freely
                failed_categories.append(cat)
                self._record_user_memory_error(f"{cat}: {e}")
                logger.error(
                    "User preference retrieval failed for category %s: %s",
                    cat,
                    e,
                    exc_info=True,
                )
                continue
            all_prefs.extend(prefs)

        if failed_categories and not all_prefs:
            logger.error(
                "User memory is enabled but no preferences could be retrieved "
                "(failed categories: %s); generation continues without them.",
                ", ".join(failed_categories),
            )
            return None
        if not all_prefs:
            return ""
        try:
            return self.memory_system.format_preferences_for_prompt(
                all_prefs,
                max_length=1000,
            )
        except Exception as e:  # noqa: BLE001 - formatting must not abort a run
            self._record_user_memory_error(f"format_preferences_for_prompt: {e}")
            logger.error("Failed to format user preferences: %s", e, exc_info=True)
            return None

    def _record_user_memory_error(self, message: str) -> None:
        """Mark user memory as degraded and keep the first errors for the state."""
        self.user_memory_degraded = True
        errors = getattr(self, "user_memory_errors", None)
        if not isinstance(errors, list):
            errors = []
            self.user_memory_errors = errors
        if message not in errors:
            errors.append(message)

    def build_design_expertise(
        self,
        design_expertise: str,
        diagram_type: Optional[str],
        content_area: Optional[str],
        *,
        user_query: str = "",
        retrieval_query: str = "",
    ) -> str:
        """Assemble the design expertise block handed to the generator.

        Up to three sources are concatenated as separate, self-contained
        segments joined by a blank line. They are never interleaved: the
        design-memory segment is fenced by
        :data:`DESIGN_MEMORY_SECTION_HEADER` / :data:`DESIGN_MEMORY_SECTION_FOOTER`
        so that it stays identifiable, which is what makes the provenance in
        ``WorkflowState.design_memory_retrieved_items`` checkable against the
        text that actually reached the prompt.

        Order, highest authority first:

        1. ``design_expertise`` — what the caller passed in. It is never
           rewritten, reordered or dropped, because an explicit argument is an
           instruction and retrieval is only a supplement.
        2. retrieved design memory — evolved, system-level design knowledge.
           It follows the caller's text so the two design-knowledge blocks stay
           adjacent and the retrieved block reads as an addition to it.
        3. user preferences — personalisation stays last, exactly where it was
           before design memory existed, so a stored user preference remains the
           final (and in practice strongest) signal in the block.

        ``user_query`` and ``retrieval_query`` are keyword-only with empty
        defaults so the existing three-positional-argument callers keep working
        unchanged; with no query signal at all, retrieval is skipped rather than
        run against an empty query.
        """
        segments: List[str] = [design_expertise] if design_expertise else []

        if self._design_memory_is_active():
            retrieved = self._retrieve_design_expertise(
                user_query=user_query,
                diagram_type=diagram_type,
                content_area=content_area,
                retrieval_query=retrieval_query,
            )
            if retrieved is None:
                logger.error(
                    "Proceeding without design memory; the generated diagram "
                    "will not reflect evolved design knowledge for this run."
                )
            elif retrieved:
                segments.append(
                    f"{DESIGN_MEMORY_SECTION_HEADER}\n"
                    f"{retrieved}\n"
                    f"{DESIGN_MEMORY_SECTION_FOOTER}"
                )

        if getattr(self, "enable_user_memory", False) and getattr(
            self, "memory_system", None
        ):
            user_prefs = self._retrieve_user_preferences(
                diagram_type=diagram_type,
                content_area=content_area,
            )
            if user_prefs is None:
                logger.error(
                    "Proceeding without user preferences; the generated diagram "
                    "will not reflect stored user memory for this run."
                )
            elif user_prefs:
                segments.append(user_prefs)

        return "\n\n".join(segments)

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
        # ``retrieval_query`` stays empty here: the Router that produces one
        # runs inside the generator, after this point, so design memory falls
        # back to the user query as its semantic query.
        full_design_expertise = self.build_design_expertise(
            design_expertise,
            diagram_type,
            content_area,
            user_query=str(user_query or ""),
        )

        from .common.design_constraints import build_design_constraints
        runtime = {}
        try:
            runtime = json.loads(runtime_directives.split("\n", 1)[1]) if runtime_directives else {}
        except (ValueError, IndexError):
            pass
        self.design_constraints = build_design_constraints(
            source_text=str(text_content or ""), requirements=str(user_query or ""),
            design_expertise=design_expertise, diagram_type=diagram_type,
            use_icons=getattr(self, "use_icons", False), locked_nodes=runtime.get("locked_nodes", []),
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
            design_constraints=getattr(self, "design_constraints", ""),
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

        from .quality_policy import should_refine
        if not self._should_refine() or not should_refine(verification.state, force=getattr(self, "always_refine", False)):
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
            design_constraints=getattr(self, "design_constraints", ""),
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
            # Refinement is an optional enhancement stage. A refiner failure must
            # not discard an already rendered and verified diagram; degrade to the
            # original render and let the state carry the failure signal.
            self._record_refiner_candidate_artifacts(refiner_state, generation)
            logger.error(
                "[Phase 4] Refinement failed (%s); keeping original render as "
                "final output (refiner_degraded=True).",
                "; ".join(refiner_state.errors or ["unknown refiner error"]),
            )
            return _RefinementPhaseResult(
                manifest=None,
                png_path=None,
                state=refiner_state,
            )

        if refiner_converged is not True:
            self._record_refiner_candidate_artifacts(refiner_state, generation)
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

    @staticmethod
    def _record_refiner_candidate_artifacts(
        refiner_state: Any,
        generation: _GenerationArtifacts,
    ) -> None:
        """Expose non-adopted refiner artifacts so degraded runs stay debuggable."""
        candidate_manifest_path = getattr(refiner_state, "candidate_manifest_path", None)
        candidate_image_path = getattr(refiner_state, "candidate_image_path", None)
        if isinstance(candidate_manifest_path, str) and candidate_manifest_path:
            generation.artifact_paths["refiner_candidate_manifest_path"] = candidate_manifest_path
        if isinstance(candidate_image_path, str) and candidate_image_path:
            generation.artifact_paths["refiner_candidate_png_path"] = candidate_image_path

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
        from .quality_policy import quality_summary, quality_status
        verifier_state = verification.state
        refiner_state = refinement.state
        return WorkflowState(
            text_content=text_content,
            user_query=user_query,
            quality_status=quality_status(quality_summary(verifier_state)),
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
                    or getattr(refiner_state, "status", None)
                    in {"reported_degraded", "failed"}
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
            user_memory_enabled=bool(
                getattr(self, "enable_user_memory", False)
                and getattr(self, "memory_system", None) is not None
            ),
            user_memory_degraded=bool(getattr(self, "user_memory_degraded", False)),
            user_memory_errors=_optional_string_list(
                getattr(self, "user_memory_errors", None)
            ),
            design_memory_enabled=bool(
                getattr(self, "enable_design_memory", False)
                and getattr(self, "design_memory_retriever", None) is not None
            ),
            design_memory_degraded=bool(
                getattr(self, "design_memory_degraded", False)
            ),
            design_memory_errors=_optional_string_list(
                getattr(self, "design_memory_errors", None)
            ),
            design_memory_retrieved_items=_optional_retrieved_items(
                getattr(self, "design_memory_retrieved_items", None)
            ),
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
