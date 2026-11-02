#!/bin/bash

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PID_DIR="$PROJECT_ROOT/scripts/.pids"

get_service_port() {
    local name=$1

    case "$name" in
        backend)
            echo 3010
            ;;
        renderer)
            echo 3000
            ;;
        frontend)
            echo 5175
            ;;
        *)
            echo ""
            ;;
    esac
}

# Seconds to wait after SIGTERM before escalating to SIGKILL.
GRACE_SECONDS="${STOP_GRACE_SECONDS:-10}"

# PIDs listening on a TCP port (one per line).
get_pids_by_port() {
    local port=$1

    if command -v lsof >/dev/null 2>&1; then
        lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u
        return
    fi
    if command -v ss >/dev/null 2>&1; then
        ss -ltnpH "sport = :$port" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u
    fi
}

process_cwd() {
    local pid=$1
    if [ -e "/proc/$pid/cwd" ]; then
        readlink "/proc/$pid/cwd" 2>/dev/null
    elif command -v lsof >/dev/null 2>&1; then
        lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1
    fi
}

process_command() {
    ps -o command= -p "$1" 2>/dev/null
}

# Only processes started from this checkout may be stopped: the working
# directory or the command line must point inside PROJECT_ROOT.
belongs_to_project() {
    local pid=$1
    local cwd
    local command

    kill -0 "$pid" 2>/dev/null || return 1
    cwd=$(process_cwd "$pid")
    case "$cwd" in
        "$PROJECT_ROOT"|"$PROJECT_ROOT"/*) return 0 ;;
    esac
    command=$(process_command "$pid")
    case "$command" in
        *"$PROJECT_ROOT"*) return 0 ;;
    esac
    return 1
}

# The PID plus all of its descendants, parents first.
process_tree() {
    local pid=$1
    local child

    echo "$pid"
    for child in $(pgrep -P "$pid" 2>/dev/null); do
        process_tree "$child"
    done
}

# SIGTERM the whole tree, wait for a graceful exit, then SIGKILL survivors.
terminate_tree() {
    local pid=$1
    local pids
    local alive
    local waited=0

    pids=$(process_tree "$pid")
    # shellcheck disable=SC2086
    kill -TERM $pids 2>/dev/null || true

    while [ "$waited" -lt "$GRACE_SECONDS" ]; do
        alive=""
        for p in $pids; do
            if kill -0 "$p" 2>/dev/null; then
                alive="$alive $p"
            fi
        done
        [ -z "$alive" ] && return 0
        sleep 1
        waited=$((waited + 1))
    done

    echo -e "${YELLOW}Processes${alive} ignored SIGTERM for ${GRACE_SECONDS}s; sending SIGKILL.${NC}"
    # shellcheck disable=SC2086
    kill -KILL $alive 2>/dev/null || true
    return 0
}

usage() {
    echo -e "${CYAN}Usage:${NC} $0 [all|backend|renderer|frontend]"
    echo ""
    echo "  all       - Stop all services (default)"
    echo "  backend   - Stop backend API"
    echo "  renderer  - Stop renderer service"
    echo "  frontend  - Stop frontend dev server"
    exit 1
}

stop_service() {
    local name=$1
    local port
    local pid_file="$PID_DIR/${name}.pid"
    port=$(get_service_port "$name")

    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file")
        if belongs_to_project "$pid"; then
            echo -e "${GREEN}[${name}]${NC} Stopping (PID: $pid)..."
            terminate_tree "$pid"
            echo -e "${GREEN}[${name}]${NC} Stopped."
        elif kill -0 "$pid" 2>/dev/null; then
            echo -e "${YELLOW}[${name}]${NC} PID $pid is no longer an EvoDesign process; leaving it running."
        else
            echo -e "${YELLOW}[${name}]${NC} Process $pid not running (stale PID file)."
        fi
        rm -f "$pid_file"
    fi

    # Catch services started outside start_service.sh (e.g. `npm run dev` in
    # this checkout), but never touch another program that owns the port.
    if [ -n "$port" ]; then
        local port_pid
        local found=""
        for port_pid in $(get_pids_by_port "$port"); do
            found=1
            if belongs_to_project "$port_pid"; then
                echo -e "${GREEN}[${name}]${NC} Stopping EvoDesign process on port ${port} (PID: ${port_pid})..."
                terminate_tree "$port_pid"
                echo -e "${GREEN}[${name}]${NC} Stopped port ${port}."
            else
                echo -e "${YELLOW}[${name}]${NC} Port ${port} is held by PID ${port_pid} outside this checkout ($(process_command "$port_pid")); leaving it running."
            fi
        done
        if [ -z "$found" ] && [ ! -f "$pid_file" ]; then
            echo -e "${YELLOW}[${name}]${NC} No process found on port ${port}."
        fi
    fi
}

TARGET="${1:-all}"

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  EvoDesign Service Stopper${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

case "$TARGET" in
    all)
        stop_service backend
        stop_service renderer
        stop_service frontend
        ;;
    backend)
        stop_service backend
        ;;
    renderer)
        stop_service renderer
        ;;
    frontend)
        stop_service frontend
        ;;
    *)
        usage
        ;;
esac

echo ""
echo -e "${GREEN}Done.${NC}"
