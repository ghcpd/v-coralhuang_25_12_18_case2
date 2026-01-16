Param()
$here = Split-Path -Path $MyInvocation.MyCommand.Path -Parent
Set-Location $here
Write-Host "Creating virtualenv .venv and installing dependencies..."
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip | Out-Null
python -m pip install -r requirements.txt | Out-Null

Write-Host "Running harness (full run: RAW then COMPAT)..."
$proc = Start-Process -FilePath python -ArgumentList "e2e_api_regression_harness.py" -NoNewWindow -Wait -PassThru
if ($proc.ExitCode -ne 0) {
    Write-Error "run_tests.ps1: FAILED (exit $($proc.ExitCode))"
    exit $proc.ExitCode
}
Write-Host "run_tests.ps1: SUCCESS - FAIL-THEN-PASS gate satisfied"
