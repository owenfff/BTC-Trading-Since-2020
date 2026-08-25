param(
    [string]$RemoteUser = "ubuntu",
    [string]$RemoteHost = "111.231.25.250",
    [string]$RemoteRoot = "/home/ubuntu/apps/btc-current"
)

$ErrorActionPreference = "Stop"
$bashCandidates = @(
    "C:\Program Files\Git\usr\bin\bash.exe",
    "C:\Program Files\Git\bin\bash.exe"
)
$bash = $bashCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $bash) {
    $bashCommand = Get-Command bash.exe -ErrorAction SilentlyContinue
    if ($bashCommand) { $bash = $bashCommand.Source }
}
if (-not $bash) { throw "Git Bash is required for the resumable SSH sync script." }

$oldRemoteUser = $env:REMOTE_USER
$oldRemoteHost = $env:REMOTE_HOST
$oldRemoteRoot = $env:REMOTE_ROOT
try {
    $env:REMOTE_USER = $RemoteUser
    $env:REMOTE_HOST = $RemoteHost
    $env:REMOTE_ROOT = $RemoteRoot
    & $bash (Join-Path $PSScriptRoot "sync-shanghai-panel.sh")
    if ($LASTEXITCODE -ne 0) { throw "Shanghai panel sync failed with exit code $LASTEXITCODE" }
}
finally {
    if ($null -eq $oldRemoteUser) { Remove-Item Env:REMOTE_USER -ErrorAction SilentlyContinue } else { $env:REMOTE_USER = $oldRemoteUser }
    if ($null -eq $oldRemoteHost) { Remove-Item Env:REMOTE_HOST -ErrorAction SilentlyContinue } else { $env:REMOTE_HOST = $oldRemoteHost }
    if ($null -eq $oldRemoteRoot) { Remove-Item Env:REMOTE_ROOT -ErrorAction SilentlyContinue } else { $env:REMOTE_ROOT = $oldRemoteRoot }
}
