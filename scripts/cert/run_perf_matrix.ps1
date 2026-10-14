# =============================================================================
# Certification: matriz de performance (cold/warm, cache, rutas degradadas)
# =============================================================================
# Corre la matriz de evidencia de performance sobre el deployment local real
# (Postgres/Redis/Qdrant + providers del .env) y escribe un resumen por corrida.
#
#   pwsh scripts/cert/run_perf_matrix.ps1 -OutDir artifacts/certification/<sha>/perf
#
# Workloads:
#   simple / rag / agentic     -> corpus A/B/C (tests/golden)
#   no-evidence                -> corpus sin evidencia (abstención legítima)
#   retrieval-unavailable      -> Qdrant en puerto muerto (RETRIEVAL_UNAVAILABLE)
#   fallback-provider          -> primario caído (base URL rota) => fallback real
#   cache                      -> probe HTTP (hit/miss + TTFT)
#   load                       -> concurrencia baja/intermedia (1/2/4)
param(
    [string]$OutDir = "",
    [string]$Sha = "",
    [string]$OrgId = "00000000-0000-0000-0000-000000000001",
    [ValidateSet("dev", "ci-parity")][string]$Profile = "dev",
    [int]$SimpleLimit = 8,
    [int]$RagLimit = 10,
    [int]$AgenticLimit = 6,
    [switch]$SkipLoad
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repo
if (-not $Sha) { $Sha = (git rev-parse HEAD).Trim() }
if (-not $OutDir) { $OutDir = Join-Path $repo "artifacts/certification/$Sha/perf" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$env:PYTHONPATH = $repo

# Perfil de configuración de la corrida:
#   dev       -> .env local completo (adaptive active, lazy ingestion on, ...)
#   ci-parity -> valores default de config.py que CI usa (reproducible/comparable)
$profileEnv = @{}
if ($Profile -eq "ci-parity") {
    $profileEnv = @{
        RAG_ADAPTIVE_RAG_MODE         = "off"
        RAG_DECISION_ROUTING_MODE     = "legacy"
        RAG_COGNITIVE_OS_ENABLED      = "off"
        RAG_RAG_LAZY_INGESTION_ENABLED = "false"
        RAG_RAG_LONG_CONTEXT_MODE     = "off"
        RAG_RAG_EVIDENCE_REASONING_MODE = "off"
    }
}

$noEvidence = Join-Path $OutDir "corpus_no_evidence.json"
@(
    "¿Cuál es el color favorito del CEO de una empresa que no existe en el corpus?",
    "¿Cuánto costó el proyecto secreto Marte-7 en 2087?",
    "¿Quién ganó el torneo interno de ajedrez de 1975 en la sede de Neptuno?"
) | ConvertTo-Json | Set-Content -Path $noEvidence -Encoding utf8

$runs = @()
function Invoke-Run {
    # NOTA: no usar un parametro llamado `Args`: colisiona con la automatica
    # $args de PowerShell y los argumentos se pierden silenciosamente.
    param([string]$Label, [string]$Module, [string[]]$RunArgs, [hashtable]$EnvOverrides = @{})
    $merged = @{}
    foreach ($key in $profileEnv.Keys) { $merged[$key] = $profileEnv[$key] }
    foreach ($key in $EnvOverrides.Keys) { $merged[$key] = $EnvOverrides[$key] }
    $saved = @{}
    foreach ($key in $merged.Keys) {
        $saved[$key] = [Environment]::GetEnvironmentVariable($key)
        [Environment]::SetEnvironmentVariable($key, $merged[$key])
    }
    $started = (Get-Date).ToUniversalTime()
    $log = Join-Path $OutDir "$Label.log"
    if ($Module.EndsWith(".py")) {
        & uv run --frozen --no-sync python $Module @RunArgs 2>&1 | Tee-Object -FilePath $log | Out-Null
    } else {
        & uv run --frozen --no-sync python -m $Module @RunArgs 2>&1 | Tee-Object -FilePath $log | Out-Null
    }
    $code = $LASTEXITCODE
    foreach ($key in $saved.Keys) { [Environment]::SetEnvironmentVariable($key, $saved[$key]) }
    $script:runs += [ordered]@{
        label       = $Label
        module      = $Module
        exit_code   = $code
        started_at  = $started.ToString("o")
        duration_s  = [Math]::Round(((Get-Date).ToUniversalTime() - $started).TotalSeconds, 1)
        log         = $log
        env         = ($merged.Keys | ForEach-Object { "$_=$($merged[$_])" }) -join ";"
    }
    Write-Host "[$Label] exit=$code"
}

# 1-3: corpus A/B/C (cold = primera pasada; warm = segunda pasada del mismo corpus)
Invoke-Run -Label "simple-cold" -Module "src.scripts.perf_traffic" -RunArgs @(
    "--label", "cert-simple-cold", "--org-id", $OrgId, "--queries", "tests/golden/corpus_simple.json",
    "--limit", "$SimpleLimit", "--iterations", "1", "--out-dir", $OutDir)
Invoke-Run -Label "simple-warm" -Module "src.scripts.perf_traffic" -RunArgs @(
    "--label", "cert-simple-warm", "--org-id", $OrgId, "--queries", "tests/golden/corpus_simple.json",
    "--limit", "$SimpleLimit", "--iterations", "1", "--out-dir", $OutDir)
Invoke-Run -Label "rag-warm" -Module "src.scripts.perf_traffic" -RunArgs @(
    "--label", "cert-rag-warm", "--org-id", $OrgId, "--queries", "tests/golden/corpus_rag.json",
    "--limit", "$RagLimit", "--iterations", "1", "--out-dir", $OutDir)
Invoke-Run -Label "agentic-warm" -Module "src.scripts.perf_traffic" -RunArgs @(
    "--label", "cert-agentic-warm", "--org-id", $OrgId, "--queries", "tests/golden/corpus_agentic.json",
    "--limit", "$AgenticLimit", "--iterations", "1", "--out-dir", $OutDir)

# 4: no-evidence (abstención legítima)
Invoke-Run -Label "no-evidence" -Module "src.scripts.perf_traffic" -RunArgs @(
    "--label", "cert-no-evidence", "--org-id", $OrgId, "--queries", $noEvidence,
    "--limit", "3", "--iterations", "1", "--out-dir", $OutDir)

# 5: retrieval unavailable (Qdrant en puerto muerto)
Invoke-Run -Label "retrieval-unavailable" -Module "src.scripts.perf_traffic" -RunArgs @(
    "--label", "cert-retrieval-unavailable", "--org-id", $OrgId, "--queries", "tests/golden/corpus_simple.json",
    "--limit", "3", "--iterations", "1", "--out-dir", $OutDir) -EnvOverrides @{
    RAG_QDRANT_PORT = "6399"
}

# 6: fallback real de provider (primario inaccesible)
Invoke-Run -Label "fallback-provider" -Module "src.scripts.perf_traffic" -RunArgs @(
    "--label", "cert-fallback-provider", "--org-id", $OrgId, "--queries", "tests/golden/corpus_simple.json",
    "--limit", "3", "--iterations", "1", "--out-dir", $OutDir) -EnvOverrides @{
    RAG_LITELLM_API_BASE = "http://127.0.0.1:9/v1"
}

# 7: cache + TTFT por HTTP
Invoke-Run -Label "http-probe" -Module "scripts/cert/http_probe.py" -RunArgs @(
    "--out", (Join-Path $OutDir "http-probe.json"))

# 8: load (concurrencia baja e intermedia)
if (-not $SkipLoad) {
    Invoke-Run -Label "load" -Module "src.scripts.load_test" -RunArgs @(
        "--label", "cert-load", "--org-id", $OrgId, "--queries", "tests/golden/corpus_simple.json",
        "--concurrency", "1,2,4", "--requests", "3", "--out-dir", $OutDir)
}

$summary = [ordered]@{
    schema     = "zent.cert.perf-matrix/1"
    git_sha    = $Sha
    git_dirty  = [bool](git status --porcelain)
    profile    = $Profile
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    out_dir    = $OutDir
    runs       = $runs
}
$summary | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $OutDir "matrix.json") -Encoding utf8
Write-Host "matrix: $(Join-Path $OutDir 'matrix.json')"
