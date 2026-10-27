#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Loop rápido de pytest: últimas fallas o archivos indicados.

.DESCRIPTION
    Sin argumentos corre `--lf` (last failed). Con argumentos, los pasa tal cual
    a pytest: archivos, -k, -m, etc. Siempre agrega `-q -x --durations=15`
    para feedback corto; si necesitas otro comportamiento, usa pytest directo.

.EXAMPLE
    pwsh scripts/test-fast.ps1
    pwsh scripts/test-fast.ps1 tests/test_rate_limiter.py
    pwsh scripts/test-fast.ps1 tests/test_http.py -k auth
#>
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Extra
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = if ($IsWindows) {
    Join-Path $RepoRoot '.venv/Scripts/python.exe'
} else {
    Join-Path $RepoRoot '.venv/bin/python'
}
if (-not (Test-Path $Python)) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}

$PytestArgs = @('-m', 'pytest')
if (-not $Extra -or $Extra.Count -eq 0) {
    $PytestArgs += '--lf'
} else {
    $PytestArgs += $Extra
}
$PytestArgs += @('-q', '--no-header', '-x', '--durations=15')

Push-Location $RepoRoot
try {
    & $Python @PytestArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
