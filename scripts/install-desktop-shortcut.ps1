[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $repoRoot 'start-plugin-station.vbs'
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'Codex工具箱.lnk'
$wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
$icon = Join-Path $repoRoot 'assets\CodexTools.ico'
$description = 'CodexTools desktop launcher'

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Launcher not found: $launcher"
}
if (-not (Test-Path -LiteralPath $wscript -PathType Leaf)) {
    throw "Windows Script Host not found: $wscript"
}
if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) {
    throw "CodexTools brand icon not found: $icon"
}

$shell = New-Object -ComObject WScript.Shell
if (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
    $existing = $shell.CreateShortcut($shortcutPath)
    $owned = $existing.Description -eq $description -or (
        $existing.TargetPath -ieq $wscript -and
        $existing.Arguments -like '*start-plugin-station.vbs*'
    )
    if (-not $owned) {
        throw "Desktop shortcut already exists but is not owned by CodexTools: $shortcutPath"
    }
}

$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $wscript
$shortcut.Arguments = '"' + $launcher + '"'
$shortcut.WorkingDirectory = $repoRoot
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = $description
$shortcut.Save()

$saved = $shell.CreateShortcut($shortcutPath)
if ($saved.TargetPath -ine $wscript -or $saved.Arguments -notlike "*$launcher*") {
    throw 'Desktop shortcut verification failed.'
}

[pscustomobject]@{
    Shortcut = $shortcutPath
    Target = $saved.TargetPath
    Arguments = $saved.Arguments
    WorkingDirectory = $saved.WorkingDirectory
    IconLocation = $saved.IconLocation
}
