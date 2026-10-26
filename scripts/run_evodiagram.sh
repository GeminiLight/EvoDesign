#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# Ensure imports work when the script is launched from any directory.
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# EvoDiagram generation script.
#
# Usage:
#   ./scripts/run_evodiagram.sh
#
# Environment variables:
#   DATASET          Dataset JSON path (default: dataset/test/data.json)
#   MODELS           Comma-separated models.yaml alias list
#                    (default: configured-model)
#   START, END       Sample range pair (1-based inclusive, optional; default: all)
#   ABLATION         Ablation config: full | wo_refiner | wo_multiagent | custom
#                    (default: full)
#   EXTRA_ARGS       Additional args forwarded to main.py (useful for custom ablations)
#   REFINER_ITERS    Max refinement iterations when refiner is enabled (default: 1)

DATASET="${DATASET:-dataset/test/data.json}"
# Values are configs/models.yaml aliases (main.py --model validates against
# has_model). The public default reads the explicit LLM_* configuration.
MODELS_CSV="${MODELS:-configured-model}"
START="${START:-}"
END="${END:-}"
ABLATION="${ABLATION:-full}"
EXTRA_ARGS="${EXTRA_ARGS:-}"
REFINER_ITERS="${REFINER_ITERS-1}"

IFS="," read -r -a MODELS <<< "$MODELS_CSV"

if [[ "$DATASET" = /* ]]; then
  DATASET_PATH="$DATASET"
else
  DATASET_PATH="$PROJECT_ROOT/$DATASET"
fi

if [ -n "$START" ] || [ -n "$END" ]; then
  if [ -z "$START" ] || [ -z "$END" ]; then
    echo "[ERROR] START and END must be set together for EvoDiagram generation." >&2
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
fi

# Resolve ablation → variant mapping
# Variant presets automatically configure mode/refiner/icons in Python.
VARIANT="evodiagram"
PASS_VARIANT=1
PASS_REFINER_ITERS=1
REFINER_LABEL="enabled"

case "$ABLATION" in
  full)
    ;;
  wo_refiner)
    VARIANT="evodiagram_wo_refiner"
    PASS_REFINER_ITERS=0
    REFINER_LABEL="disabled by variant"
    ;;
  wo_multiagent)
    VARIANT="evodiagram_wo_multiagent"
    ;;
  wo_icons)
    VARIANT="evodiagram_wo_icons"
    ;;
  custom)
    # User controls runtime defaults via settings.yaml and EXTRA_ARGS.
    PASS_VARIANT=0
    REFINER_LABEL="controlled by settings/EXTRA_ARGS"
    ;;
  *)
    echo "[ERROR] Unknown ABLATION: $ABLATION"
    echo "        Supported: full, wo_refiner, wo_multiagent, wo_icons, custom"
    exit 1
    ;;
esac

echo "========================================"
echo "  EvoDiagram Generation"
echo "========================================"
echo "[INFO] Dataset:   $DATASET"
echo "[INFO] Resolved:  $DATASET_PATH"
echo "[INFO] Models:    ${MODELS[*]}"
echo "[INFO] Range:     ${START:-all} → ${END:-all}"
echo "[INFO] Ablation:  $ABLATION"
if [ "$PASS_VARIANT" -eq 1 ]; then
  echo "[INFO] Variant:   $VARIANT"
else
  echo "[INFO] Variant:   settings/EXTRA_ARGS"
fi
if [ "$PASS_REFINER_ITERS" -eq 1 ]; then
  echo "[INFO] Refiner:   $REFINER_LABEL (iters=$REFINER_ITERS)"
else
  echo "[INFO] Refiner:   $REFINER_LABEL"
fi
if [ -n "$EXTRA_ARGS" ]; then
  echo "[INFO] Extra:     $EXTRA_ARGS"
fi
echo ""

for model in "${MODELS[@]}"; do
  echo "----------------------------------------"
  echo "[INFO] Model: $model"
  echo "----------------------------------------"

  cmd=("$PYTHON_BIN" -m evo_diagram.agentic_system.main
    --model "$model"
    --dataset-path "$DATASET_PATH"
  )

  if [ "$PASS_VARIANT" -eq 1 ]; then
    cmd+=(--variant "$VARIANT")
  fi
  if [ "$PASS_REFINER_ITERS" -eq 1 ] && [ -n "$REFINER_ITERS" ]; then
    cmd+=(--refiner-iterations "$REFINER_ITERS")
  fi
  if [ -n "$START" ]; then
    cmd+=(--start "$START" --end "$END")
  else
    cmd+=(--all)
  fi
  if [ -n "$EXTRA_ARGS" ]; then
    # shellcheck disable=SC2086
    cmd+=($EXTRA_ARGS)
  fi

  "${cmd[@]}"
done

echo ""
echo "[INFO] EvoDiagram generation complete."
