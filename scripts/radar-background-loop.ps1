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
$OwnerToken = [guid]::NewGuid().ToString("N")
$OwnerStartTime = (Get-Process -Id $PID).StartTime.ToUniversalTime().ToString("o")

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
    param(
        [int]$OwnerPid,
        [string]$OwnerStartTime
    )
    if ($OwnerPid -le 0 -or [string]::IsNullOrWhiteSpace($OwnerStartTime)) {
        return $false
    }
    $Process = Get-Process -Id $OwnerPid -ErrorAction SilentlyContinue
    if (-not $Process) {
        return $false
    }
    try {
        $StartedAt = $Process.StartTime.ToUniversalTime().ToString("o")
        return $StartedAt -eq $OwnerStartTime
    }
    catch {
        return $false
    }
}

function Read-LoopLock {
    try {
        return Get-Content -LiteralPath $LoopLock -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function New-LoopLockPayload {
    @{
        pid = $PID
        process_start_time = $OwnerStartTime
        owner_token = $OwnerToken
        started_at = (Get-Date -Format o)
        project_root = $ProjectRoot
    } | ConvertTo-Json -Depth 3
}

function New-AtomicLoopLock {
    $Payload = New-LoopLockPayload
    $Bytes = [System.Text.Encoding]::UTF8.GetBytes($Payload)
    $Stream = [System.IO.File]::Open($LoopLock, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try {
        $Stream.Write($Bytes, 0, $Bytes.Length)
        $Stream.Flush($true)
    }
    finally {
        $Stream.Dispose()
    }
}

function Test-LockOwnedByCurrentProcess {
    param($Lock)
    if (-not $Lock) {
        return $false
    }
    try {
        return ([int]$Lock.pid -eq $PID) -and
            ([string]$Lock.process_start_time -eq $OwnerStartTime) -and
            ([string]$Lock.owner_token -eq $OwnerToken)
    }
    catch {
        return $false
    }
}

function Test-SameLockOwner {
    param($Left, $Right)
    if (-not $Left -or -not $Right) {
        return $false
    }
    try {
        return ([int]$Left.pid -eq [int]$Right.pid) -and
            ([string]$Left.process_start_time -eq [string]$Right.process_start_time) -and
            ([string]$Left.owner_token -eq [string]$Right.owner_token)
    }
    catch {
        return $false
    }
}

function Acquire-LoopLock {
    for ($Attempt = 0; $Attempt -lt 5; $Attempt++) {
        try {
            New-AtomicLoopLock
            return $true
        }
        catch [System.IO.IOException] {
            $Existing = Read-LoopLock
            $ExistingPid = 0
            $ExistingStartTime = ""
            if ($Existing) {
                try {
                    $ExistingPid = [int]$Existing.pid
                    $ExistingStartTime = [string]$Existing.process_start_time
                }
                catch {
                    $ExistingPid = 0
                    $ExistingStartTime = ""
                }
            }
            if ($Existing -and (Test-ProcessAlive -OwnerPid $ExistingPid -OwnerStartTime $ExistingStartTime)) {
                Write-LoopLog "Another Radar background loop is already running with PID $ExistingPid."
                return $false
            }
            try {
                $Current = Read-LoopLock
                if ((-not $Existing -and -not $Current) -or (Test-SameLockOwner -Left $Existing -Right $Current)) {
                    Remove-Item -LiteralPath $LoopLock -Force -ErrorAction Stop
                    Write-LoopLog "Recovered stale Radar background loop lock."
                }
            }
            catch {
                Start-Sleep -Milliseconds 100
            }
        }
    }
    return $false
}

if (-not (Acquire-LoopLock)) {
    exit 75
}

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
        $Current = Read-LoopLock
        if (Test-LockOwnedByCurrentProcess -Lock $Current) {
            Remove-Item -LiteralPath $LoopLock -Force
        }
    }
    Write-LoopLog "Radar background loop stopped."
}
