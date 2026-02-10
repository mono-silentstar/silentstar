param(
    [ValidateSet("Startup", "Logon")]
    [string]$Mode = "Logon",
    [string]$WebTaskName = "silentstar-web",
    [string]$WorkerTaskName = "silentstar-worker"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallWeb = Join-Path $ScriptDir "install-autostart-windows.ps1"
$InstallWorker = Join-Path $ScriptDir "install-worker-autostart-windows.ps1"

if (-not (Test-Path -LiteralPath $InstallWeb)) {
    throw "silentstar: missing $InstallWeb"
}
if (-not (Test-Path -LiteralPath $InstallWorker)) {
    throw "silentstar: missing $InstallWorker"
}

Write-Host "silentstar: installing web task..."
& $InstallWeb -Mode $Mode -TaskName $WebTaskName

Write-Host "silentstar: installing worker task..."
& $InstallWorker -Mode $Mode -TaskName $WorkerTaskName

Write-Host "silentstar: all autostart tasks installed."
