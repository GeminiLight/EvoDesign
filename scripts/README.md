# EvoDesign scripts

Start with the [main quick start](../README.md#run-locally). Dataset files are released separately; use the authored `examples/diagrams/quickstart.json` for a small software smoke run.

| Script | Purpose |
| --- | --- |
| `setup_local.py` | Generate local `.env` files without overwriting existing settings |
| `start_service.sh` / `stop_service.sh` | Start/stop the local API, renderer and workspace |
| `check_quality.sh all` | Offline tests, lint, type checks and builds |
| `design_memory.py` | Validate, export and additively import personal DNA rules |
| `run_evodiagram.sh` | Generate with a model alias from `configs/models.yaml` |
| `run_baselines.sh` | Run comparison methods with explicit provider model names |
| `run_evaluation.sh` | Score explicitly selected generated method/model directories |
| `run_pipeline.sh` | Orchestrate generation and evaluation; `GENERATOR_MODELS` and `BASELINE_MODELS` distinguish YAML aliases from raw provider names |
| `research/` | Research round orchestration, aggregation and regression utilities |

Activate `.venv` before using shell wrappers. Generation uses the alias `configured-model` by default. Baselines require `MODELS` (or exported `LLM_MODEL_NAME`). Evaluation requires `METHODS`; it does not guess which previous results belong to your study. Keep an independent judge configured for research comparisons.

```sh
DATASET=examples/diagrams/quickstart.json START=1 END=1 ./scripts/run_evodiagram.sh
# Replace provider-model with your actual model identifier:
MODELS=provider-model DATASET=your-inputs.json START=1 END=1 ./scripts/run_baselines.sh
METHODS=evodiagram/configured-model,baselines/code_mermaid/provider-model ./scripts/run_evaluation.sh
```

Method names and decoding parameters must match the actual outputs. `BASELINE_TEMPERATURE` defaults to 1 to match the public generator setting; update both together if your provider needs another value. The default baseline list is `mermaid,direct_llm`. `ALGORITHMS=tlkz` needs a local LaTeX installation; `ALGORITHMS=pixel` needs a suitable image model and its provider credentials. Other upstream baseline adapters have their own documented requirements.

For ablations, `ABLATION=wo_refiner`, `wo_multiagent`, `wo_icons` and `custom` select named presets. Use explicit sample ranges for pilot runs before spending model credits on a batch. See [reproducibility](../docs/reproducibility.md) and [memory portability](../docs/design-memory.md).
