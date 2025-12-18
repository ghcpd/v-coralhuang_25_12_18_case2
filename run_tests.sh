#!/usr/bin/env bash
set -euo pipefail

# Create/activate virtualenv
python -m venv .venv
source .venv/bin/activate

pip install -r requirements-dev.txt

# Run raw mode (expected to fail)
set +e
MODE=raw python e2e_api_regression_harness.py
RAW_EXIT=$?
set -e

# Run compat mode (expected to pass)
MODE=compat python e2e_api_regression_harness.py
COMPAT_EXIT=$?

if [ $RAW_EXIT -eq 0 ]; then
  echo "Expected Mode A (raw) to FAIL but it passed"
  exit 1
fi

if [ $COMPAT_EXIT -ne 0 ]; then
  echo "Expected Mode B (compat) to PASS but it failed"
  exit 1
fi

echo "✅ PASS-THEN-PASS gate satisfied: raw failed and compat passed"
exit 0
