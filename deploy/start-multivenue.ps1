param(
    [ValidateSet("readonly", "testnet")]
    [string]$Mode = "readonly",
    [switch]$Once,
    [switch]$ConfirmTestnet,
    [switch]$AllowSpotApproximation,
    [string]$PythonPath = "",
    [switch]$ForgetCredentials
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$oldPythonPath = $env:PYTHONPATH
$oldValues = @{
    OKX_DEMO_API_KEY = [Environment]::GetEnvironmentVariable("OKX_DEMO_API_KEY", "Process")
    OKX_DEMO_API_SECRET = [Environment]::GetEnvironmentVariable("OKX_DEMO_API_SECRET", "Process")
    OKX_DEMO_API_PASSPHRASE = [Environment]::GetEnvironmentVariable("OKX_DEMO_API_PASSPHRASE", "Process")
    BINANCE_TESTNET_API_KEY = [Environment]::GetEnvironmentVariable("BINANCE_TESTNET_API_KEY", "Process")
    BINANCE_TESTNET_API_SECRET = [Environment]::GetEnvironmentVariable("BINANCE_TESTNET_API_SECRET", "Process")
}
$okxStorePath = Join-Path $repo "quant\outputs\okx_demo_credentials.json"
$binanceStorePath = Join-Path $repo "quant\outputs\binance_testnet_credentials.json"
$exitCode = 1

function Read-LocalSecret([string]$Prompt) {
    $secure = Read-Host -Prompt $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

function ConvertTo-PlainText([string]$EncryptedValue) {
    $secure = ConvertTo-SecureString -String $EncryptedValue
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

function ConvertTo-DpapiText([string]$PlainValue) {
    $secure = ConvertTo-SecureString -String $PlainValue -AsPlainText -Force
    return ConvertFrom-SecureString -SecureString $secure
}

function Assert-AsciiCredential([string]$Name, [string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { throw "$Name is empty" }
    foreach ($character in $Value.ToCharArray()) {
        if ([int][char]$character -gt 127) { throw "$Name contains non-ASCII characters. Use the raw credential." }
    }
}

function Read-DpapiObject([string]$Path, [string[]]$Fields) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        $stored = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
        foreach ($field in $Fields) {
            if (-not $stored.$field) { return $null }
        }
        $result = @{}
        foreach ($field in $Fields) { $result[$field] = ConvertTo-PlainText ([string]$stored.$field) }
        return $result
    } catch { throw "Local DPAPI credential store could not be decrypted for this Windows user. Use -ForgetCredentials to replace it." }
}

function Save-DpapiObject([string]$Path, [hashtable]$Values) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $encrypted = @{}
    foreach ($key in $Values.Keys) { $encrypted[$key] = ConvertTo-DpapiText ([string]$Values[$key]) }
    $encrypted | ConvertTo-Json | Set-Content -LiteralPath $Path -Encoding UTF8
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
    if (-not $PythonPath) { $PythonPath = (Get-Command python.exe -ErrorAction Stop).Source }
    if (-not (Test-Path -LiteralPath $PythonPath)) { throw "Python executable not found: $PythonPath" }

    if ($ForgetCredentials) {
        foreach ($path in @($okxStorePath, $binanceStorePath)) {
            if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
        }
    }

    $okx = if (-not $ForgetCredentials) { Read-DpapiObject $okxStorePath @("api_key", "api_secret", "passphrase") } else { $null }
    if (-not $env:OKX_DEMO_API_KEY -and $okx) { $env:OKX_DEMO_API_KEY = $okx.api_key }
    if (-not $env:OKX_DEMO_API_SECRET -and $okx) { $env:OKX_DEMO_API_SECRET = $okx.api_secret }
    if (-not $env:OKX_DEMO_API_PASSPHRASE -and $okx) { $env:OKX_DEMO_API_PASSPHRASE = $okx.passphrase }
    if (-not $env:OKX_DEMO_API_KEY) { $env:OKX_DEMO_API_KEY = Read-LocalSecret "OKX Demo API key (local only; raw ASCII)" }
    if (-not $env:OKX_DEMO_API_SECRET) { $env:OKX_DEMO_API_SECRET = Read-LocalSecret "OKX Demo API secret (local only; raw ASCII)" }
    if (-not $env:OKX_DEMO_API_PASSPHRASE) { $env:OKX_DEMO_API_PASSPHRASE = Read-LocalSecret "OKX Demo passphrase (local only; raw ASCII)" }
    Assert-AsciiCredential "OKX_DEMO_API_KEY" $env:OKX_DEMO_API_KEY
    Assert-AsciiCredential "OKX_DEMO_API_SECRET" $env:OKX_DEMO_API_SECRET
    Assert-AsciiCredential "OKX_DEMO_API_PASSPHRASE" $env:OKX_DEMO_API_PASSPHRASE
    if (-not $okx -or $ForgetCredentials) {
        Save-DpapiObject $okxStorePath @{ api_key = $env:OKX_DEMO_API_KEY; api_secret = $env:OKX_DEMO_API_SECRET; passphrase = $env:OKX_DEMO_API_PASSPHRASE }
    }

    $binance = if (-not $ForgetCredentials) { Read-DpapiObject $binanceStorePath @("api_key", "api_secret") } else { $null }
    if (-not $env:BINANCE_TESTNET_API_KEY -and $binance) { $env:BINANCE_TESTNET_API_KEY = $binance.api_key }
    if (-not $env:BINANCE_TESTNET_API_SECRET -and $binance) { $env:BINANCE_TESTNET_API_SECRET = $binance.api_secret }
    if (-not $env:BINANCE_TESTNET_API_KEY) { $env:BINANCE_TESTNET_API_KEY = Read-LocalSecret "Binance Spot Testnet API key (local only; raw ASCII)" }
    if (-not $env:BINANCE_TESTNET_API_SECRET) { $env:BINANCE_TESTNET_API_SECRET = Read-LocalSecret "Binance Spot Testnet API secret (local only; raw ASCII)" }
    Assert-AsciiCredential "BINANCE_TESTNET_API_KEY" $env:BINANCE_TESTNET_API_KEY
    Assert-AsciiCredential "BINANCE_TESTNET_API_SECRET" $env:BINANCE_TESTNET_API_SECRET
    if (-not $binance -or $ForgetCredentials) {
        Save-DpapiObject $binanceStorePath @{ api_key = $env:BINANCE_TESTNET_API_KEY; api_secret = $env:BINANCE_TESTNET_API_SECRET }
    }

    if ($Mode -eq "testnet") {
        if (-not $ConfirmTestnet) { throw "Testnet order mode requires -ConfirmTestnet" }
        if (-not $AllowSpotApproximation) { throw "Binance Spot behavioral approximation requires -AllowSpotApproximation" }
    }

    $env:PYTHONPATH = "$repo;$repo\quant\src"
    $runArgs = @("-m", "quant_bot", "run-all", "--mode", "testnet", "--venues", "okx-demo,binance-spot-testnet", "--symbols", "auto", "--poll-seconds", "60", "--allow-spot-approximation")
    if ($Once) { $runArgs += "--once" }
    if ($Mode -eq "testnet") {
        $runArgs += "--enable-orders"; $runArgs += "--confirm-testnet"
    }
    & $PythonPath @runArgs
    $exitCode = $LASTEXITCODE
} catch { Write-Error $_; $exitCode = 1 }
finally {
    if ($null -eq $oldPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
    foreach ($name in $oldValues.Keys) {
        if ($null -eq $oldValues[$name]) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue } else { Set-Item "Env:$name" $oldValues[$name] }
    }
}
exit $exitCode
