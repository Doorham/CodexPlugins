$ErrorActionPreference = 'Stop'
$installDir = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CompanyAIHelpers\CodexAnswerChime'
$startupLink = Join-Path ([Environment]::GetFolderPath('Startup')) 'Codex Answer Chime.lnk'
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
Get-Process -Name 'CodexAnswerChime' -ErrorAction SilentlyContinue | Stop-Process -Force
if (Test-Path -LiteralPath $startupLink) { Remove-Item -LiteralPath $startupLink -Force }
Remove-ItemProperty -LiteralPath $runKey -Name 'Codex Answer Chime' -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $installDir) { Remove-Item -LiteralPath $installDir -Recurse -Force }
Write-Output 'Codex Answer Chime removed for the current user.'
