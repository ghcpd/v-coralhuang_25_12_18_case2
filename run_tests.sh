#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Creating virtualenv .venv (if missing) and installing dependencies..."
python -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -r requirements.txt

echo "Running harness (full run: RAW then COMPAT)..."
python e2e_api_regression_harness.py
EXIT=$?
if [ $EXIT -ne 0 ]; then
  echo "run_tests: FAILED (exit $EXIT)"
  exit $EXIT
fi

echo "run_tests: SUCCESS - FAIL-THEN-PASS gate satisfied"
