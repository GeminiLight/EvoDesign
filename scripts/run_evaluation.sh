#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# Orchestration layer: batch-run evaluation over multiple methods.
# The actual single-run logic lives in scripts/evaluate.sh.
#
# Configurable parameters (override via env):
#   METHODS    - comma-separated method list (required; actual generated method/model paths)
#   WORKERS    - concurrent workers (default: 4)
#   START, END - sample range pair (1-based inclusive, optional; default: all)
#   REGENERATE - 1=force re-eval (default: 0)
#   ALLOW_PARTIAL - 1=return success even if some methods fail (default: 0)
#   JUDGE_RUNS - k independent judge evaluations per (sample, metric),
#                aggregated by median (default: 1, single judge run).
#                Changing k invalidates stored results via the run signature.

WORKERS="${WORKERS:-4}"
METHODS_CSV="${METHODS:-}"
START="${START:-}"
END="${END:-}"
REGENERATE="${REGENERATE:-0}"
ALLOW_PARTIAL="${ALLOW_PARTIAL:-0}"
JUDGE_RUNS="${JUDGE_RUNS:-1}"
EXP_ID="${EVO_EXPERIMENT_ID:-$(date +%Y-%m-%d)}"

if ! [[ "$JUDGE_RUNS" =~ ^[1-9][0-9]*$ ]]; then
  echo "[ERROR] JUDGE_RUNS must be a positive integer: $JUDGE_RUNS" >&2
  exit 2
fi

if [ -n "$START" ] || [ -n "$END" ]; then
  if [ -z "$START" ] || [ -z "$END" ]; then
    echo "[ERROR] START and END must be set together for evaluation." >&2
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

# Select only the actual outputs you generated, including batch-capable baselines.
# This avoids silently evaluating another model's old result directories.
if [ -z "$METHODS_CSV" ]; then
  echo "[ERROR] Set METHODS to the generated method/model directories (see docs/reproducibility.md)." >&2
  exit 2
fi
IFS="," read -r -a METHODS <<< "$METHODS_CSV"

echo "========================================"
echo "  Batch Evaluation"
echo "========================================"
echo "[INFO] Workers:    $WORKERS"
echo "[INFO] Range:      ${START:-all} → ${END:-all}"
echo "[INFO] Methods:    ${#METHODS[@]}"
echo "[INFO] Regenerate: $REGENERATE"
echo "[INFO] Judge runs: $JUDGE_RUNS"
echo "[INFO] Partial OK: $ALLOW_PARTIAL"
echo "[INFO] Exp ID:     $EXP_ID"
echo ""

FAILED_METHODS=()
for method in "${METHODS[@]}"; do
  echo "----------------------------------------"
  echo "[INFO] Evaluating: $method"
  echo "----------------------------------------"

  cmd=("$PROJECT_ROOT/scripts/evaluate.sh"
    --method "$method"
    --workers "$WORKERS"
    --exp-id "$EXP_ID"
    --judge-runs "$JUDGE_RUNS"
  )

  if [ -n "$START" ]; then cmd+=(--start "$START"); fi
  if [ -n "$END" ]; then cmd+=(--end "$END"); fi
  if [ "$REGENERATE" -eq 1 ]; then cmd+=(--regeneration); fi

  if ! "${cmd[@]}"; then
    echo "[ERROR] Evaluation failed for $method"
    FAILED_METHODS+=("$method")
  fi
  echo ""
done

if [ "${#FAILED_METHODS[@]}" -gt 0 ]; then
  echo "[ERROR] Failed methods: ${FAILED_METHODS[*]}"
  if [ "$ALLOW_PARTIAL" -eq 1 ]; then
    echo "[WARN] ALLOW_PARTIAL=1, returning success despite failures."
  else
    exit 1
  fi
fi

echo "[INFO] Batch evaluation complete."
echo "[INFO] Results: experiments/$EXP_ID/scores/"
