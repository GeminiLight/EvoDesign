#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ALGORITHMS=diagramagent exec "$ROOT/scripts/run_baselines.sh" "$@"
