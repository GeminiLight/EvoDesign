#!/usr/bin/env python3
"""
Main entry point for Text2Diagram workflow CLI.

Usage:
    python -m evo_diagram.agentic_system.main --example 1
    python -m evo_diagram.agentic_system.main --start 1 --end 10
    python -m evo_diagram.agentic_system.main --all
"""
import os
import json
import argparse
import logging
import sys
import traceback
from pathlib import Path
from evo_diagram.utils.env_loader import ensure_env_loaded

ensure_env_loaded()

from evo_diagram.core.llm_factory import LLMFactory
from evo_diagram.core.experiment import get_experiment_id, get_evodiagram_output_dir
from evo_diagram.utils.path_manager import (
    DEFAULT_TEST_DATASET,
    EXAMPLES_DIR,
    safe_join_under,
    safe_path_segment,
)
from evo_diagram.agentic_system.config import (
    AgenticSystemConfig,
    get_variant_preset,
    list_variant_presets,
)
from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class VerificationQualityError(RuntimeError):
    """Raised when generation completes but the verifier quality gate fails."""


# ── CLI Parsing ─────────────────────────────────────────────────────────

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run Text2Diagram workflow on dataset examples"
    )
    parser.add_argument(
        "--example", type=int,
        help="Dataset index (starts from 1)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process every item in the dataset",
    )
    parser.add_argument(
        "--mode", choices=["multiagent", "oneshot"], default=argparse.SUPPRESS,
        help="Generation mode: 'multiagent' (Structure→Styling→Layout) or 'oneshot' (single LLM call). "
             "Defaults are set by --variant preset.",
    )
    parser.add_argument(
        "--no-save-intermediate", action="store_true",
        help="Disable saving intermediate results"
    )
    parser.add_argument(
        "--enable-refiner", action="store_true", default=argparse.SUPPRESS,
        help="Enable VLM-based diagram refinement after rendering. "
             "Defaults are set by --variant preset."
    )
    parser.add_argument(
        "--refiner-iterations", type=int, default=3,
        help="Maximum refinement iterations (default: 3)"
    )

    # Verification
    parser.add_argument("--enable-verifier", action="store_true", default=True)
    parser.add_argument("--no-verifier", dest="enable_verifier", action="store_false")
    parser.add_argument("--verification-only", action="store_true", default=False)
    critic_group = parser.add_mutually_exclusive_group()
    critic_group.add_argument("--critic", dest="enable_critic", action="store_true", default=True)
    critic_group.add_argument("--no-critic", dest="enable_critic", action="store_false")

    parser.add_argument("--model", type=str, help="Model alias declared in configs/models.yaml")

    # Tool toggles
    parser.add_argument("--use-icons", action="store_true", default=argparse.SUPPRESS,
                        help="Add Material Design icons to diagram nodes. "
                             "Defaults are set by --variant preset.")
    parser.add_argument("--no-icons", dest="use_icons", action="store_false",
                        default=argparse.SUPPRESS,
                        help="Disable icons, overriding the variant preset.")
    parser.add_argument(
        "--canvas-library",
        choices=["excalidraw", "tldraw"],
        default=argparse.SUPPRESS,
        help="Canvas/rendering backend. Defaults to settings.yaml.",
    )

    # Provider
    parser.add_argument("--model-config", type=str, default=None)
    parser.add_argument("--settings", type=str, default=None, help="Path to settings.yaml")
    parser.add_argument("--role", type=str, default="generator")
    parser.add_argument("--dataset-path", type=str)
    parser.add_argument("--start", type=int)
    parser.add_argument("--end", type=int)
    parser.add_argument("--ids", type=str, nargs="+")
    parser.add_argument("--tag", type=str, default=None,
                        help="Tag appended to output dir (e.g. 'v2' → .../id_v2)")
    parser.add_argument("--variant", type=str, choices=list_variant_presets(), default=None,
                        help="Experiment variant preset: evodiagram, evodiagram_wo_refiner, etc. "
                             "When omitted, runtime defaults come from settings.yaml and output paths "
                             "still use the evodiagram variant name.")

    # User Memory
    parser.add_argument("--learn-from-edit", action="store_true", default=False)
    parser.add_argument("--enable-user-memory", action="store_true", default=False)
    parser.add_argument("--user-id", type=str, default="default_user")
    parser.add_argument("--session-id", type=str, default=None)
    parser.add_argument("--memory-db-path", type=str, default=None,
                        help="User preference DB path (default: from settings.yaml)")

    # Learn-from-edit mode
    parser.add_argument("--task-json", type=str)
    parser.add_argument("--model-manifest", type=str)
    parser.add_argument("--model-image", type=str)
    parser.add_argument("--user-manifest", type=str)
    parser.add_argument("--user-image", type=str)

    return parser.parse_args()


def build_config(args) -> AgenticSystemConfig:
    """Build AgenticSystemConfig from parsed CLI arguments."""
    if args.model_config:
        from evo_diagram.config.model_loader import ModelConfig
        ModelConfig.init(args.model_config)

    if args.settings:
        from evo_diagram.config.settings import AppSettings
        AppSettings.init(args.settings)

    # Resolution order:
    #   CLI flags > explicitly selected variant preset > settings.yaml defaults.
    # When --variant is omitted, keep "evodiagram" only as the output-path
    # variant name; do not let its preset shadow settings.yaml.
    variant = args.variant or "evodiagram"
    preset = get_variant_preset(args.variant) if args.variant else {}
    from evo_diagram.config.settings import AppSettings

    settings = AppSettings.get_default()
    settings_mode = settings.generation_mode
    settings_canvas = settings.canvas_library
    settings_enable_refiner = settings.generation_enable_refiner
    settings_use_icons = settings.generation_use_icons
    settings_full_domain_knowledge = settings.full_domain_knowledge

    def resolve_arg(name: str, setting_default):
        if hasattr(args, name):
            return getattr(args, name)
        return preset.get(name, setting_default)

    return AgenticSystemConfig(
        role=args.role,
        model_override=args.model,
        mode=resolve_arg("mode", settings_mode),
        save_intermediate=not args.no_save_intermediate,
        tag=args.tag,
        variant=variant,
        enable_refiner=resolve_arg("enable_refiner", settings_enable_refiner),
        refiner_iterations=args.refiner_iterations,
        enable_verifier=args.enable_verifier,
        verification_only=args.verification_only,
        enable_critic=args.enable_critic,
        use_icons=resolve_arg("use_icons", settings_use_icons),
        canvas_library=resolve_arg("canvas_library", settings_canvas),
        full_domain_knowledge=settings_full_domain_knowledge,
        enable_user_memory=args.enable_user_memory,
        user_id=args.user_id,
        session_id=args.session_id,
        memory_db_path=args.memory_db_path,
        learn_from_edit=args.learn_from_edit,
        task_json=args.task_json,
        model_manifest=args.model_manifest,
        model_image=args.model_image,
        user_manifest=args.user_manifest,
        user_image=args.user_image,
    )


# ── Validation ──────────────────────────────────────────────────────────

def validate_config(config: AgenticSystemConfig, args):
    """Validate config + CLI args combination."""
    if config.learn_from_edit:
        required = ["task_json", "model_manifest", "model_image", "user_manifest", "user_image"]
        missing = [f"--{f.replace('_', '-')}" for f in required if not getattr(config, f)]
        if missing:
            raise ValueError(f"--learn-from-edit requires: {', '.join(missing)}")
        return

    mode_count = sum([
        args.example is not None,
        args.start is not None or args.end is not None,
        args.ids is not None,
        getattr(args, "all", False),
    ])
    if mode_count == 0:
        raise ValueError("Must specify one of: --example, --start/--end, --ids, or --all")
    if mode_count > 1:
        raise ValueError("Cannot combine --example, --start/--end, --ids, and --all.")
    if args.start is not None or args.end is not None:
        if args.start is None or args.end is None:
            raise ValueError("Both --start and --end must be specified together")
        if args.start < 1 or args.end < 1:
            raise ValueError("--start and --end must be >= 1")
        if args.start > args.end:
            raise ValueError("--start must be <= --end")


# ── Dataset ─────────────────────────────────────────────────────────────

def load_dataset(dataset_path: str | None):
    """Load dataset from path (default: test dataset)."""
    path = Path(dataset_path).expanduser() if dataset_path else DEFAULT_TEST_DATASET
    with open(path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    return dataset, str(path)


def determine_items(dataset, args):
    """Determine which examples to process based on CLI args."""
    items = []

    if args.ids is not None:
        id_to_item = {item.get("id", ""): (i + 1, item) for i, item in enumerate(dataset)}
        not_found = []
        for data_id in args.ids:
            if data_id in id_to_item:
                items.append(id_to_item[data_id])
            else:
                not_found.append(data_id)
        if not_found:
            raise ValueError(f"Data IDs not found in dataset: {not_found}")

    elif args.example is not None:
        index = args.example - 1
        if index < 0 or index >= len(dataset):
            raise ValueError(f"Invalid example index: {args.example}. Valid range: 1-{len(dataset)}")
        items = [(args.example, dataset[index])]

    elif getattr(args, "all", False):
        items = [(num, item) for num, item in enumerate(dataset, start=1)]

    else:
        if args.end > len(dataset):
            raise ValueError(f"--end ({args.end}) exceeds dataset size ({len(dataset)})")
        items = [(num, dataset[num - 1]) for num in range(args.start, args.end + 1)]

    return items


# ── Model ───────────────────────────────────────────────────────────────

def initialize_model(config: AgenticSystemConfig):
    """Initialize LLM model from models.yaml or environment variables.

    Returns (model, model_name) tuple.
    """
    from evo_diagram.config.model_loader import ModelConfig

    overrides = {"max_tokens": 16384, "max_retries": 6}

    model_config = ModelConfig.get_default()
    if config.model_override:
        if not model_config.has_model(config.model_override):
            available = ", ".join(model_config.list_models())
            raise ValueError(
                f"Unknown model alias {config.model_override!r}. "
                "Declare it under models in the active models.yaml or use one "
                f"of: {available}."
            )
        params = model_config.get_named_model_config(config.model_override, **overrides)
        model = LLMFactory.create(**params)
        resolved_name = config.model_override
    else:
        model = LLMFactory.create_for_role(config.role, **overrides)

        # Resolve actual model name from provider config
        try:
            roles = model_config.list_roles()
            resolved_name = roles.get(config.role, "unknown")
        except Exception:
            resolved_name = "unknown"

    logger.info(f"Model initialized (role={config.role}, model={resolved_name})")
    return model, resolved_name


def initialize_router_model():
    """Initialize the required Router classifier model."""
    from evo_diagram.config.model_loader import ModelConfig

    model_config = ModelConfig.get_default()
    roles = model_config.list_roles()
    if "router" not in roles:
        raise RuntimeError(
            "Router role is required in model settings. Add roles.router to "
            "the active settings.yaml instead of relying on the old fast-role fallback."
        )

    try:
        router_model = LLMFactory.create_for_role("router")
    except Exception as exc:
        raise RuntimeError(
            "Router role is configured but the router model could not be "
            "initialized. Fix the router model/provider config."
        ) from exc
    logger.info("Router model initialized (router role)")
    return router_model


def _explicit_diagram_type(item) -> str | None:
    """Return a meaningful dataset diagram_type, or None when routing is needed."""
    value = item.get("diagram_type") if isinstance(item, dict) else None
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    if value.lower() in {"unknown", "general", "auto", "automatic"}:
        return None
    return value


def _items_need_router(items) -> bool:
    return any(_explicit_diagram_type(item) is None for _example_num, item in items)


# ── Output ──────────────────────────────────────────────────────────────

def _dataset_path_is_eval(dataset_path: str) -> bool:
    """Return whether a dataset path denotes the test/eval split.

    Use path segments instead of substring matching so names such as
    ``contest_data.json`` or ``pretest_train.json`` do not accidentally route
    outputs into the experiment tree.
    """
    path = Path(dataset_path)
    markers = {"test", "eval"}
    parts = {part.lower() for part in path.parts}
    return bool(parts & markers) or path.stem.lower() in markers


def get_output_dir(
    item_id: str,
    dataset_path: str,
    model_name: str = "default",
    tag: str = None,
    variant: str = "evodiagram",
):
    """Determine output directory for an item.

    Eval mode writes to experiments/{exp_id}/outputs/evodiagram/{variant}/{model}/{item_id}/
    """
    is_eval = _dataset_path_is_eval(dataset_path)
    safe_item_id = safe_path_segment(item_id, field_name="dataset item id")
    if is_eval:
        model_id = safe_path_segment(
            model_name.replace("/", "_").replace("\\", "_").replace(":", "_"),
            field_name="model name",
        )
        if tag:
            safe_tag = safe_path_segment(tag, field_name="output tag")
            dir_name = f"{safe_item_id}_{safe_tag}"
        else:
            dir_name = safe_item_id
        exp_id = get_experiment_id()
        output_root = get_evodiagram_output_dir(variant, model_id, exp_id)
        output_dir = safe_join_under(output_root, dir_name)
    else:
        output_dir = safe_join_under(EXAMPLES_DIR, safe_item_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    return str(output_dir)


def get_output_failure_dir(
    example_num: int,
    dataset_path: str,
    model_name: str = "default",
    variant: str = "evodiagram",
) -> str:
    """Return a deterministic safe directory for failures before item dir resolution."""
    fallback_id = f"example_{example_num}_invalid_output_path"
    try:
        return get_output_dir(
            fallback_id,
            dataset_path,
            model_name=model_name,
            tag=None,
            variant=variant,
        )
    except Exception:  # noqa: BLE001
        output_dir = safe_join_under(EXAMPLES_DIR, fallback_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        return str(output_dir)


# ── Processing ──────────────────────────────────────────────────────────

def _write_failure_artifact(output_dir, *, example_num, item_id, exc, extra=None):
    """Persist a per-item failure record for batch debugging."""
    try:
        os.makedirs(output_dir, exist_ok=True)
        failure_path = os.path.join(output_dir, "failure.json")
        payload = {
            "success": False,
            "example_num": example_num,
            "item_id": item_id,
            "output_dir": output_dir,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exception(
                type(exc),
                exc,
                exc.__traceback__,
            ),
        }
        if extra:
            payload.update(extra)
        with open(failure_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return failure_path
    except Exception as write_exc:  # noqa: BLE001
        logger.warning(
            "Could not write failure artifact for item %s: %s",
            item_id,
            write_exc,
        )
        return None


def _state_result_metadata(state):
    return {
        "image_path": getattr(state, "final_png_path", None),
        "manifest_path": getattr(state, "final_manifest_path", None),
        "verification_status": getattr(state, "verification_status", None),
        "verification_quality_passed": getattr(
            state,
            "verification_quality_passed",
            None,
        ),
        "verification_cli_exit_code": getattr(state, "verification_cli_exit_code", None),
        "verification_objective_summary": getattr(
            state,
            "verification_objective_summary",
            None,
        ),
        "verification_errors": getattr(state, "verification_errors", None),
        "verification_report_path": getattr(state, "verification_report_path", None),
        "degraded": bool(getattr(state, "refiner_degraded", False)),
        "refiner_status": getattr(state, "refiner_status", None),
    }


def _verification_failure_message(state):
    quality_passed = getattr(state, "verification_quality_passed", None)
    status = getattr(state, "verification_status", None)
    cli_exit_code = getattr(state, "verification_cli_exit_code", None)
    errors = getattr(state, "verification_errors", None)

    if quality_passed is False:
        return "verification did not pass" + (f" (status={status})" if status else "")
    if status in {"failed", "error"}:
        return f"verification stage failed (status={status})"
    if (
        isinstance(cli_exit_code, int)
        and not isinstance(cli_exit_code, bool)
        and cli_exit_code != 0
    ):
        return f"verification command failed (exit_code={cli_exit_code})"
    if (
        quality_passed is None
        and status == "reported_with_warnings"
        and cli_exit_code == 0
    ):
        return None
    if errors and quality_passed is not True:
        return "verification reported errors"
    return None


def process_example(example_num, item, model, config: AgenticSystemConfig, output_dir, router_model=None):
    """Process a single example through the workflow."""
    item_id = item.get("id", f"example_{example_num}")
    text_content = item.get("content", "")
    user_query = item.get("query", "")
    diagram_type = _explicit_diagram_type(item)
    content_area = item.get("content_area", "unknown")

    logger.info("=" * 80)
    logger.info("Processing example %d (id: %s)", example_num, item_id)
    logger.info("Diagram Type: %s | Content Area: %s", diagram_type or "auto", content_area)
    if config.enable_user_memory:
        logger.info("User Memory: enabled (user_id: %s)", config.user_id)
    logger.info("Content: %s%s", text_content[:200], "..." if len(text_content) > 200 else "")
    logger.info("Query: %s", user_query)
    logger.info("=" * 80)

    save_dir = output_dir if config.save_intermediate else None

    try:
        workflow = Text2DiagramWorkflow(model, config=config, router_model=router_model)
        state = workflow.run(
            text_content, user_query,
            save_dir=save_dir,
            final_dir=output_dir,
            diagram_type=diagram_type,
            content_area=content_area,
        )

        logger.info("Saved rendered diagram: %s", state.final_png_path)
        metadata = _state_result_metadata(state)
        verification_error = _verification_failure_message(state)
        if verification_error:
            failure_path = _write_failure_artifact(
                output_dir,
                example_num=example_num,
                item_id=item_id,
                exc=VerificationQualityError(verification_error),
                extra=metadata,
            )
            result = {
                "example_num": example_num,
                "item_id": item_id,
                "output_dir": output_dir,
                **metadata,
                "error": verification_error,
                "error_type": "VerificationQualityError",
                "success": False,
            }
            if failure_path:
                result["failure_path"] = failure_path
            return result

        return {
            "example_num": example_num,
            "item_id": item_id,
            "output_dir": output_dir,
            **metadata,
            "success": True,
        }

    except Exception as e:
        logger.error("Error processing example %d (id: %s): %s", example_num, item_id, e, exc_info=True)
        failure_path = _write_failure_artifact(
            output_dir,
            example_num=example_num,
            item_id=item_id,
            exc=e,
        )
        result = {
            "example_num": example_num,
            "item_id": item_id,
            "error": str(e),
            "error_type": type(e).__name__,
            "success": False,
        }
        if failure_path:
            result["failure_path"] = failure_path
        return result


def learn_from_user_edit(config: AgenticSystemConfig):
    """Learn user preferences from manual diagram edits."""
    from datetime import datetime

    session_id = config.session_id or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    try:
        from evo_diagram.user_memory.main import UserPreferenceMemorySystem

        system = UserPreferenceMemorySystem(
            user_id=config.user_id,
            memory_db_path=config.memory_db_path,
        )
    except ImportError as e:
        raise ImportError(f"Failed to import user_preference_memory: {e}")

    with open(config.task_json) as f:
        task_json = json.load(f)

    logger.info("User ID: %s | Session: %s", config.user_id, session_id)
    logger.info("Task: %s", config.task_json)

    result = system.learn_from_edit(
        task_json=task_json,
        model_manifest_path=config.model_manifest,
        model_image_path=config.model_image,
        user_manifest_path=config.user_manifest,
        user_image_path=config.user_image,
        session_id=session_id,
    )

    prefs = result["preferences"]
    logger.info("Extracted: %d | Filtered: %d", prefs['extracted'], prefs['filtered'])
    return result


# ── Main ────────────────────────────────────────────────────────────────

def main() -> int:
    args = parse_arguments()
    config = build_config(args)
    validate_config(config, args)

    if config.learn_from_edit:
        learn_from_user_edit(config)
        return 0

    dataset, dataset_path = load_dataset(args.dataset_path)
    items = determine_items(dataset, args)

    logger.info("Dataset: %s (%d items)", dataset_path, len(dataset))
    if args.ids:
        logger.info("Processing IDs: %s", args.ids)
    else:
        logger.info("Processing examples: %s", [idx for idx, _ in items])

    model, model_name = initialize_model(config)

    router_model = None
    if _items_need_router(items):
        # Create a cheap model for samples that need Router classification.
        router_model = initialize_router_model()
    else:
        logger.info("Skipping Router model initialization; all selected items declare diagram_type.")

    success_list, failure_list = [], []
    for example_num, item in items:
        item_id = item.get("id", f"example_{example_num}")
        try:
            output_dir = get_output_dir(
                item_id,
                dataset_path,
                model_name,
                config.tag,
                config.variant,
            )
        except ValueError as e:
            output_dir = get_output_failure_dir(
                example_num,
                dataset_path,
                model_name=model_name,
                variant=config.variant,
            )
            failure_path = _write_failure_artifact(
                output_dir,
                example_num=example_num,
                item_id=item_id,
                exc=e,
            )
            result = {
                "example_num": example_num,
                "item_id": item_id,
                "output_dir": output_dir,
                "error": str(e),
                "error_type": type(e).__name__,
                "success": False,
            }
            if failure_path:
                result["failure_path"] = failure_path
            failure_list.append(result)
            logger.warning("Continuing to next example...")
            continue
        item_router_model = router_model if _explicit_diagram_type(item) is None else None
        result = process_example(
            example_num,
            item,
            model,
            config,
            output_dir,
            router_model=item_router_model,
        )

        if result["success"]:
            success_list.append(result)
        else:
            failure_list.append(result)
            logger.warning("Continuing to next example...")

    if len(items) > 1 or failure_list:
        logger.info("=" * 80)
        logger.info("Summary: %d succeeded, %d failed", len(success_list), len(failure_list))
        for r in failure_list:
            logger.error("  Failed: example %d (id: %s): %s", r['example_num'], r['item_id'], r['error'][:80])
        logger.info("=" * 80)

    return 1 if failure_list else 0


if __name__ == "__main__":
    sys.exit(main())
