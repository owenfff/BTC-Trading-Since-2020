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
$oldKey = [Environment]::GetEnvironmentVariable("BYBIT_DEMO_API_KEY", "Process")
$oldSecret = [Environment]::GetEnvironmentVariable("BYBIT_DEMO_API_SECRET", "Process")
$temporaryCredentials = $false
$credentialStorePath = Join-Path $repo "quant\outputs\bybit_demo_credentials.json"
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

function ConvertTo-PlainText([string]$EncryptedValue) {
    $secure = ConvertTo-SecureString -String $EncryptedValue
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function ConvertTo-DpapiText([string]$PlainValue) {
    $secure = ConvertTo-SecureString -String $PlainValue -AsPlainText -Force
    return ConvertFrom-SecureString -SecureString $secure
}

function Assert-AsciiCredential([string]$Name, [string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { throw "$Name is empty" }
    foreach ($character in $Value.ToCharArray()) {
        if ([int][char]$character -gt 127) {
            throw "$Name contains non-ASCII characters. Paste the raw Bybit credential, not formatted text or smart quotes."
        }
    }
}

function Read-DpapiCredentials([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        $stored = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
        if (-not $stored.api_key -or -not $stored.api_secret) { return $null }
        return @{
            ApiKey = ConvertTo-PlainText ([string]$stored.api_key)
            ApiSecret = ConvertTo-PlainText ([string]$stored.api_secret)
        }
    } catch {
        throw "Local DPAPI credential store could not be decrypted for this Windows user. Use -ForgetCredentials to replace it."
    }
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
    if (-not $PythonPath) {
        $pythonCommand = Get-Command python.exe -ErrorAction Stop
        $PythonPath = $pythonCommand.Source
    }
    if (-not (Test-Path -LiteralPath $PythonPath)) {
        throw "Python executable not found: $PythonPath"
    }

    if ($ForgetCredentials -and (Test-Path -LiteralPath $credentialStorePath)) {
        Remove-Item -LiteralPath $credentialStorePath -Force
        Write-Host "[quant] local DPAPI credentials forgotten"
    }
    $storedCredentials = if (-not $ForgetCredentials) { Read-DpapiCredentials $credentialStorePath } else { $null }
    if (-not $env:BYBIT_DEMO_API_KEY -and $storedCredentials) { $env:BYBIT_DEMO_API_KEY = $storedCredentials.ApiKey }
    if (-not $env:BYBIT_DEMO_API_SECRET -and $storedCredentials) { $env:BYBIT_DEMO_API_SECRET = $storedCredentials.ApiSecret }
    if (-not $env:BYBIT_DEMO_API_KEY) {
        $env:BYBIT_DEMO_API_KEY = Read-LocalSecret "Bybit Demo API key (local only; raw ASCII)"
        $temporaryCredentials = $true
    }
    if (-not $env:BYBIT_DEMO_API_SECRET) {
        $env:BYBIT_DEMO_API_SECRET = Read-LocalSecret "Bybit Demo API secret (local only; raw ASCII)"
        $temporaryCredentials = $true
    }
    Assert-AsciiCredential "BYBIT_DEMO_API_KEY" $env:BYBIT_DEMO_API_KEY
    Assert-AsciiCredential "BYBIT_DEMO_API_SECRET" $env:BYBIT_DEMO_API_SECRET
    if (-not $storedCredentials -or $ForgetCredentials) {
        Save-DpapiCredentials $credentialStorePath $env:BYBIT_DEMO_API_KEY $env:BYBIT_DEMO_API_SECRET
        Write-Host "[quant] credentials saved in Windows-user DPAPI store"
    }

    $env:PYTHONPATH = "$repo;$repo\quant\src"
    Write-Host "[quant] repository: $repo"
    Write-Host "[quant] mode: $Mode"
    Write-Host "[quant] credentials: Windows-user DPAPI + process-local only"

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
    if ($temporaryCredentials) { Write-Host "[quant] plaintext credentials cleared from this PowerShell process" }
}

exit $exitCode
