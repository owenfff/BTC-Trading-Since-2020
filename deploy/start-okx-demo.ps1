param(
    [ValidateSet("readonly", "demo")]
    [string]$Mode = "readonly",
    [switch]$Once,
    [switch]$ConfirmTestnet,
    [string]$PythonPath = "",
    [switch]$ForgetCredentials
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$oldPythonPath = $env:PYTHONPATH
$oldKey = [Environment]::GetEnvironmentVariable("OKX_DEMO_API_KEY", "Process")
$oldSecret = [Environment]::GetEnvironmentVariable("OKX_DEMO_API_SECRET", "Process")
$oldPassphrase = [Environment]::GetEnvironmentVariable("OKX_DEMO_API_PASSPHRASE", "Process")
$credentialStorePath = Join-Path $repo "quantoutputsokx_demo_credentials.json"
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
        if (-not $stored.api_key -or -not $stored.api_secret -or -not $stored.passphrase) { return $null }
        return @{ ApiKey = ConvertTo-PlainText ([string]$stored.api_key); ApiSecret = ConvertTo-PlainText ([string]$stored.api_secret); Passphrase = ConvertTo-PlainText ([string]$stored.passphrase) }
    } catch { throw "Local OKX DPAPI credential store could not be decrypted for this Windows user. Use -ForgetCredentials to replace it." }
}

function Save-DpapiCredentials([string]$Path, [string]$ApiKey, [string]$ApiSecret, [string]$Passphrase) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $payload = @{ api_key = ConvertTo-DpapiText $ApiKey; api_secret = ConvertTo-DpapiText $ApiSecret; passphrase = ConvertTo-DpapiText $Passphrase } | ConvertTo-Json
    Set-Content -LiteralPath $Path -Value $payload -Encoding UTF8
}

try {
    if (-not $PythonPath) {
        $candidates = @((Join-Path $env:USERPROFILE ".cachecodex-runtimescodex-primary-runtimedependenciespythonpython.exe"), (Join-Path $env:LOCALAPPDATA "ProgramsPythonPython311python.exe"), (Join-Path $env:LOCALAPPDATA "ProgramsPythonPython313python.exe"))
        $PythonPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
    if (-not $PythonPath) { $PythonPath = (Get-Command python.exe -ErrorAction Stop).Source }
    if (-not (Test-Path -LiteralPath $PythonPath)) { throw "Python executable not found: $PythonPath" }
    if ($ForgetCredentials -and (Test-Path -LiteralPath $credentialStorePath)) { Remove-Item -LiteralPath $credentialStorePath -Force }
    $stored = if (-not $ForgetCredentials) { Read-DpapiCredentials $credentialStorePath } else { $null }
    if (-not $env:OKX_DEMO_API_KEY -and $stored) { $env:OKX_DEMO_API_KEY = $stored.ApiKey }
    if (-not $env:OKX_DEMO_API_SECRET -and $stored) { $env:OKX_DEMO_API_SECRET = $stored.ApiSecret }
    if (-not $env:OKX_DEMO_API_PASSPHRASE -and $stored) { $env:OKX_DEMO_API_PASSPHRASE = $stored.Passphrase }
    if (-not $env:OKX_DEMO_API_KEY) { $env:OKX_DEMO_API_KEY = Read-LocalSecret "OKX Demo API key (local only; raw ASCII)" }
    if (-not $env:OKX_DEMO_API_SECRET) { $env:OKX_DEMO_API_SECRET = Read-LocalSecret "OKX Demo API secret (local only; raw ASCII)" }
    if (-not $env:OKX_DEMO_API_PASSPHRASE) { $env:OKX_DEMO_API_PASSPHRASE = Read-LocalSecret "OKX Demo passphrase (local only; raw ASCII)" }
    Assert-AsciiCredential "OKX_DEMO_API_KEY" $env:OKX_DEMO_API_KEY
    Assert-AsciiCredential "OKX_DEMO_API_SECRET" $env:OKX_DEMO_API_SECRET
    Assert-AsciiCredential "OKX_DEMO_API_PASSPHRASE" $env:OKX_DEMO_API_PASSPHRASE
    if (-not $stored -or $ForgetCredentials) { Save-DpapiCredentials $credentialStorePath $env:OKX_DEMO_API_KEY $env:OKX_DEMO_API_SECRET $env:OKX_DEMO_API_PASSPHRASE }
    $env:PYTHONPATH = "$repo;$repo\quant\src"
    & $PythonPath -m quant_bot preflight --venue okx-demo
    if ($LASTEXITCODE -ne 0) { throw "OKX Demo preflight failed with exit code $LASTEXITCODE" }
    $runArgs = @("-m", "quant_bot", "run", "--venue", "okx-demo", "--mode", "testnet", "--symbols", "auto", "--poll-seconds", "60")
    if ($Once) { $runArgs += "--once" }
    if ($Mode -eq "demo") {
        if (-not $ConfirmTestnet) { throw "Demo order mode requires -ConfirmTestnet" }
        $runArgs += "--enable-orders"; $runArgs += "--confirm-testnet"
    }
    & $PythonPath @runArgs
    $exitCode = $LASTEXITCODE
} catch { Write-Error $_; $exitCode = 1 }
finally {
    if ($null -eq $oldPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
    if ($null -eq $oldKey) { Remove-Item Env:OKX_DEMO_API_KEY -ErrorAction SilentlyContinue } else { $env:OKX_DEMO_API_KEY = $oldKey }
    if ($null -eq $oldSecret) { Remove-Item Env:OKX_DEMO_API_SECRET -ErrorAction SilentlyContinue } else { $env:OKX_DEMO_API_SECRET = $oldSecret }
    if ($null -eq $oldPassphrase) { Remove-Item Env:OKX_DEMO_API_PASSPHRASE -ErrorAction SilentlyContinue } else { $env:OKX_DEMO_API_PASSPHRASE = $oldPassphrase }
}
exit $exitCode
