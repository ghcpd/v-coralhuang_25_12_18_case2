#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
python - <<'PY'
import sys, os, subprocess
print('Using python:', sys.executable)
PY

# create venv
if [ ! -d ".venv" ]; then
  python -m venv .venv
fi
# shellcheck source=/dev/null
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt

echo "\n== Running Mode: RAW (expected to SHOW breaks) =="
MODE=RAW python e2e_api_regression_harness.py || { echo "RAW phase failed (unexpected)"; deactivate; exit 2; }

echo "\n== Running Mode: COMPAT (expected to PASS all compatibility checks) =="
MODE=COMPAT python e2e_api_regression_harness.py || { echo "COMPAT phase failed (compat mapping did not fix all issues)"; deactivate; exit 3; }

echo "\nSUCCESS: RAW phase demonstrated breaks and COMPAT phase passed all checks."
deactivate
