[CmdletBinding()]
param(
    [ValidateSet('Check', 'Apply')]
    [string]$Mode = 'Check',
    [string]$RepositoryRoot = '',
    [string]$RemoteName = 'origin',
    [string]$Branch = 'main',
    [switch]$AllowNonGitHubRemote
)

$ErrorActionPreference = 'Stop'
$repoRoot = if ($RepositoryRoot) {
    (Resolve-Path -LiteralPath $RepositoryRoot).Path
} else {
    Split-Path -Parent $PSScriptRoot
}

function Write-Result {
    param([hashtable]$Value, [int]$ExitCode = 0)
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    [pscustomobject]$Value | ConvertTo-Json -Compress
    exit $ExitCode
}

$script:gitExecutable = $null

function Resolve-GitExecutable {
    $command = Get-Command git.exe -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($command) { return $command.Source }

    $candidates = @()
    if ($env:CODEXTOOLS_GIT) { $candidates += $env:CODEXTOOLS_GIT }
    if ($env:ProgramFiles) { $candidates += Join-Path $env:ProgramFiles 'Git\cmd\git.exe' }
    $programFilesX86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
    if ($programFilesX86) { $candidates += Join-Path $programFilesX86 'Git\cmd\git.exe' }
    if ($env:LOCALAPPDATA) {
        $candidates += Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd\git.exe'
        $candidates += Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\git.exe'
    }
    if ($env:USERPROFILE) {
        $candidates += Join-Path $env:USERPROFILE 'scoop\apps\git\current\cmd\git.exe'
        $runtimeRoot = Join-Path $env:USERPROFILE '.cache\codex-runtimes'
        if (Test-Path -LiteralPath $runtimeRoot -PathType Container) {
            $runtimeCandidates = Get-ChildItem -LiteralPath $runtimeRoot -Directory -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending |
                ForEach-Object { Join-Path $_.FullName 'dependencies\native\git\cmd\git.exe' }
            $candidates += @($runtimeCandidates)
        }
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw '未找到可用的 Git。请先启动一次 Codex 以准备随附运行时，或安装 Git for Windows。'
}

function Invoke-Git {
    param([string[]]$Arguments)
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = @(& $script:gitExecutable -C $repoRoot @Arguments 2>&1)
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($output -join ' ')"
    }
    return $output
}

function Test-GitHubRemote {
    param([string]$Url)
    return $Url -match '^https://github\.com/[^/]+/[^/]+(?:\.git)?$' -or
        $Url -match '^git@github\.com:[^/]+/[^/]+(?:\.git)?$' -or
        $Url -match '^ssh://git@github\.com/[^/]+/[^/]+(?:\.git)?$'
}

function Get-ReleaseFromRef {
    param([string]$Ref)
    $content = @(Invoke-Git @('show', "$Ref`:ONLINE-RELEASE.json")) -join "`n"
    return $content | ConvertFrom-Json
}

function Install-BuiltHelper {
    param([string]$FileName, [string]$TargetFolder, [string]$ProcessName, [string]$Commit)
    $source = Join-Path $repoRoot "artifacts\helpers\$FileName"
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { return $false }
    $folder = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) "CompanyAIHelpers\$TargetFolder"
    $target = Join-Path $folder $FileName
    $same = (Test-Path -LiteralPath $target -PathType Leaf) -and
        ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -eq (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash)
    if ($same) { return $false }
    $running = @()
    if ($ProcessName) { $running = @(Get-Process -Name $ProcessName -ErrorAction SilentlyContinue) }
    foreach ($process in $running) { Stop-Process -Id $process.Id -Force }
    if ($running.Count) { Start-Sleep -Milliseconds 300 }
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        $backupFolder = Join-Path $folder 'Backups'
        New-Item -ItemType Directory -Path $backupFolder -Force | Out-Null
        $backup = Join-Path $backupFolder "$([IO.Path]::GetFileNameWithoutExtension($FileName))-pre-$($Commit.Substring(0, 8))$([IO.Path]::GetExtension($FileName))"
        if (-not (Test-Path -LiteralPath $backup)) { Copy-Item -LiteralPath $target -Destination $backup }
    }
    $temporary = "$target.updating"
    Copy-Item -LiteralPath $source -Destination $temporary -Force
    Move-Item -LiteralPath $temporary -Destination $target -Force
    if ($running.Count) { Start-Process -FilePath $target -WorkingDirectory $folder -WindowStyle Hidden }
    return $true
}

try {
    $script:gitExecutable = Resolve-GitExecutable
    $head = (@(Invoke-Git @('rev-parse', 'HEAD')))[0].Trim()
    $branchName = (@(Invoke-Git @('branch', '--show-current')))[0].Trim()
    $dirty = @((Invoke-Git @('status', '--porcelain'))).Count -gt 0
    $remoteUrl = (@(Invoke-Git @('remote', 'get-url', $RemoteName)))[0].Trim()
    if (-not $AllowNonGitHubRemote -and -not (Test-GitHubRemote $remoteUrl)) {
        Write-Result @{
            ok = $false; status = 'wrong_remote'; updated = $false
            message = "网络版只接受 GitHub 远端；当前 $RemoteName 不是 github.com。"
        } 2
    }

    Invoke-Git @('fetch', '--tags', $RemoteName, $Branch) | Out-Null
    $remoteHead = (@(Invoke-Git @('rev-parse', 'FETCH_HEAD')))[0].Trim()
    $release = Get-ReleaseFromRef 'FETCH_HEAD'

    if ($head -eq $remoteHead) {
        Write-Result @{
            ok = $true; status = 'current'; updated = $false; source = 'GitHub'
            version = [string]$release.version; headCommit = $head
            message = "当前已是最新版 v$($release.version)。"
        }
    }

    & $script:gitExecutable -C $repoRoot merge-base --is-ancestor $head $remoteHead 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Result @{
            ok = $false; status = 'diverged'; updated = $false
            message = '本地与 GitHub 历史已经分叉，自动更新已停止。'
        } 3
    }

    if ($Mode -eq 'Check') {
        Write-Result @{
            ok = $true; status = 'available'; updated = $false; updateAvailable = $true; source = 'GitHub'
            version = [string]$release.version; headCommit = $remoteHead
            message = "GitHub 上有 v$($release.version)，可以更新。"
        }
    }
    if ($dirty) {
        Write-Result @{ ok = $false; status = 'local_changes'; updated = $false; message = '检测到本地改动，已停止自动更新。' } 4
    }
    if ($branchName -ne $Branch) {
        Write-Result @{ ok = $false; status = 'development_branch'; updated = $false; message = "当前位于 $branchName 分支，已停止自动更新。" } 5
    }

    $changedFiles = @(Invoke-Git @('diff', '--name-only', "$head..$remoteHead"))
    Invoke-Git @('merge', '--ff-only', $remoteHead) | Out-Null

    if ($changedFiles -contains 'apps/plugin-station/requirements.txt') {
        & (Join-Path $repoRoot 'scripts\bootstrap.ps1') | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Python environment update failed.' }
    }
    $helperChanged = @($changedFiles | Where-Object {
        $_ -like 'helpers/*' -or $_ -eq 'scripts/build-helpers.ps1'
    }).Count -gt 0
    if ($helperChanged) {
        & (Join-Path $repoRoot 'scripts\build-helpers.ps1') | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Helper build failed.' }
    }
    $helpersUpdated = @()
    if ($helperChanged) {
        if (Install-BuiltHelper 'UpdreamClipboardCleaner.exe' 'UpdreamClipboardCleaner' 'UpdreamClipboardCleaner' $remoteHead) { $helpersUpdated += 'UpdreamClipboardCleaner' }
        if (Install-BuiltHelper 'CodexAnswerChime.exe' 'CodexAnswerChime' 'CodexAnswerChime' $remoteHead) { $helpersUpdated += 'CodexAnswerChime' }
        if (Install-BuiltHelper 'ArctisNova5BatteryMonitor.exe' 'ArctisNova5BatteryMonitor' 'ArctisNova5BatteryMonitor' $remoteHead) { $helpersUpdated += 'ArctisNova5BatteryMonitor' }
        Install-BuiltHelper 'ArctisNova5StartupGate.exe' 'ArctisNova5BatteryMonitor' '' $remoteHead | Out-Null
        if (Install-BuiltHelper 'EnvironmentDetector.exe' 'EnvironmentDetector' 'EnvironmentDetector' $remoteHead) { $helpersUpdated += 'EnvironmentDetector' }
    }

    $codexSystemProxyResult = $null
    $codexSystemProxyChanged = @($changedFiles | Where-Object {
        $_ -like 'apps/plugin-station/plugins/codex-system-proxy/*' -or
        $_ -eq 'apps/plugin-station/core/codex_system_proxy.py' -or
        $_ -eq 'scripts/ensure-codex-system-proxy.py'
    }).Count -gt 0
    if ($codexSystemProxyChanged) {
        $venvPython = Join-Path $repoRoot '.runtime\venv\Scripts\python.exe'
        if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
            $lines = @(& $venvPython (Join-Path $repoRoot 'scripts\ensure-codex-system-proxy.py'))
            if ($LASTEXITCODE -ne 0) { throw 'Codex system proxy synchronization failed.' }
            if ($lines.Count) { $codexSystemProxyResult = $lines[-1] | ConvertFrom-Json }
        }
    }

    $proxyBypassResult = $null
    $proxyBypassChanged = @($changedFiles | Where-Object {
        $_ -like 'apps/plugin-station/plugins/proxy-bypass/*' -or
        $_ -eq 'apps/plugin-station/core/clash_verge_bypass.py' -or
        $_ -eq 'scripts/ensure-proxy-bypass.py'
    }).Count -gt 0
    if ($proxyBypassChanged) {
        $venvPython = Join-Path $repoRoot '.runtime\venv\Scripts\python.exe'
        if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
            $lines = @(& $venvPython (Join-Path $repoRoot 'scripts\ensure-proxy-bypass.py'))
            if ($LASTEXITCODE -ne 0) { throw 'Proxy bypass synchronization failed.' }
            if ($lines.Count) { $proxyBypassResult = $lines[-1] | ConvertFrom-Json }
        }
    }

    Write-Result @{
        ok = $true; status = 'updated'; updated = $true; restartRequired = $true; source = 'GitHub'
        version = [string]$release.version; headCommit = $remoteHead; helpersUpdated = $helpersUpdated
        codexSystemProxy = $codexSystemProxyResult; proxyBypass = $proxyBypassResult
        message = "已从 GitHub 更新到 v$($release.version)，正在重启工具箱。"
    }
}
catch {
    $message = [string]$_.Exception.Message
    if ($message -match '(Authentication failed|could not read Username|Permission denied|Repository not found)') {
        $message = 'GitHub 访问失败。请检查公开仓库地址和网络；只有推送代码时才需要 GitHub 登录授权。'
    }
    Write-Result @{ ok = $false; status = 'error'; updated = $false; message = "更新失败：$message" } 1
}
