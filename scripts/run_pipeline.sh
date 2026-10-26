#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

usage() {
  echo "Usage: $0 [generate|evaluate|all]"
  echo ""
  echo "Commands:"
  echo "  generate  Run generation phase only (EvoDiagram + baselines)"
  echo "  evaluate  Run evaluation phase only"
  echo "  all       Run generation then evaluation (default)"
  echo ""
  echo "Environment variables (shared across all phases):"
  echo "  DATASET          Dataset path (default: dataset/test/data.json)"
  echo "  MODELS           Comma-separated model list"
  echo "  START, END       Sample range pair (1-based inclusive; default: all)"
  echo "  WORKERS          Evaluation workers (default: 4)"
  echo "  REGENERATE       1=force re-eval (default: 0)"
  echo ""
  echo "Per-phase switches (run_baselines.sh only):"
  echo "  ALGORITHMS       Comma-separated baseline list"
  exit 1
}

CMD="${1:-all}"
START="${START:-}"
END="${END:-}"

if [ -n "$START" ] || [ -n "$END" ]; then
  if [ -z "$START" ] || [ -z "$END" ]; then
    echo "[ERROR] START and END must be set together for pipeline runs." >&2
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

case "$CMD" in
  generate)
    echo "========================================"
    echo "  Pipeline: Generation Only"
    echo "========================================"
    echo ""
    MODELS="${GENERATOR_MODELS:-${MODELS:-configured-model}}" "$PROJECT_ROOT/scripts/run_evodiagram.sh"
    echo ""
    MODELS="${BASELINE_MODELS:-${MODELS:-${LLM_MODEL_NAME:-}}}" "$PROJECT_ROOT/scripts/run_baselines.sh"
    ;;

  evaluate)
    echo "========================================"
    echo "  Pipeline: Evaluation Only"
    echo "========================================"
    echo ""
    "$PROJECT_ROOT/scripts/run_evaluation.sh"
    ;;

  all)
    echo "========================================"
    echo "  Pipeline: Generate → Evaluate"
    echo "========================================"
    echo ""

    echo "[PHASE 1/3] EvoDiagram Generation"
    MODELS="${GENERATOR_MODELS:-${MODELS:-configured-model}}" "$PROJECT_ROOT/scripts/run_evodiagram.sh"

    echo ""
    echo "[PHASE 2/3] Baseline Generation"
    MODELS="${BASELINE_MODELS:-${MODELS:-${LLM_MODEL_NAME:-}}}" "$PROJECT_ROOT/scripts/run_baselines.sh"

    echo ""
    echo "[PHASE 3/3] Evaluation"
    "$PROJECT_ROOT/scripts/run_evaluation.sh"
    ;;

  *)
    usage
    ;;
esac

echo ""
echo "========================================"
echo "  Pipeline Complete"
echo "========================================"
