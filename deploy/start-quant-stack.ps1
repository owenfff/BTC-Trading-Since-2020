param(
    [ValidateSet("readonly", "testnet")]
    [string]$Mode = "readonly",
    [switch]$Once,
    [switch]$ConfirmTestnet,
    [switch]$AllowSpotApproximation,
    [string]$PythonPath = "",
    [int]$DashboardPort = 8080,
    [string]$DashboardHost = "127.0.0.1",
    [switch]$ForgetCredentials
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$dashboardLog = Join-Path $repo "quant\outputs\frontend_dashboard.log"
$dashboardErrorLog = Join-Path $repo "quant\outputs\frontend_dashboard.error.log"
$dashboard = $null

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

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dashboardLog) | Out-Null
    $dashboardArgs = @("frontend/server.py", "--host", $DashboardHost, "--port", [string]$DashboardPort)
    $dashboard = Start-Process -FilePath $PythonPath -ArgumentList $dashboardArgs -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput $dashboardLog -RedirectStandardError $dashboardErrorLog -PassThru
    Write-Host ("[quant] dashboard: http://{0}:{1}" -f $DashboardHost, $DashboardPort)
    Write-Host "[quant] dashboard role: FRONTEND_ONLY"

    $launcher = Join-Path $repo "deploy\start-multivenue.ps1"
    & $launcher -Mode $Mode -Once:$Once -ConfirmTestnet:$ConfirmTestnet -AllowSpotApproximation:$AllowSpotApproximation -PythonPath $PythonPath -ForgetCredentials:$ForgetCredentials
    $exitCode = $LASTEXITCODE
} catch {
    Write-Error $_
    $exitCode = 1
} finally {
    if ($dashboard -and -not $dashboard.HasExited) {
        Stop-Process -Id $dashboard.Id -Force -ErrorAction SilentlyContinue
    }
}
exit $exitCode
