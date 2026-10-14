# =============================================================================
# Certification: suite con entorno de paridad CI (sin tocar `.env`).
# =============================================================================
# Replica el entorno del job `test` de .github/workflows/ci.yml como variables
# de proceso (las env vars tienen prioridad sobre `.env` en pydantic-settings).
# El `.env` local NO se modifica: el script es seguro para correr en paralelo
# con otros procesos de certificación.
#
#   pwsh scripts/cert/run_ci_parity_suite.ps1 -Label invariants -Database rag_cert `
#        -Targets "tests/test_architecture.py","tests/test_authority_ownership.py"
#   pwsh scripts/cert/run_ci_parity_suite.ps1 -Label full-suite -Database rag_cert -Targets "tests/"
#
# Evidencia: <OutDir>/<Label>.evidence.json + junit-<Label>.xml + pytest-<Label>.log
param(
    [string]$Label = "suite",
    [string]$Database = "",
    [string[]]$Targets = @("tests/"),
    [string]$OutDir = "",
    [string[]]$ExtraArgs = @(),
    [string]$Sha = ""
)
$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repo
if (-not $Sha) { $Sha = (git rev-parse HEAD).Trim() }
if (-not $OutDir) { $OutDir = Join-Path $repo "artifacts/certification/$Sha/$Label" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# --- Paridad CI (.github/workflows/ci.yml, job `test`) -----------------------
$env:RAG_ENVIRONMENT = "development"
$env:RAG_LOG_LEVEL = "INFO"
$env:RAG_POSTGRES_HOST = "127.0.0.1"
$env:RAG_POSTGRES_PORT = "5432"
$env:RAG_POSTGRES_USER = "rag_user"
$env:RAG_POSTGRES_DB = if ($Database) { $Database } else { "rag_platform" }
$env:RAG_REDIS_URL = $env:RAG_REDIS_URL
$env:RAG_QDRANT_HOST = "127.0.0.1"
$env:RAG_QDRANT_PORT = "6333"
$env:RAG_BILLING_ENABLED = "false"
$env:RAG_SEED_DEMO_DATA = "true"
$env:RAG_LITELLM_DEFAULT_MODEL = "gpt-4o"
$env:RAG_DECISION_ROUTING_MODE = "legacy"
$env:RAG_ADAPTIVE_RAG_MODE = "off"
$env:RAG_COGNITIVE_OS_ENABLED = "off"
$env:PYTHONPATH = $repo

$secretNames = @(
    "RAG_POSTGRES_PASSWORD", "RAG_LITELLM_API_KEY", "RAG_GATEWAY_FALLBACK_API_KEY",
    "RAG_EMBEDDING_FALLBACK_API_KEY", "RAG_PORTAL_SESSION_KEY", "RAG_PORTAL_DEV_PASSWORD",
    "RAG_CONNECTOR_SECRETS_KEY", "METRICS_TOKEN", "RAG_QDRANT_API_KEY"
)
$fingerprintLines = $secretNames | ForEach-Object {
    $value = [Environment]::GetEnvironmentVariable($_)
    if ($null -eq $value) { "$_=<unset>" } else { "$_=<redacted:$($value.Length)>" }
}
$fingerprintLines += @(
    "RAG_ENVIRONMENT=development", "RAG_POSTGRES_DB=$($env:RAG_POSTGRES_DB)",
    "RAG_BILLING_ENABLED=false", "RAG_SEED_DEMO_DATA=true",
    "RAG_LITELLM_DEFAULT_MODEL=gpt-4o", "RAG_DECISION_ROUTING_MODE=legacy",
    "RAG_ADAPTIVE_RAG_MODE=off", "RAG_COGNITIVE_OS_ENABLED=off"
)
$fingerprintPath = Join-Path $OutDir "env-fingerprint.txt"
$fingerprintLines | Set-Content -Path $fingerprintPath -Encoding utf8
$fingerprintHash = (Get-FileHash $fingerprintPath -Algorithm SHA256).Hash

$junit = Join-Path $OutDir "junit-$Label.xml"
$log = Join-Path $OutDir "pytest-$Label.log"
$evidencePath = Join-Path $OutDir "$Label.evidence.json"

$started = (Get-Date).ToUniversalTime()
$args = @("run", "--frozen", "--no-sync", "pytest") + $Targets + @(
    "-q", "--tb=short", "--timeout=300", "--junitxml=$junit"
) + $ExtraArgs
& uv @args 2>&1 | Tee-Object -FilePath $log
$exitCode = $LASTEXITCODE
$finished = (Get-Date).ToUniversalTime()

$evidence = [ordered]@{
    schema                    = "zent.cert.suite-run/2"
    generated_by              = "scripts/cert/run_ci_parity_suite.ps1"
    label                     = $Label
    git_sha                   = $Sha
    git_branch                = (git rev-parse --abbrev-ref HEAD).Trim()
    git_dirty                 = [bool](git status --porcelain)
    environment               = "local-ci-parity"
    database                  = $env:RAG_POSTGRES_DB
    configuration             = "env vars con los valores del job `test` de CI (sin tocar .env)"
    config_fingerprint_sha256 = $fingerprintHash
    command                   = "uv " + ($args -join " ")
    python                    = (& .\.venv\Scripts\python.exe -c "import sys; print(sys.version.split()[0])")
    uv                        = ((uv --version) -split ' ')[1]
    started_at                = $started.ToString("o")
    finished_at               = $finished.ToString("o")
    duration_seconds          = [Math]::Round(($finished - $started).TotalSeconds, 1)
    exit_code                 = $exitCode
    result                    = if ($exitCode -eq 0) { "pass" } else { "fail" }
    junit                     = $junit
    log                       = $log
}
$evidence | ConvertTo-Json -Depth 4 | Set-Content -Path $evidencePath -Encoding utf8
Write-Host "evidence: $evidencePath"
Write-Host "exit=$exitCode"
exit $exitCode
