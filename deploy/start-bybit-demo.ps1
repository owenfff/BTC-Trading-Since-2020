param(
    [ValidateSet("readonly", "demo")]
    [string]$Mode = "readonly",
    [switch]$Once,
    [switch]$ConfirmTestnet,
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$oldPythonPath = $env:PYTHONPATH
$oldKey = [Environment]::GetEnvironmentVariable("BYBIT_DEMO_API_KEY", "Process")
$oldSecret = [Environment]::GetEnvironmentVariable("BYBIT_DEMO_API_SECRET", "Process")
$temporaryCredentials = $false
$exitCode = 1

function Read-LocalSecret([string]$Prompt) {
    $secure = Read-Host -Prompt $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

try {
    if (-not $PythonPath) {
        $candidates = @(
            (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe")
        )
        $PythonPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
    if (-not $PythonPath) {
        $pythonCommand = Get-Command python.exe -ErrorAction Stop
        $PythonPath = $pythonCommand.Source
    }
    if (-not (Test-Path -LiteralPath $PythonPath)) {
        throw "Python executable not found: $PythonPath"
    }

    if (-not $env:BYBIT_DEMO_API_KEY) {
        $env:BYBIT_DEMO_API_KEY = Read-LocalSecret "Bybit Demo API key (local only)"
        $temporaryCredentials = $true
    }
    if (-not $env:BYBIT_DEMO_API_SECRET) {
        $env:BYBIT_DEMO_API_SECRET = Read-LocalSecret "Bybit Demo API secret (local only)"
        $temporaryCredentials = $true
    }

    $env:PYTHONPATH = "$repo;$repo\quant\src"
    Write-Host "[quant] repository: $repo"
    Write-Host "[quant] mode: $Mode"
    Write-Host "[quant] credentials: process-local only"

    & $PythonPath -m quant_bot preflight --venue bybit-demo
    if ($LASTEXITCODE -ne 0) {
        throw "Bybit Demo preflight failed with exit code $LASTEXITCODE"
    }

    $runArgs = @("-m", "quant_bot", "run", "--venue", "bybit-demo", "--mode", "testnet", "--symbols", "auto", "--poll-seconds", "60")
    if ($Once) {
        $runArgs += "--once"
    }
    if ($Mode -eq "demo") {
        if (-not $ConfirmTestnet) {
            throw "Demo order mode requires -ConfirmTestnet"
        }
        $runArgs += "--enable-orders"
        $runArgs += "--confirm-testnet"
        Write-Warning "DEMO ORDER MODE ENABLED. This can submit virtual Bybit Demo orders."
    } else {
        Write-Host "[quant] read-only mode: no orders will be submitted"
    }

    & $PythonPath @runArgs
    $exitCode = $LASTEXITCODE
} catch {
    Write-Error $_
    $exitCode = 1
} finally {
    if ($null -eq $oldPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
    if ($null -eq $oldKey) { Remove-Item Env:BYBIT_DEMO_API_KEY -ErrorAction SilentlyContinue } else { $env:BYBIT_DEMO_API_KEY = $oldKey }
    if ($null -eq $oldSecret) { Remove-Item Env:BYBIT_DEMO_API_SECRET -ErrorAction SilentlyContinue } else { $env:BYBIT_DEMO_API_SECRET = $oldSecret }
    if ($temporaryCredentials) { Write-Host "[quant] temporary credentials cleared from this PowerShell process" }
}

exit $exitCode
