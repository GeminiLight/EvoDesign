#!/bin/bash
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PID_DIR="$PROJECT_ROOT/scripts/.pids"
LOG_DIR="$PROJECT_ROOT/scripts/logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

usage() {
    echo -e "${CYAN}Usage:${NC} $0 [all|backend|renderer|frontend]"
    echo ""
    echo "  all       - Start all services (default)"
    echo "  backend   - Start backend API (port 3010)"
    echo "  renderer  - Start renderer service (port 3000)"
    echo "  frontend  - Start frontend dev server (port 5175)"
    exit 1
}

is_running() {
    local name=$1
    local pid_file="$PID_DIR/${name}.pid"
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        rm -f "$pid_file"
    fi
    return 1
}

start_backend() {
    if is_running backend; then
        echo -e "${YELLOW}[Backend API] Already running (PID: $(cat "$PID_DIR/backend.pid"))${NC}"
        return
    fi
    echo -e "${GREEN}[Backend API]${NC} Starting on port 3010..."
    (
        cd "$PROJECT_ROOT/backend"
        # Prefer the repository environment created by `uv venv` / the setup
        # guide. Never let a globally installed uvicorn select another Python.
        local python_bin
        if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
            python_bin="$PROJECT_ROOT/.venv/bin/python"
        elif [ -x "$PROJECT_ROOT/backend/venv/bin/python" ]; then
            python_bin="$PROJECT_ROOT/backend/venv/bin/python"
        else
            python_bin="python3"
        fi
        # backend/app/config.py imports evo_diagram.utils.env_loader, but the
        # package lives at the repo root and is not installed into backend/venv.
        # Running uvicorn from backend/ therefore fails with
        # "ModuleNotFoundError: No module named 'evo_diagram'" unless the repo
        # root is on the path. Prepend it, keeping any existing PYTHONPATH.
        export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
        exec "$python_bin" -m uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port 3010 --reload
    ) > "$LOG_DIR/backend.log" 2>&1 &
    echo $! > "$PID_DIR/backend.pid"
    echo -e "${GREEN}[Backend API]${NC} Started (PID: $!)"
}

start_renderer() {
    if is_running renderer; then
        echo -e "${YELLOW}[Renderer] Already running (PID: $(cat "$PID_DIR/renderer.pid"))${NC}"
        return
    fi
    echo -e "${GREEN}[Renderer]${NC} Starting on port 3000..."
    (
        cd "$PROJECT_ROOT/evo_diagram/agentic_system/tool_services"
        if [ ! -d "node_modules" ]; then
            echo "[Renderer] Installing dependencies..."
            npm ci
        fi
        exec npm run dev -- --hostname 127.0.0.1
    ) > "$LOG_DIR/renderer.log" 2>&1 &
    echo $! > "$PID_DIR/renderer.pid"
    echo -e "${GREEN}[Renderer]${NC} Started (PID: $!)"
}

start_frontend() {
    if is_running frontend; then
        echo -e "${YELLOW}[Frontend] Already running (PID: $(cat "$PID_DIR/frontend.pid"))${NC}"
        return
    fi
    echo -e "${GREEN}[Frontend]${NC} Starting on port 5175..."
    (
        cd "$PROJECT_ROOT/frontend"
        if [ ! -d "node_modules" ]; then
            echo "[Frontend] Installing dependencies..."
            npm ci
        fi
        exec npm run dev
    ) > "$LOG_DIR/frontend.log" 2>&1 &
    echo $! > "$PID_DIR/frontend.pid"
    echo -e "${GREEN}[Frontend]${NC} Started (PID: $!)"
}

TARGET="${1:-all}"

# Pre-flight checks: repository-root .env is the shared source for EvoDesign
# secrets (STEPFUN_API_KEY plus backend JWT/SESSION secrets). backend/.env is
# optional and only used for backend-specific overrides.
MISSING_ENV=0
if [[ "$TARGET" == "all" || "$TARGET" == "backend" ]] && [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo -e "${RED}ERROR: .env not found.${NC}"
    echo "  python3 scripts/setup_local.py"
    MISSING_ENV=1
fi
if [[ "$TARGET" == "all" || "$TARGET" == "frontend" ]] && [ ! -f "$PROJECT_ROOT/frontend/.env" ]; then
    echo -e "${RED}ERROR: frontend/.env not found.${NC}"
    echo "  python3 scripts/setup_local.py"
    MISSING_ENV=1
fi
if [[ "$TARGET" != "all" && "$TARGET" != "backend" && "$TARGET" != "renderer" && "$TARGET" != "frontend" ]]; then
    usage
    MISSING_ENV=1
fi
if [ "$MISSING_ENV" -eq 1 ]; then
    exit 1
fi

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  EvoDesign Service Launcher${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

case "$TARGET" in
    all)
        start_backend
        start_renderer
        start_frontend
        ;;
    backend)
        start_backend
        ;;
    renderer)
        start_renderer
        ;;
    frontend)
        start_frontend
        ;;
    *)
        usage
        ;;
esac

echo ""
echo -e "${CYAN}Services:${NC}"
echo -e "  Backend API : http://localhost:3010  (docs: http://localhost:3010/docs)"
echo -e "  Renderer    : http://localhost:3000"
echo -e "  Frontend    : http://localhost:5175"
echo ""
echo -e "${CYAN}Logs:${NC}       $LOG_DIR/"
echo -e "${CYAN}Stop with:${NC}  ./scripts/stop_service.sh [all|backend|renderer|frontend]"
