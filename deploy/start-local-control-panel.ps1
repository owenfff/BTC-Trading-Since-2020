param(
    [int]$Port = 8080,
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
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

$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$repo;$repo\quant\src"
    Write-Host "[quant] local control panel: http://127.0.0.1:$Port"
    Write-Host "[quant] credentials are never accepted by the browser; launch opens local PowerShell prompts"
    & $PythonPath (Join-Path $repo "frontend\server.py") --host 127.0.0.1 --port $Port --control
} finally {
    if ($null -eq $oldPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
}
