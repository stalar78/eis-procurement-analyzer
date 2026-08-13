param(
    [int]$IntervalSeconds = 10800,
    [switch]$RunOnce
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$Launcher = Join-Path $ProjectRoot "scripts\radar-production.cmd"
$RuntimeLogDir = Join-Path $ProjectRoot "runtime-logs"
$LoopLock = Join-Path $RuntimeLogDir "radar-background-loop.lock"
$LoopLog = Join-Path $RuntimeLogDir "radar-background-loop.log"

if ($IntervalSeconds -lt 1) {
    throw "IntervalSeconds must be positive."
}
if (-not (Test-Path -LiteralPath $Launcher)) {
    throw "Radar production launcher not found: $Launcher"
}
if (-not (Test-Path -LiteralPath $RuntimeLogDir)) {
    New-Item -ItemType Directory -Path $RuntimeLogDir -Force | Out-Null
}

function Write-LoopLog {
    param([string]$Message)
    $Timestamp = Get-Date -Format o
    Add-Content -LiteralPath $LoopLog -Value "$Timestamp $Message" -Encoding UTF8
}

function Test-ProcessAlive {
    param([int]$Pid)
    if ($Pid -le 0) {
        return $false
    }
    return [bool](Get-Process -Id $Pid -ErrorAction SilentlyContinue)
}

if (Test-Path -LiteralPath $LoopLock) {
    $ExistingPid = 0
    try {
        $Existing = Get-Content -LiteralPath $LoopLock -Raw -Encoding UTF8 | ConvertFrom-Json
        $ExistingPid = [int]$Existing.pid
    }
    catch {
        $ExistingPid = 0
    }
    if (Test-ProcessAlive -Pid $ExistingPid) {
        Write-LoopLog "Another Radar background loop is already running with PID $ExistingPid."
        exit 75
    }
}

$LockPayload = @{
    pid = $PID
    started_at = (Get-Date -Format o)
    project_root = $ProjectRoot
} | ConvertTo-Json -Depth 3
[System.IO.File]::WriteAllText($LoopLock, $LockPayload, [System.Text.Encoding]::UTF8)

try {
    Write-LoopLog "Radar background loop started. interval_seconds=$IntervalSeconds"
    do {
        Write-LoopLog "Starting Radar production launcher."
        & $Launcher --send-telegram-alerts
        $ExitCode = $LASTEXITCODE
        Write-LoopLog "Radar production launcher exited with code $ExitCode."
        if ($RunOnce) {
            break
        }
        Start-Sleep -Seconds $IntervalSeconds
    } while ($true)
}
finally {
    if (Test-Path -LiteralPath $LoopLock) {
        try {
            $Current = Get-Content -LiteralPath $LoopLock -Raw -Encoding UTF8 | ConvertFrom-Json
            if ([int]$Current.pid -eq $PID) {
                Remove-Item -LiteralPath $LoopLock -Force
            }
        }
        catch {
        }
    }
    Write-LoopLog "Radar background loop stopped."
}
