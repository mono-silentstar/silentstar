param(
    [string]$PythonBin = "",
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$WorkerScript = Join-Path $RepoRoot "worker\bridge_worker.py"

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $RepoRoot "worker\config.json"
}

if (-not (Test-Path -LiteralPath $WorkerScript)) {
    throw "silentstar-worker: worker script not found at $WorkerScript"
}
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "silentstar-worker: config file not found at $ConfigPath"
}

$usePyLauncher = $false
if ([string]::IsNullOrWhiteSpace($PythonBin)) {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        $PythonBin = $py.Source
        $usePyLauncher = $true
    } else {
        $python = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($null -eq $python) {
            throw "silentstar-worker: python not found. Set -PythonBin."
        }
        $PythonBin = $python.Source
    }
}

Write-Host "silentstar-worker: repo root $RepoRoot"
Write-Host "silentstar-worker: config $ConfigPath"
Write-Host "silentstar-worker: python $PythonBin"

Push-Location $RepoRoot
try {
    if ($usePyLauncher) {
        & $PythonBin -3 $WorkerScript --config $ConfigPath
    } else {
        & $PythonBin $WorkerScript --config $ConfigPath
    }
} finally {
    Pop-Location
}
