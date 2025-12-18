# PowerShell run_tests.ps1
param()
$ErrorActionPreference = 'Stop'
$VENV = '.venv'
$PYTHON = if ($env:PYTHON) { $env:PYTHON } else { 'python' }

Write-Host "Creating virtual environment in $VENV"
& $PYTHON -m venv $VENV
& "$VENV\Scripts\python.exe" -m pip install -U pip
& "$VENV\Scripts\pip.exe" install -r requirements.txt -r requirements-dev.txt

Write-Host "`n--- Running Mode A: RAW_V2 (expected to FAIL) ---"
& "$VENV\Scripts\python.exe" e2e_api_regression_harness.py --mode RAW_V2
$rawExit = $LASTEXITCODE
if ($rawExit -eq 0) {
    Write-Error "ERROR: Mode A (RAW_V2) unexpectedly passed; expected failures to be demonstrated"
    exit 1
} else {
    Write-Host "OK: Mode A (RAW_V2) showed failures as expected (exit $rawExit)"
}

Write-Host "`n--- Running Mode B: COMPAT (expected to PASS) ---"
& "$VENV\Scripts\python.exe" e2e_api_regression_harness.py --mode COMPAT
if ($LASTEXITCODE -ne 0) {
    Write-Error "ERROR: Mode B (COMPAT) failed (exit $LASTEXITCODE)"
    exit 1
}

Write-Host "`nSUCCESS: RAW_V2 showed failures and COMPAT passed all checks. Gate satisfied."
exit 0
