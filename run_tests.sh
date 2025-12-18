#!/bin/bash
# E2E API Regression Harness - Bash Test Runner
# Usage: ./run_tests.sh
# Runs the test harness in offline mode (no real API calls)

set -e

echo "=== E2E API Regression Harness Test Runner ==="
echo "Platform: Linux/macOS (Bash)"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Step 1: Check Python availability
echo "[1/4] Checking Python availability..."
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found in PATH"
    exit 1
fi
PYTHON_EXE=$(command -v python3)
echo "  Found Python: $PYTHON_EXE"

# Step 2: Create/activate virtual environment
echo ""
echo "[2/4] Setting up virtual environment..."
VENV_PATH="./venv"
if [ ! -d "$VENV_PATH" ]; then
    echo "  Creating virtual environment..."
    python3 -m venv "$VENV_PATH"
else
    echo "  Virtual environment already exists"
fi

# Activate venv
if [ ! -f "$VENV_PATH/bin/activate" ]; then
    echo "ERROR: Failed to create virtual environment"
    exit 1
fi
source "$VENV_PATH/bin/activate"
echo "  Activated: $VENV_PATH"

# Step 3: Install dependencies
echo ""
echo "[3/4] Installing dependencies..."
REQ_FILE="requirements.txt"
if [ -f "$REQ_FILE" ]; then
    echo "  Installing from $REQ_FILE..."
    python -m pip install -q -r "$REQ_FILE" --disable-pip-version-check
    echo "  Dependencies installed"
else
    echo "  WARNING: $REQ_FILE not found, skipping pip install"
fi

# Step 4: Run tests in offline mode
echo ""
echo "[4/4] Running regression tests (OFFLINE MODE)..."
echo "  Running: python e2e_api_regression_harness.py"
echo ""
echo "--- TEST OUTPUT ---"

export BASE_URL=""
python e2e_api_regression_harness.py
TEST_EXIT_CODE=$?

echo "--- END TEST OUTPUT ---"
echo ""

if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo "RESULT: All tests PASSED"
    echo ""
    echo "The compatibility mapping successfully transforms v2 responses to legacy-safe shapes."
    echo ""
    exit 0
else
    echo "RESULT: Some tests FAILED (exit code: $TEST_EXIT_CODE)"
    exit 1
fi
