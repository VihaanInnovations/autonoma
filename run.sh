#!/bin/bash
set -euo pipefail

echo "========================================"
echo "   Autonoma Community Edition Launcher  "
echo "========================================"
echo ""

# 1. Component Check
if [ ! -d "daemon" ]; then
    echo "[ERROR] 'daemon' folder not found. Are you in the right directory?"
    exit 1
fi

# 2. Python Detection
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    VER=$(python3 --version 2>&1)
    PYTHON_CMD="python3"
    echo "[OK] Python Detector: Found 'python3' ($VER)"
elif command -v python &> /dev/null; then
    VER=$(python --version 2>&1)
    PYTHON_CMD="python"
    echo "[OK] Python Detector: Found 'python' ($VER)"
else
    echo "[CRITICAL] No Python found! Please install Python 3.10+."
    exit 1
fi

# 3. Environment Setup
VENV_PATH="daemon/venv"
if [ ! -d "$VENV_PATH" ] || [ ! -f "$VENV_PATH/bin/activate" ]; then
    if [ -d "$VENV_PATH" ]; then
        echo "[INFO] Existing venv is not Linux-compatible. Recreating..."
        rm -rf "$VENV_PATH"
    fi
    echo "[INFO] First time setup: Creating Virtual Environment..."
    $PYTHON_CMD -m venv "$VENV_PATH"

    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to create venv."
        exit 1
    fi

    echo "[INFO] Installing Dependencies (this may take a minute)..."
    "$VENV_PATH/bin/pip" install -r daemon/requirements.txt

    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to install dependencies."
        exit 1
    fi
fi

# 4. Launch
echo ""
echo "[INFO] Starting Autonoma Daemon..."
echo "----------------------------------------"

# Use the venv python to run the script
"$VENV_PATH/bin/python" daemon/start.py
