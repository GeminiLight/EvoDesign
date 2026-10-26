import logging
from dataclasses import dataclass
from typing import Optional

from evo_diagram.canvas_environment.capabilities import (
    require_generation_capability,
    require_refiner_capability,
)
from evo_diagram.canvas_runtime import normalize_canvas_library
from evo_diagram.config.settings import normalize_generation_mode


logger = logging.getLogger(__name__)


# Variant → default configuration mapping.
# When a user selects a variant, these values act as the baseline config.
# Any explicitly-provided CLI argument overrides the preset.
_VARIANT_PRESETS = {
    "evodiagram": {
        "enable_refiner": True,
        "mode": "multiagent",
        "use_icons": True,
    },
    "evodiagram_wo_refiner": {
        "enable_refiner": False,
        "mode": "multiagent",
        "use_icons": True,
    },
    "evodiagram_wo_multiagent": {
        "enable_refiner": False,
        "mode": "oneshot",
        "use_icons": True,
    },
    "evodiagram_wo_icons": {
        "enable_refiner": True,
        "mode": "multiagent",
        "use_icons": False,
    },
}


def list_variant_presets() -> tuple[str, ...]:
    """Return the supported experiment variant names."""
    return tuple(sorted(_VARIANT_PRESETS))


def get_variant_preset(variant: str) -> dict:
    """Return the preset defaults for a given variant."""
    if variant not in _VARIANT_PRESETS:
        supported = ", ".join(list_variant_presets())
        raise ValueError(f"Unknown variant: {variant!r}. Use one of: {supported}.")
    return dict(_VARIANT_PRESETS[variant])


@dataclass
class AgenticSystemConfig:
    # ── Provider (pass-through from CLI) ─────────────────────────────────
    role: str = "generator"        # Role in models.yaml
    model_override: Optional[str] = None  # --model alias override

    # ── Generation strategy ──────────────────────────────────────────────
    mode: str = "multiagent"       # "multiagent" (Structure→Styling→Layout) or "oneshot" (single LLM call)
    save_intermediate: bool = True # False to disable saving intermediate JSON/PNG
    tag: Optional[str] = None      # Tag appended to output dir to avoid overwriting
    variant: str = "evodiagram"    # Experiment variant: evodiagram, evodiagram_wo_refiner, etc.

    # ── Tool toggles ────────────────────────────────────────────────────
    use_icons: bool = False  # add Material Design icons to diagram nodes
    canvas_library: str = "excalidraw"  # "excalidraw" or "tldraw"
    full_domain_knowledge: bool = True  # inject all stage rules into every agent

    # ── Refiner ──────────────────────────────────────────────────────────
    enable_refiner: bool = False
    refiner_iterations: int = 3

    # ── Verification ─────────────────────────────────────────────────────
    enable_verifier: bool = True
    verification_only: bool = False
    enable_critic: bool = True

    # ── User Memory ──────────────────────────────────────────────────────
    enable_user_memory: bool = False
    user_id: str = "default_user"
    session_id: Optional[str] = None
    memory_db_path: Optional[str] = None  # resolved from AppSettings in __post_init__

    # ── Design Memory ────────────────────────────────────────────────────
    # Evolved design knowledge (strategy / guideline / principle) retrieved at
    # generation time. On by default because it is part of the system under
    # evaluation: an experiment that silently generates without it is exactly
    # the regression this switch guards against. Turning it on cannot break a
    # run — every failure path degrades to "generate without design knowledge"
    # and is recorded on the workflow state.
    enable_design_memory: bool = True
    design_memory_db_path: Optional[str] = None  # resolved from AppSettings in __post_init__
    design_memory_embedding_model: Optional[str] = None  # None → settings.yaml
    design_memory_top_k: int = 5
    design_memory_score_threshold: float = 0.0

    # ── Learn-from-edit mode ─────────────────────────────────────────────
    learn_from_edit: bool = False
    task_json: Optional[str] = None
    model_manifest: Optional[str] = None
    model_image: Optional[str] = None
    user_manifest: Optional[str] = None
    user_image: Optional[str] = None

    def __post_init__(self):
        self.mode = normalize_generation_mode(self.mode)

        self.canvas_library = normalize_canvas_library(self.canvas_library)
        require_generation_capability(
            canvas_library=self.canvas_library,
            mode=self.mode,
        )

        if self.enable_refiner:
            require_refiner_capability(
                canvas_library=self.canvas_library,
                mode=self.mode,
            )

        # Only resolve implicit defaults here. Programmatic values passed to
        # AgenticSystemConfig must remain authoritative for reproducible runs.
        try:
            if self.memory_db_path is None:
                from evo_diagram.config.settings import AppSettings
                self.memory_db_path = AppSettings.get_default().user_preference_memory_path
        except Exception as exc:
            if self.enable_user_memory:
                raise RuntimeError(
                    "Could not resolve user preference memory path from settings. "
                    "Pass memory_db_path explicitly or fix settings.yaml before "
                    "enabling user memory."
                ) from exc
            logger.warning(
                "Could not resolve default user preference memory path; "
                "continuing with memory_db_path=None because user memory is disabled: %s",
                exc,
            )

        # Design memory deliberately does NOT mirror the user-memory branch
        # above: it never raises. Design knowledge is an enhancement, so an
        # unreadable settings file has to end in "generate without it" rather
        # than in a failed run. A None path leaves resolution to
        # DiagramDesignMemory, which applies the same settings default.
        try:
            if self.design_memory_db_path is None:
                from evo_diagram.config.settings import AppSettings
                self.design_memory_db_path = (
                    AppSettings.get_default().design_memory_vector_db_path
                )
        except Exception as exc:
            logger.warning(
                "Could not resolve default design memory vector store path; "
                "design memory will be skipped unless design_memory_db_path is "
                "passed explicitly: %s",
                exc,
            )
