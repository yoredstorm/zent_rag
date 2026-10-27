#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Corre la suite completa de pytest y deja JUnit + durations.

.DESCRIPTION
    Pensado para verificación pre-commit o diagnóstico de lentitud. No usa -x:
    muestra todos los fallos. El timeout por test sale de pyproject.toml.
    Escribe `artifacts/junit-tests-local.xml` y los 30 tests más lentos.

    Por defecto excluye `tests/certification/workflows`: esos tests necesitan
    un entorno sin proveedor LLM real y CI los corre en un job aparte. Usa
    `-WithCertification` para incluirlos.

.EXAMPLE
    pwsh scripts/test-full.ps1
    pwsh scripts/test-full.ps1 -WithCertification
    pwsh scripts/test-full.ps1 tests/test_architecture.py tests/test_db_lifecycle.py
#>
[CmdletBinding()]
param(
    [switch]$WithCertification,

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

$Artifacts = Join-Path $RepoRoot 'artifacts'
New-Item -ItemType Directory -Force -Path $Artifacts | Out-Null

$Targets = if (-not $Extra -or $Extra.Count -eq 0) { @('tests/') } else { $Extra }
$PytestArgs = @('-m', 'pytest') + $Targets
if (-not $WithCertification) {
    $PytestArgs += '--ignore=tests/certification/workflows'
}
$PytestArgs += @(
    '-q',
    '--no-header',
    '--durations=30',
    '--junitxml=artifacts/junit-tests-local.xml'
)

Push-Location $RepoRoot
try {
    & $Python @PytestArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
