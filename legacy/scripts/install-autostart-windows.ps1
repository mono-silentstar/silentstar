param(
    [ValidateSet("Startup", "Logon")]
    [string]$Mode = "Logon",
    [string]$TaskName = "silentstar",
    [string]$PhpBin = "",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8080
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
    throw "silentstar: this installer is for Windows only."
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartScript = Join-Path $ScriptDir "silentstar-start.ps1"
if (-not (Test-Path -LiteralPath $StartScript)) {
    throw "silentstar: start script not found at $StartScript"
}

if ([string]::IsNullOrWhiteSpace($PhpBin)) {
    if (-not [string]::IsNullOrWhiteSpace($env:PHP_BIN)) {
        $PhpBin = $env:PHP_BIN
    } else {
        $cmd = Get-Command php.exe -ErrorAction SilentlyContinue
        if ($null -eq $cmd) {
            throw "silentstar: php.exe not found. Pass -PhpBin path or set PHP_BIN."
        }
        $PhpBin = $cmd.Source
    }
}

$escapedStart = $StartScript.Replace("'", "''")
$escapedPhp = $PhpBin.Replace("'", "''")
$escapedHost = $HostAddress.Replace("'", "''")
$taskArgs = "-NoProfile -ExecutionPolicy Bypass -File '$escapedStart' -PhpBin '$escapedPhp' -HostAddress '$escapedHost' -Port $Port"

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $taskArgs
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if ($Mode -eq "Startup") {
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).
        IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        throw "silentstar: Startup mode requires admin PowerShell. Re-run as Administrator or use -Mode Logon."
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
    -Description "silentstar autostart task"

Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "silentstar: scheduled task installed."
Write-Host "silentstar: task name: $TaskName"
Write-Host "silentstar: mode: $Mode"
Write-Host "silentstar: launch target: http://$HostAddress:$Port"
