param(
    [string]$TaskName = "Stalar Procurement Radar"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$Launcher = Join-Path $ProjectRoot "scripts\radar-production.cmd"

if (-not (Test-Path -LiteralPath $Launcher)) {
    throw "Radar production launcher not found: $Launcher"
}

$Action = New-ScheduledTaskAction `
    -Execute $Launcher `
    -Argument "--send-telegram-alerts" `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Hours 3) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$Settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

$Task = New-ScheduledTask `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Runs EIS Procurement Radar production profile every 3 hours."

Register-ScheduledTask `
    -TaskName $TaskName `
    -InputObject $Task `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName
