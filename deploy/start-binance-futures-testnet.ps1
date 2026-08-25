param(
    [ValidateSet("readonly", "testnet")]
    [string]$Mode = "readonly",
    [switch]$Once,
    [switch]$ConfirmTestnet,
    [string]$PythonPath = "",
    [switch]$ForgetCredentials
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$oldPythonPath = $env:PYTHONPATH
$oldKey = [Environment]::GetEnvironmentVariable("BINANCE_FUTURES_TESTNET_API_KEY", "Process")
$oldSecret = [Environment]::GetEnvironmentVariable("BINANCE_FUTURES_TESTNET_API_SECRET", "Process")
$credentialStorePath = Join-Path $repo "quant\outputs\binance_futures_testnet_credentials.json"
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

function Read-DpapiCredentials([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        $stored = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
        if (-not $stored.api_key -or -not $stored.api_secret) { return $null }
        return @{ ApiKey = ConvertTo-PlainText ([string]$stored.api_key); ApiSecret = ConvertTo-PlainText ([string]$stored.api_secret) }
    } catch { throw "Local Binance Futures DPAPI credential store could not be decrypted for this Windows user. Use -ForgetCredentials to replace it." }
}

function Save-DpapiCredentials([string]$Path, [string]$ApiKey, [string]$ApiSecret) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $payload = @{ api_key = ConvertTo-DpapiText $ApiKey; api_secret = ConvertTo-DpapiText $ApiSecret } | ConvertTo-Json
    Set-Content -LiteralPath $Path -Value $payload -Encoding UTF8
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

    if ($ForgetCredentials -and (Test-Path -LiteralPath $credentialStorePath)) { Remove-Item -LiteralPath $credentialStorePath -Force }
    $stored = if (-not $ForgetCredentials) { Read-DpapiCredentials $credentialStorePath } else { $null }
    if (-not $env:BINANCE_FUTURES_TESTNET_API_KEY -and $stored) { $env:BINANCE_FUTURES_TESTNET_API_KEY = $stored.ApiKey }
    if (-not $env:BINANCE_FUTURES_TESTNET_API_SECRET -and $stored) { $env:BINANCE_FUTURES_TESTNET_API_SECRET = $stored.ApiSecret }
    if (-not $env:BINANCE_FUTURES_TESTNET_API_KEY) { $env:BINANCE_FUTURES_TESTNET_API_KEY = Read-LocalSecret "Binance USDⓈ-M Futures Testnet API key (local only; raw ASCII)" }
    if (-not $env:BINANCE_FUTURES_TESTNET_API_SECRET) { $env:BINANCE_FUTURES_TESTNET_API_SECRET = Read-LocalSecret "Binance USDⓈ-M Futures Testnet API secret (local only; raw ASCII)" }
    Assert-AsciiCredential "BINANCE_FUTURES_TESTNET_API_KEY" $env:BINANCE_FUTURES_TESTNET_API_KEY
    Assert-AsciiCredential "BINANCE_FUTURES_TESTNET_API_SECRET" $env:BINANCE_FUTURES_TESTNET_API_SECRET
    if (-not $stored -or $ForgetCredentials) { Save-DpapiCredentials $credentialStorePath $env:BINANCE_FUTURES_TESTNET_API_KEY $env:BINANCE_FUTURES_TESTNET_API_SECRET }

    $env:PYTHONPATH = "$repo;$repo\quant\src"
    & $PythonPath -m quant_bot preflight --venue binance-futures-testnet
    if ($LASTEXITCODE -ne 0) { throw "Binance Futures Testnet preflight failed with exit code $LASTEXITCODE" }
    $runArgs = @("-m", "quant_bot", "run", "--venue", "binance-futures-testnet", "--mode", "testnet", "--symbols", "auto", "--poll-seconds", "60")
    if ($Once) { $runArgs += "--once" }
    if ($Mode -eq "testnet") {
        if (-not $ConfirmTestnet) { throw "Testnet order mode requires -ConfirmTestnet" }
        $runArgs += "--enable-orders"; $runArgs += "--confirm-testnet"
    }
    & $PythonPath @runArgs
    $exitCode = $LASTEXITCODE
} catch { Write-Error $_; $exitCode = 1 }
finally {
    if ($null -eq $oldPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
    if ($null -eq $oldKey) { Remove-Item Env:BINANCE_FUTURES_TESTNET_API_KEY -ErrorAction SilentlyContinue } else { $env:BINANCE_FUTURES_TESTNET_API_KEY = $oldKey }
    if ($null -eq $oldSecret) { Remove-Item Env:BINANCE_FUTURES_TESTNET_API_SECRET -ErrorAction SilentlyContinue } else { $env:BINANCE_FUTURES_TESTNET_API_SECRET = $oldSecret }
}
exit $exitCode
