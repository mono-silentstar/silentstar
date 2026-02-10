# Start the silentstar bridge worker.
# Run from anywhere — it finds its own way home.

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

Write-Host "starting silentstar worker..."
python worker/worker.py --config worker/config.json
