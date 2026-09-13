#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Local helper for microsoft/tgrep (trigram-indexed grep).

.DESCRIPTION
    Wraps the tgrep binary installed in .agents/tools/tgrep/ (git-ignored).
    Index lives in .tgrep/ at the repo root (git-ignored).

    Commands:
      index   Build/rebuild the trigram index (extra flags pass through, e.g. --force)
      serve   Start the background watcher server (auto-builds index if missing)
      status  Show server and index status
      stop    Stop the server started by this script
      search  Search the repo; first argument is the pattern, the rest pass through
      <any>   Anything else is treated as a search pattern

.EXAMPLE
    pwsh scripts/tgrep.ps1 index
    pwsh scripts/tgrep.ps1 serve
    pwsh scripts/tgrep.ps1 search "TenantContext"
    pwsh scripts/tgrep.ps1 search "async def" -t py -C 2
    pwsh scripts/tgrep.ps1 "def test_"
    pwsh scripts/tgrep.ps1 stop
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command = 'status',

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Extra
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $RepoRoot '.tgrep/server.pid'

function Resolve-Tgrep {
    $local = Join-Path $RepoRoot '.agents/tools/tgrep/tgrep.exe'
    if (Test-Path $local) { return $local }
    $cmd = Get-Command tgrep -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw 'tgrep not found. Install the binary in .agents/tools/tgrep/ or on PATH.'
}

function Get-RunningServerPid {
    if (-not (Test-Path $PidFile)) { return $null }
    $serverPid = Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $serverPid) { return $null }
    $proc = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
    if ($proc -and $proc.ProcessName -eq 'tgrep') { return [int]$serverPid }
    return $null
}

function Start-TgrepServer {
    $existing = Get-RunningServerPid
    if ($existing) {
        Write-Host "tgrep server already running (PID $existing)."
        return
    }
    if (Test-Path $PidFile) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }

    $serverArgs = @('serve', $RepoRoot) + $Extra
    $quoted = $serverArgs | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }
    if ($IsWindows) {
        $proc = Start-Process -FilePath $Tgrep -ArgumentList $quoted -WindowStyle Hidden -PassThru
    } else {
        $proc = Start-Process -FilePath $Tgrep -ArgumentList $quoted -PassThru
    }
    Set-Content -Path $PidFile -Value $proc.Id
    Write-Host "tgrep server started (PID $($proc.Id))."
    Write-Host "Index: $RepoRoot\.tgrep"
    Write-Host "Stop it with: pwsh scripts/tgrep.ps1 stop"
}

function Stop-TgrepServer {
    if (-not (Test-Path $PidFile)) {
        Write-Host 'No server registered (.tgrep/server.pid missing).'
        return
    }
    $serverPid = Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    $proc = if ($serverPid) { Get-Process -Id $serverPid -ErrorAction SilentlyContinue } else { $null }
    if ($proc -and $proc.ProcessName -eq 'tgrep') {
        Stop-Process -Id $serverPid -Force
        Write-Host "tgrep server stopped (PID $serverPid)."
    } else {
        Write-Host "PID $serverPid is not a running tgrep process; cleaning up pid file."
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

function Invoke-TgrepSearch {
    param([string]$Pattern, [string[]]$Flags = @())
    & $Tgrep $Pattern $RepoRoot @Flags
    exit $LASTEXITCODE
}

$Tgrep = Resolve-Tgrep

switch ($Command.ToLowerInvariant()) {
    'index' { & $Tgrep index $RepoRoot @Extra; exit $LASTEXITCODE }
    'serve' { Start-TgrepServer }
    'status' {
        & $Tgrep status $RepoRoot
        $running = Get-RunningServerPid
        if ($running) { Write-Host "PID file: $running" }
    }
    'stop' { Stop-TgrepServer }
    'search' {
        if (-not $Extra -or $Extra.Count -lt 1) { throw 'Usage: pwsh scripts/tgrep.ps1 search <pattern> [flags]' }
        $flags = if ($Extra.Count -gt 1) { $Extra[1..($Extra.Count - 1)] } else { @() }
        Invoke-TgrepSearch -Pattern $Extra[0] -Flags $flags
    }
    default { Invoke-TgrepSearch -Pattern $Command -Flags $Extra }
}
