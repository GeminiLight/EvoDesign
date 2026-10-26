#!/bin/bash
# EvoDiagram Environment Setup Script
# This script sets up the development environment for EvoDiagram

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== EvoDiagram Environment Setup ===${NC}"
echo ""

# Check Python version
echo -e "${YELLOW}[1/4] Checking Python version...${NC}"
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Found Python $python_version"

if ! python3 -c "import sys; assert sys.version_info >= (3, 11)"; then
    echo -e "${RED}Error: Python 3.11 or higher is required${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python version OK${NC}"
echo ""

# Install Python dependencies
echo -e "${YELLOW}[2/4] Installing Python dependencies...${NC}"
pip install --upgrade pip
pip install -r "$SCRIPT_DIR/requirements.txt"
echo -e "${GREEN}✓ Python dependencies installed${NC}"
echo ""

# Setup icons
echo -e "${YELLOW}[3/4] Setting up Material Icons...${NC}"
python "$SCRIPT_DIR/scripts/setup_icons.py"
echo -e "${GREEN}✓ Icons setup complete${NC}"
echo ""

# Create necessary directories
echo -e "${YELLOW}[4/5] Creating directories...${NC}"
mkdir -p data/chroma
mkdir -p data/knowledge
mkdir -p examples
mkdir -p results
echo -e "${GREEN}✓ Directories created${NC}"
echo ""

# Setup tool_services
echo -e "${YELLOW}[5/5] Setting up tool_services...${NC}"
TOOL_SERVICES_DIR="$SCRIPT_DIR/agentic_system/tool_services"
if [ -d "$TOOL_SERVICES_DIR" ]; then
    echo "Installing tool_services dependencies..."
    cd "$TOOL_SERVICES_DIR"
    if [ -f "package.json" ]; then
        npm install
        echo -e "${GREEN}✓ tool_services dependencies installed${NC}"
        cd "$REPO_ROOT"
    else
        echo -e "${YELLOW}⚠ No package.json found in tool_services, skipping npm install${NC}"
        cd "$REPO_ROOT"
    fi
else
    echo -e "${YELLOW}⚠ tool_services directory not found, skipping${NC}"
fi
echo ""

# Check for .env file
echo -e "${YELLOW}Checking environment configuration...${NC}"
if [ ! -f "$REPO_ROOT/.env" ]; then
    if [ -f "$REPO_ROOT/.env.example" ]; then
        echo -e "${YELLOW}Creating repository-root .env from .env.example...${NC}"
        cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
        echo -e "${GREEN}✓ .env file created at $REPO_ROOT/.env${NC}"
        echo -e "${YELLOW}⚠ Please update .env with your actual API keys${NC}"
    else
        echo -e "${RED}⚠ No .env.example found at repository root, please create .env manually${NC}"
    fi
else
    echo -e "${GREEN}✓ repository-root .env file found${NC}"
fi

echo ""
echo -e "${GREEN}=== Setup Complete! ===${NC}"
echo ""
echo "Next steps:"
echo "  1. Configure repository-root .env with STEPFUN_API_KEY"
echo "  2. Run a test from the repository root: python -m evo_diagram.agentic_system.main --example 1 --dataset-path dataset/test/data.json"
echo ""
echo "For more information, see:"
echo "  - README.md (English)"
echo "  - wiki/setup_zh.md (Chinese)"
