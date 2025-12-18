# run_tests.ps1
# One-click test runner for API migration regression tests

$venvDir = "venv"

# Create virtual environment if it doesn't exist
if (!(Test-Path $venvDir)) {
    Write-Host "Creating virtual environment..."
    python -m venv $venvDir
}

# Activate virtual environment
Write-Host "Activating virtual environment..."
& "$venvDir\Scripts\Activate.ps1"

# Install dependencies
Write-Host "Installing dependencies..."
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Run Mode A: RAW_V2 (expect failures showing breakage)
Write-Host "`n=== Running Mode A: RAW_V2 (expecting failures to demonstrate breakage) ==="
python e2e_api_regression_harness.py RAW_V2
if ($LASTEXITCODE -ne 0) {
    Write-Host "Mode A failed as expected (showing breakage). Proceeding to Mode B..."
} else {
    Write-Host "ERROR: Mode A should have failed to show breakage!"
    exit 1
}

# Run Mode B: COMPAT (expect passes after compatibility mapping)
Write-Host "`n=== Running Mode B: COMPAT (expecting passes after mapping) ==="
python e2e_api_regression_harness.py COMPAT
if ($LASTEXITCODE -eq 0) {
    Write-Host "SUCCESS: FAIL-THEN-PASS gate satisfied!"
} else {
    Write-Host "ERROR: Mode B failed!"
    exit 1
}