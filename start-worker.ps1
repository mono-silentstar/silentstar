# Start the silentstar bridge worker.
# Run from anywhere — it finds its own way home.

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

Write-Host "starting silentstar worker..."

# Use venv if it exists, otherwise system python
$venvPython = Join-Path $scriptDir ".venv/Scripts/python.exe"
if (Test-Path $venvPython) {
    & $venvPython worker/worker.py --config worker/config.json
} else {
    python worker/worker.py --config worker/config.json
}
