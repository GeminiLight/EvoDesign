#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

choose_python() {
    if [[ -n "${PYTHON_BIN:-}" ]]; then
        echo "$PYTHON_BIN"
        return
    fi
    if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
        echo "$PROJECT_ROOT/.venv/bin/python"
        return
    fi
    if command -v python3 >/dev/null 2>&1; then
        command -v python3
        return
    fi
    command -v python
}

PY="$(choose_python)"
TARGET="${1:-architecture}"

run_hygiene() {
    cd "$PROJECT_ROOT"
    git diff --check
}

run_architecture() {
    cd "$PROJECT_ROOT"
    "$PY" scripts/generate_frontend_api_contract.py --check
    "$PY" -m pytest \
        tests/test_architecture.py \
        tests/canvas_environment/test_facade.py \
        tests/test_repo_docs.py \
        tests/test_scripts.py \
        tests/test_release_tools.py
}

run_backend() {
    cd "$PROJECT_ROOT"
    "$PY" -m pytest tests/backend
}

run_evaluation() {
    cd "$PROJECT_ROOT"
    "$PY" -m pytest tests/evaluation
}

run_baselines() {
    cd "$PROJECT_ROOT"
    "$PY" -m pytest tests/baselines
}

run_engine() {
    cd "$PROJECT_ROOT"
    # Discover new engine tests automatically. The embedding download/inference
    # integration remains an explicit local check, separate from offline CI.
    "$PY" -m pytest tests/pipeline evo_diagram/tests \
        --ignore=evo_diagram/tests/user_memory \
        --ignore=evo_diagram/tests/design_memory/test_real_chroma_cosine.py
}

run_user_memory() {
    cd "$PROJECT_ROOT"
    "$PY" -m pytest evo_diagram/tests/user_memory
}

run_frontend() {
    cd "$PROJECT_ROOT"
    "$PY" -m pytest tests/test_frontend_contract.py
    cd "$PROJECT_ROOT/frontend"
    npm run lint
    npm run test:icons
    npm run test:editor
    npm run test:browser
    npm run build
    npm run build:browser
}

run_renderer() {
    cd "$PROJECT_ROOT"
    "$PY" -m pytest tests/test_tool_service_contract.py
    cd "$PROJECT_ROOT/evo_diagram/agentic_system/tool_services"
    npm run typecheck --if-present
    npm run build
}

usage() {
    cat <<'EOF'
Usage: ./scripts/check_quality.sh [architecture|backend|engine|evaluation|baselines|user-memory|frontend|renderer|all]

Targets:
  architecture  Import boundaries, generated API contract, canvas_environment facade, repo doc, and script contract checks.
  backend       Full FastAPI service, API, database, auth, and boundary checks.
  engine        Package-local engine contracts plus cross-stage pipeline smoke checks.
  evaluation    Evaluation CLI/result contract checks.
  baselines     Baseline entrypoint and output-layout contract checks.
  user-memory   User preference memory extraction/storage contract checks.
  frontend      React lint and production build.
  renderer      Next.js renderer typecheck if present and production build.
  all           Run every target plus git diff whitespace checks.

Set PYTHON_BIN=/path/to/python to override the Python interpreter.
EOF
}

case "$TARGET" in
    architecture)
        run_hygiene
        run_architecture
        ;;
    backend)
        run_hygiene
        run_backend
        ;;
    engine)
        run_hygiene
        run_engine
        ;;
    evaluation)
        run_hygiene
        run_evaluation
        ;;
    baselines)
        run_hygiene
        run_baselines
        ;;
    user-memory)
        run_hygiene
        run_user_memory
        ;;
    frontend)
        run_hygiene
        run_frontend
        ;;
    renderer)
        run_hygiene
        run_renderer
        ;;
    all)
        run_hygiene
        run_architecture
        run_backend
        run_engine
        run_evaluation
        run_baselines
        run_user_memory
        run_frontend
        run_renderer
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        usage
        exit 1
        ;;
esac
