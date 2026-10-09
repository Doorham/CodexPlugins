[CmdletBinding()]
param(
    [ValidateSet('Ask', 'Official', 'Library', 'GitHub')][string]$Source = 'Ask',
    [string]$LibraryPath,
    [switch]$CopyToLocal,
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'
$userDataRoot = & (Join-Path $PSScriptRoot 'initialize-user-data.ps1')
$repoRoot = Split-Path -Parent $PSScriptRoot
$configDir = Join-Path $repoRoot ('.runtime\CompanyAIHelpers\Users\' + [Security.Principal.WindowsIdentity]::GetCurrent().User.Value + '\EnvironmentDetector')
$configPath = Join-Path $configDir 'installer-source.txt'

function Find-HubLibrary {
    $git = Get-Command git.exe -ErrorAction SilentlyContinue
    if (-not $git) {
        foreach ($path in @((Join-Path $env:ProgramFiles 'Git\cmd\git.exe'), (Join-Path $env:ProgramFiles 'Git\bin\git.exe'))) {
            if (Test-Path -LiteralPath $path -PathType Leaf) { $git = $path; break }
        }
    }
    if (-not $git) { return $null }
    $remote = (& $git -C $repoRoot config --get remote.origin.url 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $remote) { return $null }
    $remotePath = ([string]$remote).Replace('/', '\')
    if (-not [IO.Path]::IsPathRooted($remotePath)) { return $null }
    $bare = [IO.Path]::GetFullPath($remotePath)
    if ((Split-Path -Leaf $bare) -ine 'CodexTools.git') { return $null }
    $hub = Split-Path -Parent (Split-Path -Parent $bare)
    $candidate = Join-Path $hub 'installer-library'
    if (Test-Path -LiteralPath (Join-Path $candidate 'manifest.json') -PathType Leaf) { return $candidate }
    return $null
}

if (-not $LibraryPath) { $LibraryPath = Find-HubLibrary }
$pendingPrompt = $false
if ($Source -eq 'Ask') {
    if ($NonInteractive) {
        $Source = 'Official'
        $pendingPrompt = $true
    }
    else {
        Write-Host '环境补全安装包来源：'
        Write-Host '  1 由各软件官方源下载（WinGet/PyPI）'
        if ($LibraryPath) {
            Write-Host '  2 使用 Y 盘共享安装包库（已下载并校验）'
            Write-Host '  3 将 Y 盘安装包库复制到本机后使用'
            Write-Host '  4 下载 GitHub 子库准备好的安装包（其余文件从原发布方下载）'
            $choice = Read-Host '请选择 1、2、3 或 4'
            switch ($choice) {
                '1' { $Source = 'Official' }
                '2' { $Source = 'Library' }
                '3' { $Source = 'Library'; $CopyToLocal = $true }
                '4' { $Source = 'GitHub' }
                default { throw '选择无效；未修改安装包来源。' }
            }
        }
        else {
            Write-Host '  2 下载 GitHub 子库准备好的安装包（其余文件从原发布方下载）'
            $choice = Read-Host '请选择 1 或 2'
            switch ($choice) {
                '1' { $Source = 'Official' }
                '2' { $Source = 'GitHub' }
                default { throw '选择无效；未修改安装包来源。' }
            }
        }
    }
}

if ($Source -eq 'GitHub') {
    $LibraryPath = Join-Path $repoRoot '.runtime\installer-library'
    & (Join-Path $PSScriptRoot 'download-environment-installers.ps1') -Destination $LibraryPath | Out-Host
    if (-not $?) { throw 'GitHub 安装包库下载失败；未修改安装包来源。' }
    $Source = 'Library'
}

if ($Source -eq 'Library') {
    if (-not $LibraryPath) { throw '未找到安装包库；请指定 -LibraryPath。' }
    $LibraryPath = (Resolve-Path -LiteralPath $LibraryPath -ErrorAction Stop).Path
    $trustedVerifier = Join-Path $PSScriptRoot 'verify-installer-library.ps1'
    & $trustedVerifier -LibraryPath $LibraryPath | Out-Host
    if (-not $?) { throw '安装包校验失败。' }
    if ($CopyToLocal) {
        $target = Join-Path $repoRoot '.runtime\installer-library'
        if (Test-Path -LiteralPath $target) { throw '本机安装包库目录已存在；请先确认现有内容。' }
        New-Item -ItemType Directory -Path $target -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $LibraryPath 'manifest.json') -Destination $target -ErrorAction Stop
        $verify = Join-Path $LibraryPath 'verify-packages.ps1'
        if (Test-Path -LiteralPath $verify -PathType Leaf) {
            Copy-Item -LiteralPath $verify -Destination $target -ErrorAction Stop
        }
        Copy-Item -LiteralPath (Join-Path $LibraryPath 'packages') -Destination $target -Recurse -ErrorAction Stop
        & $trustedVerifier -LibraryPath $target | Out-Host
        if (-not $?) { throw '本机副本校验失败。' }
        $LibraryPath = $target
    }
}

New-Item -ItemType Directory -Path $configDir -Force | Out-Null
$lines = if ($Source -eq 'Library') { @('library', $LibraryPath) } elseif ($pendingPrompt) { @('official-pending') } else { @('official') }
[IO.File]::WriteAllLines($configPath, $lines, [Text.UTF8Encoding]::new($false))
Write-Output "环境补全安装包来源已设置为 $Source。"
