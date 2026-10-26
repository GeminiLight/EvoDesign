"""
Path Resolver for Evaluation System

Resolves image paths and output paths based on method name.

Supports both the new experiments/ layout and the legacy results/ layout:

    experiments/{exp_id}/
        outputs/
            baseline/{algo}/{model}/{sample_id}/render.png
            evodiagram/{variant}/{model}/{sample_id}/rendered_diagram.png
        scores/
            baseline/{algo}/{model}/{sample_id}.json
            evodiagram/{variant}/{model}/{sample_id}.json

    results/  (legacy, read-only fallback)
"""

from pathlib import Path
from typing import Tuple, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from evo_diagram.core.experiment import get_experiment_id
from evo_diagram.utils.path_manager import safe_join_under, safe_path_segment


class AmbiguousSubmodelError(ValueError):
    """Raised when generated outputs exist under several sub-model directories.

    Auto-picking one of them silently mixes backbones inside a single score
    table, so the caller must name the sub-model explicitly.
    """


def _validate_method(method: str) -> str:
    """Validate the method string before parsing slash-delimited formats."""
    if not isinstance(method, str):
        raise ValueError("method must be a string.")
    if not method:
        raise ValueError("method must not be empty.")
    if method != method.strip():
        raise ValueError("method must not contain leading or trailing whitespace.")
    if "\\" in method or "\x00" in method:
        raise ValueError(f"method must not contain unsafe path separators: {method!r}.")
    return method


def _safe_optional_segment(value: Optional[str], *, field_name: str) -> Optional[str]:
    if value is None:
        return None
    return safe_path_segment(value, field_name=field_name)


def _join_evo_image_path(results_dir: Path, data_id: str, submodel: Optional[str]) -> Path:
    segments = []
    if submodel is not None:
        segments.append(submodel)
    segments.extend([data_id, "rendered_diagram.png"])
    return safe_join_under(results_dir, *segments)



def _find_evo_image(
    results_dir: Path,
    data_id: str,
    image_name: str = "rendered_diagram.png",
    submodel: Optional[str] = None,
) -> Optional[Path]:
    """Find generated image under an evodiagram results directory.

    Resolution order (first match wins):
    1. If ``submodel`` is given:
       ``results_dir / submodel / data_id / image_name``
    2. Legacy flat layout (backward compatibility):
       ``results_dir / data_id / image_name``

    Sub-model directories are never auto-detected. When no explicit sub-model is
    given but one or more sub-model directories hold the sample, this raises
    :class:`AmbiguousSubmodelError` instead of guessing: guessing lets a single
    aggregated row mix outputs from different backbones sample by sample.

    Returns ``None`` when nothing is found.
    """
    safe_data_id = safe_path_segment(data_id, field_name="data_id")
    safe_image_name = safe_path_segment(image_name, field_name="image name")
    safe_submodel = _safe_optional_segment(submodel, field_name="model segment")

    # 1. Explicit submodel path
    if safe_submodel is not None:
        candidate = safe_join_under(results_dir, safe_submodel, safe_data_id, safe_image_name)
        return candidate if candidate.exists() else None

    # 2. Legacy flat layout
    candidate = safe_join_under(results_dir, safe_data_id, safe_image_name)
    if candidate.exists():
        return candidate

    # 3. Refuse to guess a sub-model directory.
    if results_dir.exists() and results_dir.is_dir():
        candidates = [
            subdir.name
            for subdir in sorted(results_dir.iterdir())
            if subdir.is_dir()
            and not subdir.name.startswith(".")
            and safe_join_under(subdir, safe_data_id, safe_image_name).exists()
        ]
        if candidates:
            raise AmbiguousSubmodelError(
                f"Generated output for '{safe_data_id}' lives under sub-model "
                f"director{'ies' if len(candidates) > 1 else 'y'} {candidates} of "
                f"{results_dir}, but no sub-model was specified. Auto-detection is "
                f"disabled because it silently mixes backbones within one score "
                f"table. Specify the sub-model explicitly, e.g. "
                f"--method '<variant>/{candidates[0]}'."
            )

    return None


def _reference_image_path(data_id: str) -> Path:
    """Return the ground-truth reference image path for *data_id*."""
    safe_data_id = safe_path_segment(data_id, field_name="data_id")
    return safe_join_under(
        PROJECT_ROOT,
        "dataset",
        "images",
        "diagrams",
        f"{safe_data_id}.jpg",
    )


def _get_exp_id(exp_id: Optional[str] = None) -> str:
    """Resolve experiment ID from argument, env var, config, or default date."""
    return exp_id or get_experiment_id()


def parse_method_paths(
    method: str, data_id: str, exp_id: Optional[str] = None
) -> Tuple[Path, Path, Path]:
    """Parse method name and return image path, output dir, and reference image path.

    Supports both the new ``experiments/{exp_id}/`` layout and the legacy
    ``results/`` layout.  When resolving *read* paths, the resolver first
    looks under ``experiments/``; if the file does not exist it falls back
    to ``results/``.  *Write* paths (evaluation scores) always use
    ``experiments/{exp_id}/scores/``.

    Args:
        method: Method name, e.g.:
            - "evodiagram"
            - "evodiagram/gpt-5.2"
            - "evodiagram_wo_refiner"
            - "evodiagram_wo_icon/gpt-5.2"
            - "baselines/code_mermaid/gemini-3-pro" (slash format)
            - "baselines/mermaid/gemini-3-pro" (alias for code_mermaid)
            - "baselines_code_mermaid_gemini-3-pro" (underscore format)
        data_id: Data item ID
        exp_id: Optional experiment ID override.  When omitted, resolves
            via ``EVO_EXPERIMENT_ID`` env var → ``settings.yaml`` → date.

    Returns:
        Tuple of (generated_image_path, output_dir, reference_image_path)
    """
    method = _validate_method(method)
    safe_eid = safe_path_segment(_get_exp_id(exp_id), field_name="experiment id")
    safe_data_id = safe_path_segment(data_id, field_name="data_id")

    # Reference image is always the same
    reference_image = _reference_image_path(safe_data_id)

    # ── Helper to pick between experiments/ and legacy results/ for READs ──
    def _evo_read(*exp_segments: str) -> Path:
        """Return the experiments path as primary. Legacy is used only as a fallback
        when the caller explicitly looks for existing files there."""
        return safe_join_under(
            PROJECT_ROOT,
            "experiments",
            safe_eid,
            "outputs",
            *exp_segments,
        )

    def _evo_read_with_fallback(
        exp_segments: tuple[str, ...],
        legacy_segments: tuple[str, ...],
        data_id: str,
        submodel: Optional[str] = None,
    ) -> Optional[Path]:
        """Find an evodiagram image under experiments/ first, then legacy results/."""
        exp_dir = _evo_read(*exp_segments)
        img = _find_evo_image(exp_dir, data_id, submodel=submodel)
        if img is not None:
            return img
        legacy_dir = safe_join_under(PROJECT_ROOT, "results", *legacy_segments)
        return _find_evo_image(legacy_dir, data_id, submodel=submodel)

    def _baseline_read(baseline_type: str, model_name: str) -> Path:
        """Return generated image path, preferring experiments over legacy."""
        exp_base = safe_join_under(
            PROJECT_ROOT,
            "experiments",
            safe_eid,
            "outputs",
            "baseline",
            baseline_type,
            model_name,
        )
        for name in ("render.png", "image.png"):
            exp_path = safe_join_under(exp_base, safe_data_id, name)
            if exp_path.exists():
                return exp_path
        exp_flat = safe_join_under(exp_base, f"{safe_data_id}.png")
        if exp_flat.exists():
            return exp_flat

        legacy_base = safe_join_under(
            PROJECT_ROOT,
            "results",
            "baselines",
            baseline_type,
            model_name,
        )
        for name in ("render.png", "image.png"):
            legacy_path = safe_join_under(legacy_base, safe_data_id, name)
            if legacy_path.exists():
                return legacy_path
        legacy_flat = safe_join_under(legacy_base, f"{safe_data_id}.png")
        if legacy_flat.exists():
            return legacy_flat
        # Special-case diagramagent legacy location
        if baseline_type == "diagramagent":
            special_base = safe_join_under(
                PROJECT_ROOT,
                "baselines",
                "diagramagent",
                "results",
                "baselines",
                "diagramagent",
                model_name,
            )
            for name in ("render.png", "image.png"):
                special = safe_join_under(special_base, safe_data_id, name)
                if special.exists():
                    return special
            special_flat = safe_join_under(special_base, f"{safe_data_id}.png")
            if special_flat.exists():
                return special_flat
        return safe_join_under(exp_base, safe_data_id, "render.png")

    def _evo_score_dir(variant: str, submodel: Optional[str] = None) -> Path:
        """Evaluation score output dir under experiments/{eid}/scores/."""
        segments = [variant]
        if submodel is not None:
            segments.append(submodel)
        segments.append(safe_data_id)
        return safe_join_under(
            PROJECT_ROOT,
            "experiments",
            safe_eid,
            "scores",
            "evodiagram",
            *segments,
        )

    def _baseline_score_dir(baseline_type: str, model_name: str) -> Path:
        """Evaluation score output dir under experiments/{eid}/scores/."""
        return safe_join_under(
            PROJECT_ROOT,
            "experiments",
            safe_eid,
            "scores",
            "baseline",
            baseline_type,
            model_name,
            safe_data_id,
        )

    # ------------------------------------------------------------------
    # EvoDiagram variants
    # ------------------------------------------------------------------
    if method == "evodiagram" or method.startswith("evodiagram/"):
        parts = method.split("/", 1)
        submodel = (
            safe_path_segment(parts[1], field_name="model segment")
            if len(parts) == 2
            else None
        )

        generated_image = _evo_read_with_fallback(
            ("evodiagram", "evodiagram"),
            ("evodiagram",),
            safe_data_id,
            submodel=submodel,
        )

        if generated_image is None:
            exp_dir = _evo_read("evodiagram", "evodiagram")
            generated_image = _join_evo_image_path(exp_dir, safe_data_id, submodel)

        output_dir = _evo_score_dir("evodiagram", submodel)

    elif method == "evodiagram_wo_refiner" or method.startswith("evodiagram_wo_refiner/"):
        parts = method.split("/", 1)
        submodel = (
            safe_path_segment(parts[1], field_name="model segment")
            if len(parts) == 2
            else None
        )

        generated_image = _evo_read_with_fallback(
            ("evodiagram", "evodiagram_wo_refiner"),
            ("evodiagram_wo_refiner",),
            safe_data_id,
            submodel=submodel,
        )

        if generated_image is None:
            exp_dir = _evo_read("evodiagram", "evodiagram_wo_refiner")
            generated_image = _join_evo_image_path(exp_dir, safe_data_id, submodel)

        output_dir = _evo_score_dir("evodiagram_wo_refiner", submodel)

    elif method.startswith("evodiagram_") or method.startswith("evodiagram-"):
        parts = method.split("/", 1)
        variant = safe_path_segment(parts[0], field_name="variant segment")
        submodel = (
            safe_path_segment(parts[1], field_name="model segment")
            if len(parts) == 2
            else None
        )

        generated_image = _evo_read_with_fallback(
            ("evodiagram", variant),
            (variant,),
            safe_data_id,
            submodel=submodel,
        )

        if generated_image is None:
            exp_dir = _evo_read("evodiagram", variant)
            generated_image = _join_evo_image_path(exp_dir, safe_data_id, submodel)

        output_dir = _evo_score_dir(variant, submodel)

    # ------------------------------------------------------------------
    # Baselines
    # ------------------------------------------------------------------
    else:
        # Parse baselines format: supports both slash and underscore formats
        if "/" in method:
            parts = method.split("/", 2)
            if parts[0] != "baselines" or len(parts) != 3:
                raise ValueError(
                    f"Invalid method format: {method}. Expected 'evodiagram', "
                    f"'evodiagram_wo_refiner', 'evodiagram/<submodel>', or "
                    f"'baselines/<type>/<model>'"
                )
            baseline_type = safe_path_segment(parts[1], field_name="baseline segment")
            model_name = safe_path_segment(parts[2], field_name="model segment")
        else:
            parts = method.split("_", 2)
            if parts[0] != "baselines" or len(parts) != 3:
                raise ValueError(
                    f"Invalid method format: {method}. Expected 'evodiagram', "
                    f"'evodiagram_wo_refiner', or 'baselines_<type>_<model>'"
                )
            baseline_type = safe_path_segment(parts[1], field_name="baseline segment")
            model_name = safe_path_segment(parts[2], field_name="model segment")

        if baseline_type == "mermaid":
            baseline_type = "code_mermaid"

        generated_image = _baseline_read(baseline_type, model_name)
        output_dir = _baseline_score_dir(baseline_type, model_name)

    return generated_image, output_dir, reference_image


def get_generated_image_path(method: str, data_id: str, exp_id: Optional[str] = None) -> Path:
    """Get generated image path for a method and data ID."""
    image_path, _, _ = parse_method_paths(method, data_id, exp_id=exp_id)
    return image_path


def get_output_dir(method: str, data_id: str, exp_id: Optional[str] = None) -> Path:
    """Get output directory for a method and data ID."""
    _, output_dir, _ = parse_method_paths(method, data_id, exp_id=exp_id)
    return output_dir


def get_reference_image_path(data_id: str) -> Path:
    """Get reference image path for a data ID.

    Resolved directly instead of through ``parse_method_paths("evodiagram", ...)``
    so that looking up a reference image never depends on (or fails because of)
    evodiagram generated-output resolution while evaluating another method.
    """
    return _reference_image_path(data_id)
