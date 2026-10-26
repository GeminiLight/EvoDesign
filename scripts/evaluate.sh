#!/bin/bash
# Fixed wrapper: run a single evaluation from anywhere.
# Usage: ./scripts/evaluate.sh --method <method> [args...]
# All args are forwarded to evaluation.run_evaluation.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"
python3 -m evaluation.run_evaluation "$@"
