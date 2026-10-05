[CmdletBinding()]
param([ValidateSet('Stage','Finalize')][string]$Phase = 'Stage', [string]$BackupName = '')

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot '.runtime'))
$destination = Join-Path $runtimeRoot 'CompanyAIHelpers'
foreach ($ownedTarget in @($runtimeRoot,$destination)) {
    if ((Test-Path -LiteralPath $ownedTarget) -and
        ((Get-Item -LiteralPath $ownedTarget -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Runtime destination is a reparse point; migration stopped.'
    }
}
if (-not $BackupName) { $BackupName = 'runtime-move-' + (Get-Date -Format 'yyyyMMdd-HHmmss') }
if ($BackupName -notmatch '^runtime-move-[0-9-]+$') { throw 'Invalid backup name.' }
$backupRoot = Join-Path $runtimeRoot ('migration-backups\' + $BackupName)
if (-not ([IO.Path]::GetFullPath($backupRoot).StartsWith($runtimeRoot + '\', [StringComparison]::OrdinalIgnoreCase))) { throw 'Backup is outside runtime.' }
foreach ($path in @((Join-Path $runtimeRoot 'migration-backups'),$backupRoot)) {
    if ((Test-Path -LiteralPath $path) -and
        ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Backup destination is a reparse point; nothing was migrated.'
    }
}
if ((Test-Path -LiteralPath $backupRoot) -and
    @(Get-ChildItem -LiteralPath $backupRoot -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
    throw 'Reparse point in owned backup; migration stopped.'
}
New-Item -ItemType Directory -Path $destination,$backupRoot -Force | Out-Null
trap {
    [pscustomobject]@{phase=$Phase;error=$_.Exception.Message} | ConvertTo-Json -Compress |
        Set-Content -LiteralPath (Join-Path $backupRoot 'failure.json') -Encoding UTF8
    exit 1
}
$env:CODEXTOOLS_DATA_ROOT = $destination
$allowed = @('CodexTools','CodexSystemProxy','CodexNetworkDriveAccess','ProxyOverrideBypass','EnvironmentDetector',
    'UpdreamClipboardCleaner','WeTypeAweSunBridge','CodexAnswerChime','ArctisNova5BatteryMonitor','G435BatteryMonitor','UpdreamBridge','FFmpeg')
$local = [Environment]::GetFolderPath('LocalApplicationData')
$sources = @([pscustomobject]@{ Id='normal'; Path=(Join-Path $local 'CompanyAIHelpers') })
$packages = Join-Path $local 'Packages'
if (Test-Path -LiteralPath $packages) {
    foreach ($package in (Get-ChildItem -LiteralPath $packages -Directory -Filter 'OpenAI.Codex_*')) {
        $sources += [pscustomobject]@{ Id=$package.Name; Path=(Join-Path $package.FullName 'LocalCache\Local\CompanyAIHelpers') }
    }
}
function Assert-OwnedSource($source) {
    $absolute = [IO.Path]::GetFullPath($source.Path)
    if (-not $absolute.StartsWith($local + '\',[StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($absolute) -ne 'CompanyAIHelpers') { throw 'Invalid migration source.' }
    if (-not (Test-Path -LiteralPath $absolute)) { return }
    $ancestor = $absolute
    while ($ancestor -ne $local) {
        if ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Reparse point in migration source ancestry.'
        }
        $ancestor = Split-Path -Parent $ancestor
        if (-not $ancestor) { throw 'Migration source escaped its local root.' }
    }
    if ((Get-Item -LiteralPath $absolute -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Migration source is a reparse point.'
    }
    $unknown = @(Get-ChildItem -LiteralPath $absolute -Force | Where-Object { -not $_.PSIsContainer -or $_.Name -notin $allowed })
    if ($unknown.Count) { throw 'Source contains unrecognized files; nothing will be removed.' }
    if (@(Get-ChildItem -LiteralPath $absolute -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
        throw 'Reparse point found in migration source.'
    }
}
foreach ($source in $sources) { Assert-OwnedSource $source }
function Get-DataHash([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-','') }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}
function Is-GeneratedFile([string]$Relative) {
    [IO.Path]::GetExtension($Relative) -in @('.exe','.dll','.pdb') -or
    [IO.Path]::GetFileName($Relative) -in @('instance-version.txt','status.json','saved-restore-status.json','install-record.json')
}
if ($Phase -eq 'Stage') {
    # Two installations may contain different private profiles. Never silently
    # choose one, or overwrite a profile already present in the new workspace.
    $seenData = @{}
    foreach ($source in $sources) {
        if (-not (Test-Path -LiteralPath $source.Path)) { continue }
        foreach ($file in (Get-ChildItem -LiteralPath $source.Path -File -Recurse -Force)) {
            $relative = $file.FullName.Substring($source.Path.Length + 1)
            if (Is-GeneratedFile $relative) { continue }
            $hash = Get-DataHash $file.FullName
            if ($seenData.ContainsKey($relative) -and $seenData[$relative] -ne $hash) {
                throw 'Conflicting legacy private data; preserve both originals and contact maintenance.'
            }
            $seenData[$relative] = $hash
            $target = Join-Path $destination $relative
            if ((Test-Path -LiteralPath $target) -and (Get-DataHash $target) -ne $hash) {
                throw 'Workspace private data conflicts with legacy data; no profile was overwritten.'
            }
        }
    }
    foreach ($source in $sources) {
        if (-not (Test-Path -LiteralPath $source.Path)) { continue }
        $snapshot = Join-Path $backupRoot ('snapshots\' + $source.Id)
        New-Item -ItemType Directory -Path $snapshot -Force | Out-Null
        foreach ($item in (Get-ChildItem -LiteralPath $source.Path -Force)) {
            Copy-Item -LiteralPath $item.FullName -Destination $snapshot -Recurse -Force
            foreach ($file in (Get-ChildItem -LiteralPath $item.FullName -File -Recurse -Force)) {
                $relative = $file.FullName.Substring($source.Path.Length + 1)
                $target = Join-Path $destination $relative
                if (-not (Test-Path -LiteralPath $target)) {
                    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
                    Copy-Item -LiteralPath $file.FullName -Destination $target
                }
            }
        }
    }
    [pscustomobject]@{phase='staged'; destination=$destination; backup=$backupRoot} | ConvertTo-Json -Compress |
        Set-Content -LiteralPath (Join-Path $backupRoot 'stage-result.json') -Encoding UTF8
    exit 0
}
if (-not (Test-Path -LiteralPath (Join-Path $backupRoot 'snapshots'))) { throw 'Stage backup is required.' }

# Do not move data while the old toolbox can still write it. The user closes
# only the toolbox through its Complete Exit menu; Codex is never stopped.
$appPath = Join-Path $repoRoot 'apps\plugin-station\app.py'
$appPattern = [regex]::Escape($appPath) + '(?:"|\s|$)'
if (@(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -match $appPattern
}).Count) {
    throw 'Choose More > Complete Exit in the toolbox, then rerun Finalize. Do not exit Codex.'
}

# Stop only our exact old executables, not a process-name match and never Codex.
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$nasTaskName = 'CompanyAIHelpers.NasSavedMappings.' + $sid
$priorTask = Get-ScheduledTask -TaskName $nasTaskName -ErrorAction SilentlyContinue
$priorRestoreEnabled = $null -ne $priorTask
if ($priorTask) {
    [xml]$taskXml = Export-ScheduledTask -TaskName $nasTaskName
    if ($taskXml.Task.RegistrationInfo.Source -ne 'CompanyAIHelpers.NasSavedMappings/v1') { throw 'Unowned NAS task.' }
    $taskXml.Save((Join-Path $backupRoot 'nas-task-before.xml'))
    Stop-ScheduledTask -TaskName $nasTaskName
}
$running = @()
foreach ($process in (Get-CimInstance Win32_Process)) {
    if (-not $process.ExecutablePath) { continue }
    foreach ($source in $sources) {
        if ($process.ExecutablePath.StartsWith($source.Path + '\',[StringComparison]::OrdinalIgnoreCase)) {
            $relative = $process.ExecutablePath.Substring($source.Path.Length + 1)
            if (($relative -split '\\')[0] -notin $allowed) { throw 'Unknown executable in source.' }
            $running += [pscustomobject]@{Id=$process.ProcessId; Relative=$relative}
            # Stop-ScheduledTask may have already terminated this same worker.
            # Suppress only that benign exit race, not an actual stop failure.
            try {
                Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
            } catch {
                if (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue) { throw }
            }
            break
        }
    }
}
# Helpers have now stopped. Refresh files changed after staging only when the
# destination still equals our staged copy; never overwrite a newer profile.
foreach ($source in $sources) {
    if (-not (Test-Path -LiteralPath $source.Path)) { continue }
    foreach ($file in (Get-ChildItem -LiteralPath $source.Path -File -Recurse -Force)) {
        $relative = $file.FullName.Substring($source.Path.Length + 1)
        $target = Join-Path $destination $relative
        $snapshot = Join-Path $backupRoot ('snapshots\' + $source.Id + '\' + $relative)
        $sourceHash = Get-DataHash $file.FullName
        if ((Test-Path -LiteralPath $target) -and (Get-DataHash $target) -eq $sourceHash) { continue }
        if ((Test-Path -LiteralPath $target) -and (Is-GeneratedFile $relative)) { continue }
        if ((Test-Path -LiteralPath $target) -and
            (-not (Test-Path -LiteralPath $snapshot) -or (Get-DataHash $target) -ne (Get-DataHash $snapshot))) {
            throw 'Private data changed during migration; originals and backups were retained.'
        }
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
        if ((Get-DataHash $target) -ne $sourceHash) { throw 'Copied private file failed verification.' }
    }
}
$runPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$runBackups = @()
if (Test-Path -LiteralPath $runPath) {
    foreach ($property in (Get-ItemProperty -LiteralPath $runPath).PSObject.Properties) {
        if ($property.Name -like 'PS*' -or $property.Value -isnot [string]) { continue }
        $command = [string]$property.Value
        if ($property.Name -eq 'CompanyAIHelpers.NasSavedMappings') {
            foreach ($source in $sources) {
                if ($command.StartsWith('"' + $source.Path + '\',[StringComparison]::OrdinalIgnoreCase)) {
                    $priorRestoreEnabled = $true
                }
            }
        }
        $updated = $command
        foreach ($source in $sources) { $updated = $updated.Replace($source.Path + '\',$destination + '\') }
        if ($updated -ne $command) {
            $runBackups += @{name=$property.Name;command=$command}
            Set-ItemProperty -LiteralPath $runPath -Name $property.Name -Value $updated
        }
    }
}
$runBackups | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $backupRoot 'run-before.json') -Encoding UTF8
$shell = New-Object -ComObject WScript.Shell
$startup = [Environment]::GetFolderPath('Startup')
$startupSources = @($startup)
foreach ($source in $sources | Where-Object { $_.Id -ne 'normal' }) {
    $packageRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $source.Path))
    $startupSources += Join-Path $packageRoot 'LocalCache\Roaming\Microsoft\Windows\Start Menu\Programs\Startup'
}
$startupEntryIndex = 0
foreach ($folder in $startupSources | Select-Object -Unique) {
    $startupEntryIndex++
    if (-not (Test-Path -LiteralPath $folder)) { continue }
    foreach ($linkFile in (Get-ChildItem -LiteralPath $folder -Filter '*.lnk')) {
        $link = $shell.CreateShortcut($linkFile.FullName)
        $oldTarget = $link.TargetPath; $newTarget = $oldTarget
        foreach ($source in $sources) { $newTarget = $newTarget.Replace($source.Path + '\',$destination + '\') }
        if ($newTarget -eq $oldTarget) { continue }
        $linkBackup = Join-Path $backupRoot ('startup\' + $startupEntryIndex + '-' + $linkFile.Name)
        New-Item -ItemType Directory -Path (Split-Path -Parent $linkBackup) -Force | Out-Null
        Copy-Item -LiteralPath $linkFile.FullName -Destination $linkBackup
        $targetLink = Join-Path $startup $linkFile.Name
        if ($folder -ne $startup -and (Test-Path -LiteralPath $targetLink)) {
            $prior = $shell.CreateShortcut($targetLink)
            if ($prior.TargetPath -ne $oldTarget -and $prior.TargetPath -ne $newTarget) { throw 'Unrelated Startup shortcut conflict.' }
        }
        $newLink = $shell.CreateShortcut($targetLink)
        $newArguments=$link.Arguments; $newIcon=$link.IconLocation
        foreach ($source in $sources) {
            $newArguments=$newArguments.Replace($source.Path + '\',$destination + '\')
            $newIcon=$newIcon.Replace($source.Path + '\',$destination + '\')
        }
        $newLink.TargetPath=$newTarget; $newLink.Arguments=$newArguments
        $newLink.WorkingDirectory=Split-Path -Parent $newTarget
        $newLink.Description=$link.Description; $newLink.IconLocation=$newIcon
        $newLink.Save()
        if ($folder -ne $startup) { Move-Item -LiteralPath $linkFile.FullName -Destination ($linkBackup + '.original') }
    }
}

# Preserve an existing opt-in; migration must not enable NAS restore for a
# machine that never requested it (including installations without activation).
if ($priorRestoreEnabled) {
    $python = Join-Path $repoRoot '.runtime\venv\Scripts\python.exe'
    $payload = & $python -c "import sys;sys.path.insert(0,r'apps/plugin-station');from core.company_access import CompanyAccess;a=CompanyAccess();assert a.active();a.refresh_connector();assert a.active();print(a.payload_root())"
    if ($LASTEXITCODE -ne 0 -or -not $payload) { throw 'Migrated activation validation failed.' }
    $nas = Join-Path ([string]$payload) 'NasRemoteConnect.exe'
    $enabled = Start-Process -FilePath $nas -ArgumentList '--enable-saved-restore' -WindowStyle Hidden -PassThru -Wait
    if ($enabled.ExitCode -ne 0) { throw 'Migrated NAS startup configuration failed.' }
    Start-ScheduledTask -TaskName $nasTaskName
}
foreach ($source in $sources) {
    if (-not (Test-Path -LiteralPath $source.Path)) { continue }
    Assert-OwnedSource $source
    $archive = Join-Path $backupRoot ('originals\' + $source.Id)
    if (Test-Path -LiteralPath $archive) { throw 'Original archive already exists; use a new staged backup.' }
    New-Item -ItemType Directory -Path (Split-Path -Parent $archive) -Force | Out-Null
    # Both resolved targets were validated above; keep a recoverable original, never delete.
    Move-Item -LiteralPath $source.Path -Destination $archive
}
foreach ($process in $running | Where-Object { $_.Relative -notlike 'CodexTools\CompanyAccess\*' }) {
    $program = Join-Path $destination $process.Relative
    if (Test-Path -LiteralPath $program) { Start-Process -FilePath $program -WorkingDirectory (Split-Path -Parent $program) -WindowStyle Hidden }
}
[pscustomobject]@{phase='complete';destination=$destination;backup=$backupRoot;oldRootsRemain=@($sources | Where-Object {Test-Path -LiteralPath $_.Path}).Count} |
    ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $backupRoot 'result.json') -Encoding UTF8
