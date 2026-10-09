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
$userDataRoot = & (Join-Path $PSScriptRoot 'initialize-user-data.ps1')
$normalizedId = $PluginId.Trim().ToLowerInvariant()
if (-not $normalizedId.StartsWith('private-')) { $normalizedId = "private-$normalizedId" }
if ($normalizedId -notmatch '^private-[a-z0-9]+(?:-[a-z0-9]+)*$') { throw 'PluginId must use lowercase letters, digits and hyphens.' }
if ([string]::IsNullOrWhiteSpace($Name) -or [string]::IsNullOrWhiteSpace($Developer)) { throw 'Name and Developer are required.' }

$privateRoot = Join-Path (Split-Path -Parent $PSScriptRoot) ('.runtime\CompanyAIHelpers\Users\' + [Security.Principal.WindowsIdentity]::GetCurrent().User.Value + '\CodexTools\PrivatePlugins')
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
    description = '默认仅保存在当前电脑的私人插件。'
    tags = @()
    icon = '◇'
    accent = '#8b5cf6'
    mode = 'background'
    handler = 'process_app'
    executable = "%CODEXTOOLS_USER_DATA_ROOT%\CodexTools\PrivatePlugins\$normalizedId\$executableName"
    processName = $executableName
    shareFiles = @($executableName)
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
    ShareEnabled = $false
    PublisherId = '首次共享提交时确认开发者署名'
    PromotionRequired = $true
}
