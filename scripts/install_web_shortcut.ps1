$ErrorActionPreference = "Stop"

$scriptsDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDirectory = Split-Path -Parent $scriptsDirectory
$launcherPath = Join-Path $projectDirectory "run_local_web.py"
$pythonCommand = Get-Command python -ErrorAction Stop
$pythonDirectory = Split-Path -Parent $pythonCommand.Source
$pythonwPath = Join-Path $pythonDirectory "pythonw.exe"

if (-not (Test-Path -LiteralPath $pythonwPath)) {
    throw "pythonw.exe was not found next to the active Python installation."
}

$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$shortcutPaths = @(
    (Join-Path $desktop "OTP Codex Local.lnk"),
    (Join-Path $startMenu "OTP Codex Local.lnk")
)

foreach ($shortcutPath in $shortcutPaths) {
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $pythonwPath
    $shortcut.Arguments = '"' + $launcherPath + '"'
    $shortcut.WorkingDirectory = $projectDirectory
    $shortcut.Description = "Open the OTP Codex local web app"
    $shortcut.Save()
}

Write-Host "Created OTP Codex Local shortcuts on Desktop and Start Menu."
Write-Host "You can pin the Start Menu shortcut to the taskbar."
