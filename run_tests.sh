#!/usr/bin/env bash
set -euo pipefail

VENV=.venv
PYTHON=${PYTHON:-python}

echo "Creating virtual environment in $VENV"
$PYTHON -m venv "$VENV"
"$VENV/bin/python" -m pip install -U pip
"$VENV/bin/pip" install -r requirements.txt -r requirements-dev.txt

# Mode A: RAW_V2 - we expect this to demonstrate failures (non-zero exit)
echo "\n--- Running Mode A: RAW_V2 (expected to FAIL) ---"
"$VENV/bin/python" e2e_api_regression_harness.py --mode RAW_V2 || RAW_EXIT=$?
RAW_EXIT=${RAW_EXIT:-0}
if [ "$RAW_EXIT" -eq 0 ]; then
  echo "ERROR: Mode A (RAW_V2) unexpectedly passed; expected failures to be demonstrated"
  exit 1
else
  echo "OK: Mode A (RAW_V2) showed failures as expected (exit $RAW_EXIT)"
fi

# Mode B: COMPAT - we expect ALL checks to PASS
echo "\n--- Running Mode B: COMPAT (expected to PASS) ---"
"$VENV/bin/python" e2e_api_regression_harness.py --mode COMPAT
COMPAT_EXIT=$?
if [ "$COMPAT_EXIT" -ne 0 ]; then
  echo "ERROR: Mode B (COMPAT) failed (exit $COMPAT_EXIT)"
  exit 1
fi

echo "\nSUCCESS: RAW_V2 showed failures and COMPAT passed all checks. Gate satisfied."
exit 0
