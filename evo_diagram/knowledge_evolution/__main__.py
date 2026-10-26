import argparse
import logging
from pathlib import Path

from evo_diagram.utils.path_manager import DATASET_DIR

from .engine import DesignMemoryMode, DiagramKnowledgeEvolverEngine
from .config import KnowledgeEvolutionConfig


TEST_SPLIT_DIR = DATASET_DIR / "test"


def _reject_test_split(dataset_path: str, allow_test_split: bool) -> None:
    """Refuse to evolve knowledge on the evaluation split.

    Knowledge distilled from a sample is written into design memory and
    retrieved again at generation time, so running evolution over
    ``dataset/test`` puts test-set content into the generator that the same test
    set is then used to score. ``--dataset`` used to default to the test split,
    which made that leak the *default* behaviour.
    """
    if allow_test_split:
        return
    resolved = Path(dataset_path).expanduser().resolve()
    try:
        resolved.relative_to(TEST_SPLIT_DIR.resolve())
    except ValueError:
        return
    raise SystemExit(
        f"Refusing to run knowledge evolution on the test split ({resolved}). "
        "Distilled knowledge is persisted to design memory and retrieved during "
        "generation, so this leaks evaluation content into the system under "
        "evaluation. Use the training split, or pass --allow-test-split if you "
        "are deliberately running a diagnostic whose knowledge will be discarded."
    )


def main():
    parser = argparse.ArgumentParser(description="DiagramKnowledgeEvolver")
    parser.add_argument(
        "--dataset",
        type=str,
        required=True,
        help=(
            "Path to input dataset JSON. Required on purpose: evolved knowledge "
            "is persisted and reused at generation time, so the split must be "
            "chosen explicitly (e.g. dataset/train/data.json)."
        ),
    )
    parser.add_argument(
        "--allow-test-split",
        action="store_true",
        help=(
            "Permit --dataset to point inside dataset/test. Only for diagnostics "
            "whose resulting design memory will be discarded."
        ),
    )
    parser.add_argument("--output-dir", type=str, default="output/knowledge_evolution", help="Output directory")
    parser.add_argument("--max-iters", type=int, default=3, help="Max iterations per sample")
    parser.add_argument("--model-config", type=str, default=None,
                        help="Path to models.yaml (recommended)")
    parser.add_argument("--settings", type=str, default=None,
                        help="Path to settings.yaml (optional)")
    parser.add_argument("--generation-role", type=str, default=None,
                        help="Role from models.yaml used for diagram generation (default: generator)")
    parser.add_argument("--distillation-role", type=str, default=None,
                        help="Role from models.yaml used for strategy/guideline extraction (default: distiller)")
    parser.add_argument("--judge-role", type=str, default=None,
                        help="Role from models.yaml used for promotion, demotion, and merge judging (default: distiller)")
    parser.add_argument("--log-level", type=str, default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Logging verbosity (default: INFO)")
    parser.add_argument("--design-memory-mode", type=str,
                        choices=[mode.value for mode in DesignMemoryMode],
                        default=None,
                        help="Design memory integration mode (default: enabled; offline disables DB seed, retrieval, persistence, and embedding merge)")

    args = parser.parse_args()

    _reject_test_split(args.dataset, args.allow_test_split)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.model_config:
        from evo_diagram.config.model_loader import ModelConfig
        ModelConfig.init(args.model_config)

    if args.settings:
        from evo_diagram.config.settings import AppSettings
        AppSettings.init(args.settings)

    config_kwargs = {
        name: value
        for name, value in {
            "generation_role": args.generation_role,
            "distillation_role": args.distillation_role,
            "judge_role": args.judge_role,
        }.items()
        if value is not None
    }

    config = KnowledgeEvolutionConfig(
        **config_kwargs,
        output_dir=args.output_dir,
        max_iterations=args.max_iters,
    )

    engine = DiagramKnowledgeEvolverEngine(
        config,
        design_memory_mode=args.design_memory_mode,
    )
    engine.run(args.dataset)


if __name__ == "__main__":
    main()
