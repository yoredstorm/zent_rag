# =============================================================================
# Certification: ensayo del procedimiento de rollback (bad release -> undo)
# =============================================================================
# Practica el procedimiento ANTES de necesitarlo, con la imagen certificada:
#   1. arranca la imagen buena contra una DB scratch -> /health OK
#   2. arranca la misma imagen con una config rota (Qdrant en puerto muerto)
#      -> /health degradado (así lo ve la puerta de promoción)
#   3. ejecuta el rollback (reemplaza el contenedor roto por el bueno)
#      -> /health OK, tiempo total medido
#
#   pwsh scripts/cert/rehearse_rollback.ps1 -Image zent-api:cert-<sha> -Database rag_cert_rehearsal
param(
    [string]$Image = "zent-api:cert",
    [string]$Database = "rag_cert_rehearsal",
    [string]$OutDir = "",
    [int]$GoodPort = 8100,
    [int]$BadPort = 8101
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repo
$sha = (git rev-parse HEAD).Trim()
if (-not $OutDir) { $OutDir = Join-Path $repo "artifacts/certification/$sha/rollback" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$common = @(
    "--env-file", ".env",
    "-e", "RAG_POSTGRES_HOST=host.docker.internal",
    "-e", "RAG_QDRANT_HOST=host.docker.internal",
    "-e", "RAG_ENVIRONMENT=development",
    "-e", "RAG_POSTGRES_DB=$Database"
)
$redisUrl = (Select-String -Path .env -Pattern "^RAG_REDIS_URL=(.*)$").Matches.Groups[1].Value
$redisUrl = $redisUrl -replace "127\.0\.0\.1", "host.docker.internal"
$common += @("-e", "RAG_REDIS_URL=$redisUrl")

function Wait-Health {
    param([int]$Port, [int]$Seconds = 90)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $body = (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/health" -TimeoutSec 5).Content
            return $body
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    return $null
}

$evidence = [ordered]@{
    schema     = "zent.cert.rollback-rehearsal/1"
    git_sha    = $sha
    image      = $Image
    database   = $Database
    started_at = (Get-Date).ToUniversalTime().ToString("o")
    steps      = @()
}

docker rm -f zent-cert-good zent-cert-bad 2>&1 | Out-Null

try {
    # 1. release buena
    $t0 = (Get-Date)
    docker run -d --name zent-cert-good @common -p "${GoodPort}:8000" $Image 2>&1 | Out-Null
    $health = Wait-Health -Port $GoodPort
    $evidence.steps += [ordered]@{
        step = "good_release"; health = $health
        seconds = [Math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
        healthy = [bool]($health -match '"status":"healthy"')
    }

    # 2. release rota (Qdrant en puerto muerto: dependencia caída visible)
    $t1 = (Get-Date)
    docker run -d --name zent-cert-bad @common -e "RAG_QDRANT_PORT=6399" -p "${BadPort}:8000" $Image 2>&1 | Out-Null
    $badHealth = Wait-Health -Port $BadPort
    $evidence.steps += [ordered]@{
        step = "bad_release"; health = $badHealth
        seconds = [Math]::Round(((Get-Date) - $t1).TotalSeconds, 1)
        detected_degraded = [bool]($badHealth -and $badHealth -notmatch '"status":"healthy"')
    }

    # 3. rollback (el "undo" real: volver a la imagen/config buena)
    $t2 = (Get-Date)
    docker rm -f zent-cert-bad 2>&1 | Out-Null
    docker rm -f zent-cert-good 2>&1 | Out-Null
    docker run -d --name zent-cert-good @common -p "${GoodPort}:8000" $Image 2>&1 | Out-Null
    $rollbackHealth = Wait-Health -Port $GoodPort
    $evidence.steps += [ordered]@{
        step = "rollback"; health = $rollbackHealth
        seconds = [Math]::Round(((Get-Date) - $t2).TotalSeconds, 1)
        healthy = [bool]($rollbackHealth -match '"status":"healthy"')
    }
}
finally {
    docker logs zent-cert-good 2>&1 | Select-Object -Last 40 | Set-Content -Path (Join-Path $OutDir "good-release.log") -Encoding utf8
    docker logs zent-cert-bad 2>&1 | Select-Object -Last 40 | Set-Content -Path (Join-Path $OutDir "bad-release.log") -Encoding utf8
    docker rm -f zent-cert-good zent-cert-bad 2>&1 | Out-Null
}

$evidence.finished_at = (Get-Date).ToUniversalTime().ToString("o")
$evidence.rollback_seconds = ($evidence.steps | Where-Object { $_.step -eq "rollback" }).seconds
$evidence.passed = (
    ($evidence.steps | Where-Object { $_.step -eq "good_release" }).healthy -and
    ($evidence.steps | Where-Object { $_.step -eq "bad_release" }).detected_degraded -and
    ($evidence.steps | Where-Object { $_.step -eq "rollback" }).healthy
)
$evidence | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $OutDir "rehearsal.json") -Encoding utf8
$evidence | ConvertTo-Json -Depth 5
if (-not $evidence.passed) { exit 1 }
