#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# Ensure package-mode imports work when launched from any directory.
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Baseline generation script.
#
# Usage:
#   ./scripts/run_baselines.sh
#
# Environment variables:
#   DATASET          Dataset JSON path (default: dataset/test/data.json)
#   MODELS           Comma-separated model list
#                    (required, or exported LLM_MODEL_NAME)
#   START, END       Sample range pair (1-based inclusive, optional; default: all)
#   MAX_CONCURRENT   Concurrency for programmatic baselines (default: 1)
#   ALGORITHMS       Comma-separated algorithm list
#                    (default: mermaid,direct_llm)
#                    Available: mermaid, tlkz, direct_llm, pixel, diagramagent, scisketch
#   ALLOW_UNSUPPORTED_RANGE
#                    Set to 1 to allow range-unsupported baselines to run the full dataset.
#   BASELINE_TEMPERATURE
#                    Decoding temperature for the LLM baselines (default: 1, matching
#                    the EvoDiagram generator). Pinned here because a repository .env
#                    LLM_TEMPERATURE / TEMPERATURE would otherwise win and leave the
#                    two sides decoding at different temperatures.

DATASET="${DATASET:-dataset/test/data.json}"
# Raw provider model names; pass MODELS explicitly or export LLM_MODEL_NAME.
MODELS_CSV="${MODELS:-${LLM_MODEL_NAME:-}}"
if [ -z "$MODELS_CSV" ]; then
  echo "[ERROR] Set MODELS to the provider model name before running baselines." >&2
  exit 2
fi
START="${START:-}"
END="${END:-}"
MAX_CONCURRENT="${MAX_CONCURRENT:-4}"
# pixel excluded from defaults: it needs its own image-generation endpoint
# (needs a Gemini image model); opt in with ALGORITHMS=mermaid,direct_llm,pixel.
# tlkz excluded from defaults: it compiles LaTeX locally, so it needs pdflatex
# (TeX Live/MacTeX) on PATH and PyMuPDF in the python env; opt in with
# ALGORITHMS=tlkz. Outputs land in $BASELINE_OUTPUT_DIR/code_tlkz/<model>.
ALGORITHMS_CSV="${ALGORITHMS:-mermaid,direct_llm}"
ALLOW_UNSUPPORTED_RANGE="${ALLOW_UNSUPPORTED_RANGE:-0}"
# Keep decoding aligned with the generator configuration for a fair comparison.
BASELINE_TEMPERATURE="${BASELINE_TEMPERATURE:-1}"

# Experiment ID for experiments/ directory layout
EXP_ID="${EVO_EXPERIMENT_ID:-$(date +%Y-%m-%d)}"
BASELINE_OUTPUT_DIR="$PROJECT_ROOT/experiments/$EXP_ID/outputs/baseline"

IFS="," read -r -a MODELS <<< "$MODELS_CSV"
IFS="," read -r -a ALGORITHMS <<< "$ALGORITHMS_CSV"

if [[ "$DATASET" = /* ]]; then
  DATASET_PATH="$DATASET"
else
  DATASET_PATH="$PROJECT_ROOT/$DATASET"
fi

BASELINE_START=0
BASELINE_END=""
if [ -n "$START" ] || [ -n "$END" ]; then
  if [ -z "$START" ] || [ -z "$END" ]; then
    echo "[ERROR] START and END must be set together for baseline generation." >&2
    exit 2
  fi
  if ! [[ "$START" =~ ^[1-9][0-9]*$ ]]; then
    echo "[ERROR] START must be a positive 1-based integer: $START" >&2
    exit 2
  fi
  if ! [[ "$END" =~ ^[1-9][0-9]*$ ]]; then
    echo "[ERROR] END must be a positive 1-based integer: $END" >&2
    exit 2
  fi
  if [ "$START" -gt "$END" ]; then
    echo "[ERROR] START must be <= END (START=$START, END=$END)" >&2
    exit 2
  fi
  BASELINE_START=$((START - 1))
  BASELINE_END="$END"
fi

range_requested() {
  [ -n "$START" ] || [ -n "$END" ]
}

require_range_supported() {
  local algo="$1"
  if range_requested && [ "$ALLOW_UNSUPPORTED_RANGE" != "1" ]; then
    echo "[ERROR] $algo baseline does not support START/END range selection." >&2
    echo "[ERROR] Run without START/END, or set ALLOW_UNSUPPORTED_RANGE=1 to run the full dataset intentionally." >&2
    exit 2
  fi
  if range_requested; then
    echo "[WARN] $algo baseline ignores START/END; running the full dataset because ALLOW_UNSUPPORTED_RANGE=1." >&2
  fi
}

echo "========================================"
echo "  Baseline Generation"
echo "========================================"
echo "[INFO] Dataset:     $DATASET"
echo "[INFO] Resolved:    $DATASET_PATH"
echo "[INFO] Models:      ${MODELS[*]}"
echo "[INFO] Range:       ${START:-all} → ${END:-all}"
echo "[INFO] Concurrent:  $MAX_CONCURRENT"
echo "[INFO] Algorithms:  ${ALGORITHMS[*]}"
echo "[INFO] Temperature: $BASELINE_TEMPERATURE"
echo "[INFO] Exp ID:      $EXP_ID"
echo "[INFO] Output:      $BASELINE_OUTPUT_DIR"
echo ""

run_mermaid() {
  local model="$1"
  echo "[INFO] Running Mermaid: $model"
  local cmd=("$PYTHON_BIN" -u -m baselines.programmic.mermaid.main
    --dataset "$DATASET_PATH"
    --model "$model"
    --temperature "$BASELINE_TEMPERATURE"
    --start "$BASELINE_START"
    --max-concurrent "$MAX_CONCURRENT"
    --output-dir "$BASELINE_OUTPUT_DIR/code_mermaid/$model"
  )
  if [ -n "$BASELINE_END" ]; then cmd+=(--end "$BASELINE_END"); fi
  "${cmd[@]}"
}

run_tlkz() {
  local model="$1"
  echo "[INFO] Running TiKZ: $model"
  local cmd=("$PYTHON_BIN" -u -m baselines.programmic.tlkz.main
    --dataset "$DATASET_PATH"
    --model "$model"
    --temperature "$BASELINE_TEMPERATURE"
    --start "$BASELINE_START"
    --max-concurrent "$MAX_CONCURRENT"
    --output-dir "$BASELINE_OUTPUT_DIR/code_tlkz/$model"
  )
  if [ -n "$BASELINE_END" ]; then cmd+=(--end "$BASELINE_END"); fi
  "${cmd[@]}"
}

run_direct_llm() {
  local model="$1"
  echo "[INFO] Running Direct LLM: $model"
  local limit_args=()
  if [ -n "$BASELINE_END" ]; then
    limit_args=(--limit "$((BASELINE_END - BASELINE_START))")
  fi
  LLM_OUTPUT_DIR="$BASELINE_OUTPUT_DIR/direct_llm" \
    "$PYTHON_BIN" -u -m baselines.direct_llm.main \
    --dataset "$DATASET_PATH" \
    --model "$model" \
    --canvas-library excalidraw \
    --temperature "$BASELINE_TEMPERATURE" \
    --start "$BASELINE_START" \
    ${limit_args[@]+"${limit_args[@]}"} \
    --max-concurrent "$MAX_CONCURRENT" \
    --render
}

run_pixel() {
  local model="$1"
  echo "[INFO] Running Pixel: $model"
  require_range_supported "Pixel"
  "$PYTHON_BIN" -m baselines.pixel.gemini_image_generator \
    --model "$model" \
    --dataset "$DATASET_PATH" \
    --output "$BASELINE_OUTPUT_DIR/pixel/$model"
}

run_diagramagent() {
  local model="$1"
  echo "[INFO] Running DiagramAgent: $model"
  (
    local cmd=("$PYTHON_BIN" -u -m baselines.diagramagent.DiagramAgentEvaluator
      -d "$DATASET_PATH"
      -o "$BASELINE_OUTPUT_DIR/diagramagent/$model"
      -s "$BASELINE_START"
      -t generation
      --use-gpt4o
      --write-eval-artifacts
      --eval-baseline-type diagramagent
      --eval-model-name "$model"
    )
    if [ -n "$BASELINE_END" ]; then cmd+=(-e "$BASELINE_END"); fi
    # --eval-model-name only names the output directory; the agents read the
    # model from ELYSIVER_MODEL (see run_scisketch), so without this every
    # per-model directory was produced by the same underlying model.
    ELYSIVER_MODEL="$model" "${cmd[@]}"
  )
}

run_scisketch() {
  local model="$1"
  echo "[INFO] Running SciSketch: $model"
  (
    local cmd=("$PYTHON_BIN" -u -m baselines.scisketch.src.custom_main
      --dataset "$DATASET_PATH"
      --language drawio
      --save_directory "$BASELINE_OUTPUT_DIR/scisketch/$model"
      --start "$BASELINE_START"
      --export_png
      --write_eval_artifacts
      --eval_baseline_type scisketch
      --eval_model_name "$model"
    )
    if [ -n "$BASELINE_END" ]; then cmd+=(--end "$BASELINE_END"); fi
    ELYSIVER_MODEL="$model" "${cmd[@]}"
  )
}

for model in "${MODELS[@]}"; do
  echo "========================================"
  echo "[INFO] Model: $model"
  echo "========================================"

  for algo in "${ALGORITHMS[@]}"; do
    case "$algo" in
      mermaid)      run_mermaid "$model" ;;
      tlkz)         run_tlkz "$model" ;;
      direct_llm)   run_direct_llm "$model" ;;
      pixel)        run_pixel "$model" ;;
      diagramagent) run_diagramagent "$model" ;;
      scisketch)    run_scisketch "$model" ;;
      *)
        echo "[ERROR] Unknown algorithm: $algo" >&2
        exit 2
        ;;
    esac
  done
done

echo ""
echo "[INFO] Baseline generation complete."
