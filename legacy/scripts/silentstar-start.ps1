param(
    [string]$PhpBin = "",
    [string]$HostAddress = "",
    [int]$Port = 0,
    [switch]$NoPortCheck
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$WebRoot = Join-Path $RepoRoot "web"

if ([string]::IsNullOrWhiteSpace($PhpBin)) {
    if (-not [string]::IsNullOrWhiteSpace($env:PHP_BIN)) {
        $PhpBin = $env:PHP_BIN
    } else {
        $cmd = Get-Command php.exe -ErrorAction SilentlyContinue
        if ($null -eq $cmd) {
            throw "silentstar: php.exe not found. Set -PhpBin or PHP_BIN."
        }
        $PhpBin = $cmd.Source
    }
}

if ([string]::IsNullOrWhiteSpace($HostAddress)) {
    if (-not [string]::IsNullOrWhiteSpace($env:SILENTSTAR_HOST)) {
        $HostAddress = $env:SILENTSTAR_HOST
    } else {
        $HostAddress = "127.0.0.1"
    }
}

if ($Port -le 0) {
    $envPort = 0
    if (-not [string]::IsNullOrWhiteSpace($env:SILENTSTAR_PORT)) {
        [void][int]::TryParse($env:SILENTSTAR_PORT, [ref]$envPort)
    }
    if ($envPort -gt 0) {
        $Port = $envPort
    } else {
        $Port = 8080
    }
}

if (-not (Test-Path -LiteralPath $WebRoot)) {
    throw "silentstar: web root not found at $WebRoot"
}

if (-not $NoPortCheck) {
    $listening = netstat -ano -p TCP | Select-String -SimpleMatch (":" + $Port + " ")
    if ($null -ne $listening -and $listening.Count -gt 0) {
        Write-Host "silentstar: port $Port already has a TCP listener. Skipping launch."
        exit 0
    }
}

$args = @(
    "-S",
    "$HostAddress`:$Port",
    "-t",
    $WebRoot
)

Write-Host "silentstar: starting php server at http://$HostAddress:$Port"
Write-Host "silentstar: repo root $RepoRoot"
Write-Host "silentstar: php $PhpBin"

Start-Process -FilePath $PhpBin -ArgumentList $args -WorkingDirectory $RepoRoot -WindowStyle Hidden | Out-Null
