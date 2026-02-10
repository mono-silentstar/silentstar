param(
    [ValidateSet("Startup", "Logon")]
    [string]$Mode = "Logon",
    [string]$TaskName = "silentstar-worker",
    [string]$PythonBin = "",
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"

$isWin = $false
try {
    $isWin = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
        [System.Runtime.InteropServices.OSPlatform]::Windows
    )
} catch {
    $isWin = ($env:OS -eq "Windows_NT")
}
if (-not $isWin) {
    throw "silentstar-worker: this installer is for Windows only."
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartScript = Join-Path $ScriptDir "silentstar-worker-start.ps1"
if (-not (Test-Path -LiteralPath $StartScript)) {
    throw "silentstar-worker: start script not found at $StartScript"
}

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $RepoRoot = Split-Path -Parent $ScriptDir
    $ConfigPath = Join-Path $RepoRoot "worker\config.json"
}
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "silentstar-worker: config file not found at $ConfigPath"
}

if ([string]::IsNullOrWhiteSpace($PythonBin)) {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        $PythonBin = $py.Source
    } else {
        $python = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($null -eq $python) {
            throw "silentstar-worker: python not found. Pass -PythonBin."
        }
        $PythonBin = $python.Source
    }
}

$escapedStart = $StartScript.Replace("'", "''")
$escapedPython = $PythonBin.Replace("'", "''")
$escapedConfig = $ConfigPath.Replace("'", "''")
$taskArgs = "-NoProfile -ExecutionPolicy Bypass -File '$escapedStart' -PythonBin '$escapedPython' -ConfigPath '$escapedConfig'"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $taskArgs
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if ($Mode -eq "Startup") {
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).
        IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        throw "silentstar-worker: Startup mode requires admin PowerShell. Re-run as Administrator or use -Mode Logon."
    }
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
} else {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
    $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
}

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 0)

$task = New-ScheduledTask -Action $action -Principal $principal -Trigger $trigger -Settings $settings `
    -Description "silentstar worker autostart task"

Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "silentstar-worker: scheduled task installed."
Write-Host "silentstar-worker: task name: $TaskName"
Write-Host "silentstar-worker: mode: $Mode"
Write-Host "silentstar-worker: config: $ConfigPath"
