param(
    [string]$EntryName = "Stalar Procurement Radar Background"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$LoopScript = Join-Path $ProjectRoot "scripts\radar-background-loop.ps1"
$StartupDir = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "$EntryName.lnk"
$PowerShellExe = Join-Path $PSHOME "powershell.exe"
$Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $LoopScript

if (-not (Test-Path -LiteralPath $LoopScript)) {
    throw "Radar background loop script not found: $LoopScript"
}
if (-not (Test-Path -LiteralPath $StartupDir)) {
    New-Item -ItemType Directory -Path $StartupDir -Force | Out-Null
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PowerShellExe
$Shortcut.Arguments = $Arguments
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.WindowStyle = 7
$Shortcut.Description = "Starts the Stalar Procurement Radar background loop at user login."
$Shortcut.Save()

Write-Output "Installed startup entry: $ShortcutPath"
Write-Output "Target: $PowerShellExe"
Write-Output "Arguments: $Arguments"
Write-Output "WorkingDirectory: $ProjectRoot"
