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

get_pid_by_port() {
    local port=$1
    local netstat_output=""
    local pid=""

    if command -v netstat >/dev/null 2>&1; then
        netstat_output=$(netstat -vanp tcp 2>/dev/null | grep -E "[:.]${port}([[:space:]]|$)" || true)
        if [ -z "$netstat_output" ]; then
            netstat_output=$(netstat -tulpn 2>/dev/null | grep -E ":[[:space:]]*${port}([[:space:]]|$)" || true)
        fi
    fi

    pid=$(printf '%s\n' "$netstat_output" | awk '
        /pid=[0-9]+/ {
            match($0, /pid=([0-9]+)/, m)
            print m[1]
            exit
        }
        /^[[:space:]]*tcp/ {
            split($0, fields, /[[:space:]]+/)
            program = fields[length(fields)]
            if (program ~ /^[0-9]+\//) {
                split(program, parts, "/")
                print parts[1]
                exit
            }
        }
    ')

    printf '%s\n' "$pid"
}

kill_pid_forcefully() {
    local pid=$1

    if [ -z "$pid" ]; then
        return 1
    fi

    if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
        return 0
    fi

    return 1
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

    if [ -n "$port" ]; then
        local port_pid
        port_pid=$(get_pid_by_port "$port")

        if [ -n "$port_pid" ]; then
            echo -e "${GREEN}[${name}]${NC} Stopping port ${port} (PID: ${port_pid})..."
            if kill_pid_forcefully "$port_pid"; then
                echo -e "${GREEN}[${name}]${NC} Stopped port ${port}."
            else
                echo -e "${YELLOW}[${name}]${NC} Port ${port} PID ${port_pid} is not running."
            fi
        else
            echo -e "${YELLOW}[${name}]${NC} No process found on port ${port}."
        fi
    fi

    if [ ! -f "$pid_file" ]; then
        if [ -z "$port" ]; then
            echo -e "${YELLOW}[${name}]${NC} No PID file found, not running."
        fi
        return
    fi

    local pid
    pid=$(cat "$pid_file")

    if kill -0 "$pid" 2>/dev/null; then
        echo -e "${GREEN}[${name}]${NC} Stopping (PID: $pid)..."
        kill_pid_forcefully "$pid"
        echo -e "${GREEN}[${name}]${NC} Stopped."
    else
        echo -e "${YELLOW}[${name}]${NC} Process $pid not running (stale PID file)."
    fi

    rm -f "$pid_file"
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
