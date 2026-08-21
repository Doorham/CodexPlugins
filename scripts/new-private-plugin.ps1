[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PluginId,
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [string]$Developer
)

$ErrorActionPreference = 'Stop'
$normalizedId = $PluginId.Trim().ToLowerInvariant()
if (-not $normalizedId.StartsWith('private-')) { $normalizedId = "private-$normalizedId" }
if ($normalizedId -notmatch '^private-[a-z0-9]+(?:-[a-z0-9]+)*$') { throw 'PluginId must use lowercase letters, digits and hyphens.' }
if ([string]::IsNullOrWhiteSpace($Name) -or [string]::IsNullOrWhiteSpace($Developer)) { throw 'Name and Developer are required.' }

$privateRoot = Join-Path $env:LOCALAPPDATA 'CompanyAIHelpers\CodexTools\PrivatePlugins'
$pluginRoot = Join-Path $privateRoot $normalizedId
$manifestPath = Join-Path $pluginRoot 'plugin.json'
if (Test-Path -LiteralPath $pluginRoot) { throw "Private plugin already exists: $pluginRoot" }
New-Item -ItemType Directory -Path $pluginRoot | Out-Null

$toolName = (($normalizedId.Substring(8) -split '-') | ForEach-Object {
    if ($_.Length -eq 1) { $_.ToUpperInvariant() } else { $_.Substring(0, 1).ToUpperInvariant() + $_.Substring(1) }
}) -join ''
$executableName = "$toolName.exe"
$manifest = [ordered]@{
    id = $normalizedId
    name = $Name.Trim()
    moduleVersion = '1.0.0'
    developers = @($Developer.Trim())
    description = '仅保存在当前电脑的私人插件。'
    category = '私人'
    icon = '◇'
    accent = '#8b5cf6'
    mode = 'background'
    handler = 'process_app'
    executable = "%LOCALAPPDATA%\CompanyAIHelpers\$toolName\$executableName"
    processName = $executableName
    startup = [ordered]@{ type = 'run'; name = $Name.Trim() }
    actions = @('toggle_enabled')
    uiActions = @([ordered]@{ id = 'toggle_enabled'; label = '切换状态'; kind = 'toggle' })
    agentAccess = [ordered]@{ enabled = $true; actions = @('toggle_enabled') }
}
[System.IO.File]::WriteAllText(
    $manifestPath,
    (($manifest | ConvertTo-Json -Depth 8) + "`n"),
    [System.Text.UTF8Encoding]::new($false)
)

[pscustomobject]@{
    Scope = 'private'
    PluginId = $normalizedId
    Version = '1.0.0'
    Developers = @($Developer.Trim())
    Manifest = $manifestPath
    Sync = $false
    Upload = $false
    PromotionRequired = $true
}
