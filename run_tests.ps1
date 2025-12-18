# PowerShell test runner
$ErrorActionPreference = 'Stop'

# Create virtualenv
python -m venv .venv
& .\.venv\Scripts\Activate.ps1

pip install -r requirements-dev.txt

# Run raw mode (expected to fail)
$env:MODE = 'raw'
try { python e2e_api_regression_harness.py; $rawExit = $LASTEXITCODE } catch { $rawExit = 1 }

# Run compat mode (expected to pass)
$env:MODE = 'compat'
try { python e2e_api_regression_harness.py; $compatExit = $LASTEXITCODE } catch { $compatExit = 1 }

if ($rawExit -eq 0) {
  Write-Host "Expected Mode A (raw) to FAIL but it passed"
  exit 1
}

if ($compatExit -ne 0) {
  Write-Host "Expected Mode B (compat) to PASS but it failed"
  exit 1
}

Write-Host "✅ PASS-THEN-PASS gate satisfied: raw failed and compat passed"
exit 0
