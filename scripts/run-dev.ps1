param([switch]$Console)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvDir = Join-Path $repoRoot '.runtime\venv'
$app = Join-Path $repoRoot 'apps\plugin-station\app.py'
$python = Join-Path $venvDir $(if ($Console) { 'Scripts\python.exe' } else { 'Scripts\pythonw.exe' })

if (-not (Test-Path -LiteralPath $python)) {
    & (Join-Path $PSScriptRoot 'bootstrap.ps1')
}

if ($Console) {
    & $python $app
    exit $LASTEXITCODE
}

Start-Process -FilePath $python -ArgumentList ('"' + $app + '"') -WorkingDirectory (Split-Path -Parent $app) | Out-Null
Write-Output 'Codex插件站已启动。'
