# PowerShell run_tests
Set-StrictMode -Version Latest
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Write-Host "Using PowerShell and Python to run tests"

if (-not (Test-Path -Path "$root\.venv")) {
    python -m venv "$root\.venv"
}
# activate venv
. "$root\.venv\Scripts\Activate.ps1"
python -m pip install --upgrade pip
python -m pip install -r "$root\requirements.txt"
python -m pip install -r "$root\requirements-dev.txt"

Write-Host "\n== Running Mode: RAW (expected to SHOW breaks) =="
$raw = & { $env:MODE = 'RAW'; python "$root\e2e_api_regression_harness.py" }
if ($LASTEXITCODE -ne 0) { Write-Error "RAW phase failed (unexpected)"; exit 2 }

Write-Host "\n== Running Mode: COMPAT (expected to PASS all compatibility checks) =="
$env:MODE = 'COMPAT'
python "$root\e2e_api_regression_harness.py"
if ($LASTEXITCODE -ne 0) { Write-Error "COMPAT phase failed (compat mapping did not fix all issues)"; exit 3 }

Write-Host "\nSUCCESS: RAW phase demonstrated breaks and COMPAT phase passed all checks."
# deactivate: PowerShell venv deactivation is implicit when shell ends
