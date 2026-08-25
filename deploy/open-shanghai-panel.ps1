param(
    [string]$RemoteUser = "ubuntu",
    [string]$RemoteHost = "111.231.25.250",
    [int]$LocalPort = 18080
)

$ErrorActionPreference = "Stop"
$ssh = Get-Command ssh.exe -ErrorAction SilentlyContinue
if (-not $ssh) { throw "OpenSSH client (ssh.exe) is required." }
if ($LocalPort -lt 1024 -or $LocalPort -gt 65535) { throw "LocalPort must be between 1024 and 65535." }

$target = "$RemoteUser@$RemoteHost"
Write-Host "[quant] Shanghai panel: http://127.0.0.1:$LocalPort/"
Write-Host "[quant] tunnel target: $target -> 127.0.0.1:8080"
Write-Host "[quant] exchange credentials never pass through this tunnel command."

& $ssh.Source `
    -N `
    -o ExitOnForwardFailure=yes `
    -o ServerAliveInterval=15 `
    -o ServerAliveCountMax=3 `
    -o PreferredAuthentications=keyboard-interactive,password `
    -L "$LocalPort`:127.0.0.1`:8080" `
    $target
if ($LASTEXITCODE -ne 0) { throw "Shanghai panel tunnel exited with code $LASTEXITCODE" }
