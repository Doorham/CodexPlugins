$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$exe = Join-Path $repo '.runtime\CompanyAIHelpers\UpdreamClipboardCleaner\UpdreamClipboardCleaner.exe'
$startupLink = Join-Path ([Environment]::GetFolderPath('Startup')) 'Updream Clipboard Cleaner.lnk'
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$running = @(Get-Process -Name 'UpdreamClipboardCleaner' -ErrorAction SilentlyContinue | Where-Object { $_.Path -and [string]::Equals($_.Path, $exe, [StringComparison]::OrdinalIgnoreCase) -and $_.SessionId -eq (Get-Process -Id $PID).SessionId })
if ($running.Count) { throw 'Exit this helper normally, then retry. No process was terminated.' }
if (Test-Path -LiteralPath $startupLink) {
    $shell = New-Object -ComObject WScript.Shell
    if ([string]::Equals($shell.CreateShortcut($startupLink).TargetPath, $exe, [StringComparison]::OrdinalIgnoreCase)) { Remove-Item -LiteralPath $startupLink }
}
$values = Get-ItemProperty -LiteralPath $runKey -ErrorAction SilentlyContinue
$property = $values.PSObject.Properties['Updream Clipboard Cleaner']
if ($property -and $property.Value -eq ('"' + $exe + '"')) { Remove-ItemProperty -LiteralPath $runKey -Name 'Updream Clipboard Cleaner' }
Write-Output 'Current user startup disabled. Shared program and personal state retained.'
