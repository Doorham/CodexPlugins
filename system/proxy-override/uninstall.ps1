$ErrorActionPreference = 'Stop'
$recordDir = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CompanyAIHelpers\ProxyOverrideBypass'
$recordPath = Join-Path $recordDir 'install-record.json'
if (-not (Test-Path -LiteralPath $recordPath)) { throw "Install record not found: $recordPath" }
$record = Get-Content -LiteralPath $recordPath -Raw -Encoding UTF8 | ConvertFrom-Json
$regPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
$current = (Get-ItemProperty -LiteralPath $regPath -Name ProxyOverride -ErrorAction SilentlyContinue).ProxyOverride
$removeSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($entry in $record.AddedEntries) { [void]$removeSet.Add([string]$entry) }
$kept = @($current -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $removeSet.Contains($_) })
Set-ItemProperty -LiteralPath $regPath -Name ProxyOverride -Type String -Value ($kept -join ';')
Add-Type -Path (Join-Path $PSScriptRoot 'WinInetProxyBypass.cs')
[WinInetProxyBypass]::Apply(($kept -join ';'))
Write-Output "Removed $($removeSet.Count) entries recorded from this installation; preserved all other current entries."
