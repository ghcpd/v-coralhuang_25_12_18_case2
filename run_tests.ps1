# E2E API Regression Harness - PowerShell Test Runner
# Usage: .\run_tests.ps1
# Runs the test harness in offline mode (no real API calls)

$ErrorActionPreference = "Stop"

Write-Host "=== E2E API Regression Harness Test Runner ===" -ForegroundColor Cyan
Write-Host "Platform: Windows (PowerShell)`n" -ForegroundColor Cyan

# Get script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $ScriptDir

try {
    # Step 1: Check Python availability
    Write-Host "[1/4] Checking Python availability..." -ForegroundColor Yellow
    $PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $PythonExe) {
        Write-Host "ERROR: Python not found in PATH" -ForegroundColor Red
        exit 1
    }
    Write-Host "  Found Python: $PythonExe" -ForegroundColor Green

    # Step 2: Create/activate virtual environment
    Write-Host "`n[2/4] Setting up virtual environment..." -ForegroundColor Yellow
    $VenvPath = ".\venv"
    if (-not (Test-Path $VenvPath)) {
        Write-Host "  Creating virtual environment..." -ForegroundColor Gray
        & python -m venv $VenvPath
    } else {
        Write-Host "  Virtual environment already exists" -ForegroundColor Gray
    }

    # Activate venv
    $ActivateScript = "$VenvPath\Scripts\Activate.ps1"
    if (-not (Test-Path $ActivateScript)) {
        Write-Host "ERROR: Failed to create virtual environment" -ForegroundColor Red
        exit 1
    }
    & $ActivateScript
    Write-Host "  Activated: $VenvPath" -ForegroundColor Green

    # Step 3: Install dependencies
    Write-Host "`n[3/4] Installing dependencies..." -ForegroundColor Yellow
    $ReqFile = "requirements.txt"
    if (Test-Path $ReqFile) {
        Write-Host "  Installing from $ReqFile..." -ForegroundColor Gray
        & python -m pip install -q -r $ReqFile --disable-pip-version-check
        Write-Host "  Dependencies installed" -ForegroundColor Green
    } else {
        Write-Host "  WARNING: $ReqFile not found, skipping pip install" -ForegroundColor Yellow
    }

    # Step 4: Run tests in offline mode
    Write-Host "`n[4/4] Running regression tests (OFFLINE MODE)..." -ForegroundColor Yellow
    Write-Host "  Running: python e2e_api_regression_harness.py" -ForegroundColor Gray
    Write-Host "`n--- TEST OUTPUT ---" -ForegroundColor Cyan
    
    $env:BASE_URL = ""
    & python e2e_api_regression_harness.py
    $TestExitCode = $LASTEXITCODE
    
    Write-Host "--- END TEST OUTPUT ---`n" -ForegroundColor Cyan

    if ($TestExitCode -eq 0) {
        Write-Host "RESULT: All tests PASSED" -ForegroundColor Green
        Write-Host "`nThe compatibility mapping successfully transforms v2 responses to legacy-safe shapes.`n" -ForegroundColor Green
        exit 0
    } else {
        Write-Host "RESULT: Some tests FAILED (exit code: $TestExitCode)" -ForegroundColor Red
        exit 1
    }

} finally {
    Pop-Location
}
