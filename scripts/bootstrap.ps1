$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvDir = Join-Path $repoRoot '.runtime\venv'
$requirements = Join-Path $repoRoot 'apps\plugin-station\requirements.txt'
$python = (Get-Command python -ErrorAction Stop).Source

if (-not (Test-Path -LiteralPath (Join-Path $venvDir 'Scripts\python.exe'))) {
    & $python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create Python virtual environment.' }
}

$venvPython = Join-Path $venvDir 'Scripts\python.exe'
& $venvPython -m pip install --disable-pip-version-check -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'Failed to install Python dependencies.' }

$proxyBypassScript = Join-Path $repoRoot 'scripts\ensure-proxy-bypass.py'
if (Test-Path -LiteralPath $proxyBypassScript -PathType Leaf) {
    & $venvPython $proxyBypassScript
    if ($LASTEXITCODE -ne 0) { throw 'Proxy bypass bootstrap failed.' }
}

$codexSystemProxyScript = Join-Path $repoRoot 'scripts\ensure-codex-system-proxy.py'
if (Test-Path -LiteralPath $codexSystemProxyScript -PathType Leaf) {
    & $venvPython $codexSystemProxyScript
    if ($LASTEXITCODE -ne 0) { throw 'Codex system proxy bootstrap failed.' }
}

Write-Output "Development environment ready: $venvDir"
