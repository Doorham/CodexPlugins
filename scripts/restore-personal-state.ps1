[CmdletBinding()]
param(
    [ValidateSet('UpdreamBridge','CodexAnswerChime','EnvironmentDetector','ProxyOverrideBypass','CodexTools')][string]$Component,
    [ValidateSet('CurrentUserLegacy','WorkspaceLegacy')][string]$Source = 'CurrentUserLegacy',
    [switch]$Confirmed
)
# Local recovery only. No inventory, hashes, contents, credentials, or paths are emitted.
$ErrorActionPreference = 'Stop'
if (-not $Confirmed -or -not $Component) { throw 'Confirm this local component recovery explicitly.' }
$repo = Split-Path -Parent $PSScriptRoot
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$userRoot = & (Join-Path $PSScriptRoot 'initialize-user-data.ps1') -RepositoryRoot $repo
$sourceRoot = if ($Source -eq 'CurrentUserLegacy') {
    Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CompanyAIHelpers'
} else { Join-Path $repo '.runtime\CompanyAIHelpers' }
$origin = Join-Path $sourceRoot $Component
$target = Join-Path $userRoot $Component
if (-not (Test-Path -LiteralPath $origin -PathType Container)) { throw 'Selected local source is absent; originals retained.' }
# A workspace's legacy flat state has no automatic account attribution.
if (([IO.Directory]::GetAccessControl($origin)).GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid) {
    throw 'Source ownership differs from the current Windows account; nothing copied.'
}
$names = switch ($Component) {
    'UpdreamBridge' { @('credentials.json','webview2-data','Outputs') }
    'CodexAnswerChime' { @('settings.json','Sounds') }
    'EnvironmentDetector' { @('installer-source.txt','Backups') }
    'ProxyOverrideBypass' { @('custom-domains.json','Backups') }
    'CodexTools' { @('CompanyAccess','PrivatePlugins','runtime-intent.json') }
}
$processNames = switch ($Component) {
    'UpdreamBridge' { @('UpdreamBridgeConfig') }
    'CodexTools' { @('NasRemoteConnect') }
    default { @($Component) }
}
# Refuse live writers before copying. Read process identity, not personal files.
$writer = @(Get-Process -Name $processNames -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and ($_.Path.StartsWith($origin + '\',[StringComparison]::OrdinalIgnoreCase) -or
        $_.Path.StartsWith((Join-Path $repo ('.runtime\CompanyAIHelpers\' + $Component)) + '\',[StringComparison]::OrdinalIgnoreCase))
})
if ($writer.Count) { throw 'Exit this component normally, then retry. No process was stopped.' }
$selected = @()
foreach ($name in $names) {
    $from = Join-Path $origin $name; $to = Join-Path $target $name
    if (-not (Test-Path -LiteralPath $from)) { continue }
    if ($Component -eq 'CodexTools' -and $name -eq 'PrivatePlugins' -and (Test-Path -LiteralPath $to)) {
        foreach ($entry in @(Get-ChildItem -LiteralPath $from -Force)) {
            if ($entry.Name -eq 'private-layer.json') { continue }
            $destination = Join-Path $to $entry.Name
            if (Test-Path -LiteralPath $destination) { throw 'Destination already has private module state; no overwrite performed.' }
        }
    } elseif (Test-Path -LiteralPath $to) { throw 'Destination already has local state; no comparison or overwrite performed.' }
    # Reject links before copying; names stay on this machine and never enter a report.
    $pending = [Collections.Generic.Stack[string]]::new();$pending.Push($from)
    while ($pending.Count) {
        $entry = Get-Item -LiteralPath $pending.Pop() -Force
        if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Local source contains a link; nothing copied.' }
        if ($entry.PSIsContainer) { foreach ($child in @(Get-ChildItem -LiteralPath $entry.FullName -Force)) { $pending.Push($child.FullName) } }
    }
    # Protect retained originals too; only the approved private schema items.
    $pending.Push($from)
    while ($pending.Count) {
        $entry = Get-Item -LiteralPath $pending.Pop() -Force
        if ($entry.PSIsContainer) {
            $acl=[Security.AccessControl.DirectorySecurity]::new()
            $acl.SetSecurityDescriptorSddlForm('D:P(A;OICI;FA;;;' + $sid + ')(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)')
            [IO.Directory]::SetAccessControl($entry.FullName,$acl)
            foreach ($child in @(Get-ChildItem -LiteralPath $entry.FullName -Force)) { $pending.Push($child.FullName) }
        } else {
            $acl=[Security.AccessControl.FileSecurity]::new()
            $acl.SetSecurityDescriptorSddlForm('D:P(A;;FA;;;' + $sid + ')(A;;FA;;;SY)(A;;FA;;;BA)')
            [IO.File]::SetAccessControl($entry.FullName,$acl)
        }
    }
    $selected += [pscustomobject]@{from=$from;to=$to}
}
[IO.Directory]::CreateDirectory($target) | Out-Null
$staging = Join-Path $userRoot ('restore-staging-' + [guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($staging) | Out-Null
try {
    foreach ($item in $selected) { Copy-Item -LiteralPath $item.from -Destination (Join-Path $staging (Split-Path -Leaf $item.to)) -Recurse -ErrorAction Stop }
    if ($Component -eq 'CodexTools') {
        # Rewrite only local executable/metadata paths, never progress or account bodies.
        $plugins = Join-Path $staging 'PrivatePlugins'
        if (Test-Path -LiteralPath $plugins) {
            foreach ($manifest in @(Get-ChildItem -LiteralPath $plugins -Recurse -Filter 'plugin.json' -File)) {
                $text = [IO.File]::ReadAllText($manifest.FullName)
                $slash = [string][char]92; $escaped = $slash + $slash
                $oldPrefix = '%CODEXTOOLS_DATA_ROOT%' + $escaped + 'CodexTools' + $escaped + 'PrivatePlugins'
                $newPrefix = '%CODEXTOOLS_USER_DATA_ROOT%' + $escaped + 'CodexTools' + $escaped + 'PrivatePlugins'
                $text = $text.Replace($oldPrefix,$newPrefix)
                $text = $text.Replace($sourceRoot.Replace($slash,$escaped),$userRoot.Replace($slash,$escaped))
                [IO.File]::WriteAllText($manifest.FullName,$text,[Text.UTF8Encoding]::new($false))
            }
        }
    }
    foreach ($item in $selected) {
        $prepared = Join-Path $staging (Split-Path -Leaf $item.to)
        if ($Component -eq 'CodexTools' -and (Split-Path -Leaf $item.to) -eq 'PrivatePlugins' -and (Test-Path -LiteralPath $item.to)) {
            foreach ($entry in @(Get-ChildItem -LiteralPath $prepared -Force)) {
                if ($entry.Name -eq 'private-layer.json') { continue }
                Move-Item -LiteralPath $entry.FullName -Destination (Join-Path $item.to $entry.Name) -ErrorAction Stop
            }
        } else { Move-Item -LiteralPath $prepared -Destination $item.to -ErrorAction Stop }
    }
} catch { throw 'Local recovery did not complete; originals and local staging retained. No upload or comparison occurred.' }
[pscustomobject]@{ok=$true;localOnly=$true;originalsRetained=$true;uploaded=$false}
