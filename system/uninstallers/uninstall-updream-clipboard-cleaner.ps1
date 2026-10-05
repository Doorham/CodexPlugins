$ErrorActionPreference = 'Stop'
$installDir = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) '.runtime\CompanyAIHelpers\UpdreamClipboardCleaner'
$startupLink = Join-Path ([Environment]::GetFolderPath('Startup')) 'Updream Clipboard Cleaner.lnk'
Get-Process -Name 'UpdreamClipboardCleaner' -ErrorAction SilentlyContinue | Stop-Process -Force
if (Test-Path -LiteralPath $startupLink) { Remove-Item -LiteralPath $startupLink -Force }
if (Test-Path -LiteralPath $installDir) { Remove-Item -LiteralPath $installDir -Recurse -Force }
Write-Output 'Updream Clipboard Cleaner removed for the current user.'
