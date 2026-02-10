param(
    [string]$PhpBin = "",
    [string]$PythonBin = "",
    [string]$WorkerConfig = "",
    [string]$HostAddress = "",
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartWeb = Join-Path $ScriptDir "silentstar-start.ps1"
$StartWorker = Join-Path $ScriptDir "silentstar-worker-start.ps1"

if (-not (Test-Path -LiteralPath $StartWeb)) {
    throw "silentstar: web start script not found at $StartWeb"
}
if (-not (Test-Path -LiteralPath $StartWorker)) {
    throw "silentstar: worker start script not found at $StartWorker"
}

$webArgs = @()
if (-not [string]::IsNullOrWhiteSpace($PhpBin)) { $webArgs += @("-PhpBin", $PhpBin) }
if (-not [string]::IsNullOrWhiteSpace($HostAddress)) { $webArgs += @("-HostAddress", $HostAddress) }
if ($Port -gt 0) { $webArgs += @("-Port", "$Port") }
$webArgs += @("-NoPortCheck")

Write-Host "silentstar: launching web service..."
& $StartWeb @webArgs

Write-Host "silentstar: launching worker..."
$workerArgs = @()
if (-not [string]::IsNullOrWhiteSpace($PythonBin)) { $workerArgs += @("-PythonBin", $PythonBin) }
if (-not [string]::IsNullOrWhiteSpace($WorkerConfig)) { $workerArgs += @("-ConfigPath", $WorkerConfig) }
& $StartWorker @workerArgs
