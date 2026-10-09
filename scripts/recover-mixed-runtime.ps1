[CmdletBinding()]
param([ValidateSet('Prepare','Finish','Rollback','Resume','RebindStartup','RebindStartupInteractive')][string]$Phase='Prepare',
      [Parameter(Mandatory=$true)][string]$RecoveryId, [switch]$Confirmed,
      [switch]$DesktopWorker, [switch]$NoLaunch, [string]$FailedBackupName='',
      [int]$ExpectedSessionId=-1)
# Explicit maintenance recovery. Never stop a process or sign out Windows.
$ErrorActionPreference='Stop'
if($Phase -notin @('Rollback','RebindStartup','RebindStartupInteractive')){throw '整目录迁移恢复已停用；只允许恢复已暂停的原自启。个人原件与备份保持原处。'}
$env:PSModulePath=Join-Path $PSHOME 'Modules'
if(-not $Confirmed){throw 'User authorization to prepare/recover these exact startup entries is required.'}
if($RecoveryId -notmatch '^[a-f0-9]{32}$'){throw 'Invalid recovery identity.'}
if($Phase -eq 'Resume' -and $FailedBackupName -notmatch '^runtime-move-[0-9-]+$'){throw 'Resume requires the verified failed Stage backup name.'}
$repo=Split-Path -Parent $PSScriptRoot
$runtime=Join-Path $repo '.runtime'
$folder=Join-Path $runtime ('runtime-recovery\'+$RecoveryId)
$active=Join-Path $runtime 'runtime-upgrade\active.json'
$statePath=Join-Path $folder 'state.json'
$runPath='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$legacy=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CompanyAIHelpers'
$startup=[Environment]::GetFolderPath('Startup')
$destination=Join-Path $runtime 'CompanyAIHelpers'
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$powershell=Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$taskName='CompanyAIHelpers.RuntimeRecovery.'+$sid+'.'+$RecoveryId+'.'+$Phase
$taskSource='CompanyAIHelpers.RuntimeRecovery/v1'
$session=[Diagnostics.Process]::GetCurrentProcess().SessionId
if($DesktopWorker -and $Phase -eq 'RebindStartupInteractive' -and ($ExpectedSessionId -lt 1 -or $session -ne $ExpectedSessionId)){throw 'Recovery must remain in the requesting Windows session.'}
$workerArguments='-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "'+$PSCommandPath+'" -Phase '+$Phase+' -RecoveryId '+$RecoveryId+' -Confirmed -DesktopWorker'
if($NoLaunch){$workerArguments+=' -NoLaunch'}
if($Phase -eq 'RebindStartupInteractive'){$workerArguments+=' -ExpectedSessionId '+$session}
if($Phase -eq 'Resume'){$workerArguments+=' -FailedBackupName '+$FailedBackupName}
$executables=@('UpdreamClipboardCleaner\UpdreamClipboardCleaner.exe','CodexAnswerChime\CodexAnswerChime.exe',
    'ArctisNova5BatteryMonitor\ArctisNova5BatteryMonitor.exe','ArctisNova5BatteryMonitor\ArctisNova5StartupGate.exe')
function Assert-Regular([string]$Path) {
    $current=[IO.Path]::GetFullPath($Path)
    while($current){
        if((Test-Path -LiteralPath $current) -and ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Recovery path contains a reparse point.'}
        $parent=Split-Path -Parent $current
        if($parent -eq $current){break};$current=$parent
    }
}
function Hash([string]$Path){(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash}
function Save-Json([string]$Path,$Value){
    Assert-Regular $Path
    $temporary=$Path+'.'+[Guid]::NewGuid().ToString('N')+'.tmp'
    [IO.File]::WriteAllText($temporary,($Value|ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($false))
    if([IO.File]::Exists($Path)){[IO.File]::Replace($temporary,$Path,(Join-Path $folder ([Guid]::NewGuid().ToString('N')+'.previous.json')))}else{[IO.File]::Move($temporary,$Path)}
}
function Owned-Relative([string]$Path){
    foreach($relative in $executables){
        if([string]::Equals($Path,(Join-Path $legacy $relative),[StringComparison]::OrdinalIgnoreCase)){return $relative}
    }
    return $null
}
function Command-Target([string]$Command){
    if($Command -match '^\s*(?:"(?<exe>[^"]+)"|(?<exe>[^\s"]+))'){return $Matches.exe}
    return ''
}
function Read-OptionalRunValue([string]$Path,[string]$Name){
    if(-not (Test-Path -LiteralPath $Path)){return $null}
    $values=Get-ItemProperty -LiteralPath $Path
    $property=$values.PSObject.Properties[$Name]
    if($property){return $property.Value}
    return $null
}
function Restore-Startup($state,[bool]$Migrated){
    # Preflight all entries before changing any; never compare personal files.
    $shell=New-Object -ComObject WScript.Shell
    foreach($entry in @($state.runEntries)) {
        $relative=Owned-Relative (Command-Target $entry.command)
        if(-not $relative){throw 'Unapproved startup target.'}
        $target=if($Migrated){Join-Path $destination $relative}else{Join-Path $legacy $relative}
        Assert-Regular $target
        if(-not [IO.File]::Exists($target)){throw 'Public restoration target absent.'}
        $desired=$entry.command.Replace((Join-Path $legacy $relative),$target)
        $current=Read-OptionalRunValue $runPath $entry.name
        if($null -ne $current -and $current -ne $desired -and $current -ne $entry.command){throw 'Startup changed; none overwritten.'}
    }
    foreach($entry in @($state.links)) {
        $relative=Owned-Relative $entry.target
        $path=[IO.Path]::GetFullPath($entry.path)
        $copy=[IO.Path]::GetFullPath((Join-Path $folder $entry.backup))
        if(-not $relative -or [IO.Path]::GetDirectoryName($path) -ne $startup -or
            -not $copy.StartsWith($folder+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Unapproved shortcut backup.'}
        Assert-Regular $copy;Assert-Regular $path
        if((Hash $copy) -ne $entry.sha256){throw 'Public shortcut backup changed.'}
        $target=if($Migrated){Join-Path $destination $relative}else{$entry.target}
        Assert-Regular $target
        if(-not [IO.File]::Exists($target)){throw 'Public shortcut target absent.'}
        if([IO.File]::Exists($path) -and (Hash $path) -ne $entry.sha256){
            $current=$shell.CreateShortcut($path)
            if(-not $Migrated -or $current.TargetPath -ne $target -or $current.Arguments -ne $entry.arguments){throw 'Shortcut changed; none overwritten.'}
        }
    }
    # Validate every stored entry again; JSON cannot authorize arbitrary paths.
    foreach($entry in @($state.runEntries)){
        $relative=Owned-Relative (Command-Target $entry.command)
        if(-not $relative){throw 'Startup backup is outside the approved components.'}
        $target=if($Migrated){Join-Path $destination $relative}else{Join-Path $legacy $relative}
        Assert-Regular $target
        if(-not [IO.File]::Exists($target)){throw 'Restoration target is absent; backup retained.'}
        $command=$entry.command.Replace((Join-Path $legacy $relative),$target)
        $current=Read-OptionalRunValue $runPath $entry.name
        if($null -ne $current -and $current -ne $command -and $current -ne $entry.command){throw 'Startup changed after preparation; no value overwritten.'}
        Set-ItemProperty -LiteralPath $runPath -Name $entry.name -Value $command
    }
    $shell=New-Object -ComObject WScript.Shell
    foreach($entry in @($state.links)){
        $relative=Owned-Relative $entry.target
        $path=[IO.Path]::GetFullPath($entry.path)
        $copy=[IO.Path]::GetFullPath((Join-Path $folder $entry.backup))
        if(-not $relative -or [IO.Path]::GetExtension($path) -ne '.lnk' -or [IO.Path]::GetDirectoryName($path) -ne $startup -or
           -not $copy.StartsWith($folder+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Shortcut backup scope changed.'}
        Assert-Regular $path;Assert-Regular $copy
        if((Hash $copy) -ne $entry.sha256){throw 'Shortcut backup differs.'}
        $target=if($Migrated){Join-Path $destination $relative}else{$entry.target}
        Assert-Regular $target
        if(-not [IO.File]::Exists($target)){throw 'Shortcut target is absent; backup retained.'}
        if([IO.File]::Exists($path)){
            if((Hash $path) -ne $entry.sha256){
                $existing=$shell.CreateShortcut($path)
                if(-not $Migrated -or $existing.TargetPath -ne $target -or $existing.Arguments -ne $entry.arguments){throw 'Shortcut changed after preparation.'}
            }
        }
        if(-not $Migrated){[IO.File]::Copy($copy,$path,$true);continue}
        $link=$shell.CreateShortcut($path)
        $link.TargetPath=$target;$link.Arguments=$entry.arguments
        $link.WorkingDirectory=$entry.workingDirectory.Replace($legacy+'\',$destination+'\')
        $link.Description=$entry.description;$link.IconLocation=$entry.iconLocation.Replace($legacy+'\',$destination+'\')
        $link.Save()
    }
}
foreach($path in @($runtime,$folder,$active,$statePath,$legacy,$startup)){Assert-Regular $path}
[IO.Directory]::CreateDirectory($folder)|Out-Null
$receipt=Join-Path $folder ('receipt-'+$Phase+'.json')
if(-not $DesktopWorker -and $Phase -eq 'RebindStartupInteractive'){
    if($session -lt 1){throw 'An interactive Windows session is required.'}
    if([IO.File]::Exists($receipt)){throw 'This interactive recovery already has a receipt; preserve it and do not repeat.'}
    # Explorer launches in the interactive desktop; no task registration or elevation.
    $desktopShell=New-Object -ComObject Shell.Application
    $desktopShell.ShellExecute($powershell,$workerArguments,$repo,'open',0)
    $deadline=[DateTime]::UtcNow.AddSeconds(50)
    while(-not [IO.File]::Exists($receipt) -and [DateTime]::UtcNow -lt $deadline){Start-Sleep -Milliseconds 200}
    if(-not [IO.File]::Exists($receipt)){throw 'Interactive recovery has not acknowledged completion; do not repeat or terminate it.'}
    $result=[IO.File]::ReadAllText($receipt)|ConvertFrom-Json
    $result|ConvertTo-Json -Compress
    if(-not $result.ok){exit 1};exit 0
}
if(-not $DesktopWorker){
    $scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$tasks=$scheduler.GetFolder('\')
    $definition=$scheduler.NewTask(0)
    $definition.RegistrationInfo.Source=$taskSource
    $definition.Principal.UserId=$sid;$definition.Principal.LogonType=3;$definition.Principal.RunLevel=0
    $definition.Settings.ExecutionTimeLimit='PT0S';$definition.Settings.AllowDemandStart=$true
    $definition.Settings.DisallowStartIfOnBatteries=$false;$definition.Settings.StopIfGoingOnBatteries=$false
    $action=$definition.Actions.Create(0);$action.Path=$powershell;$action.Arguments=$workerArguments;$action.WorkingDirectory=$repo
    if([IO.File]::Exists($receipt)){throw 'This recovery phase already has a receipt; inspect it before repeating.'}
    $task=$tasks.RegisterTaskDefinition($taskName,$definition,2,$sid,$null,3,$null)
    $task.Run($null)|Out-Null
    $deadline=[DateTime]::UtcNow.AddSeconds(50)
    while(-not [IO.File]::Exists($receipt) -and [DateTime]::UtcNow -lt $deadline){
        $observed=$tasks.GetTask($taskName)
        if($observed.State -eq 3 -and $observed.LastTaskResult -eq -2147024891){
            throw 'Desktop recovery task was denied permission before starting; startup and originals retained.'
        }
        Start-Sleep -Milliseconds 200
    }
    if(-not [IO.File]::Exists($receipt)){throw 'Desktop recovery has not acknowledged completion; do not terminate or repeat it.'}
    $result=[IO.File]::ReadAllText($receipt)|ConvertFrom-Json
    $result|ConvertTo-Json -Compress
    if(-not $result.ok){exit 1};exit 0
}
$mutex=[Threading.Mutex]::new($false,('Local\CompanyAIHelpers.RuntimeRecovery.'+$RecoveryId))
if(-not $mutex.WaitOne(0)){throw 'Another recovery worker owns this operation.'}
$state=$null
try {
    $state=[IO.File]::ReadAllText($statePath)|ConvertFrom-Json
    if($state.recoveryId -ne $RecoveryId -or $state.ownerSid -ne $sid -or $state.status -ne 'prepared'){throw 'Recovery ownership/state does not match.'}
    if((Hash $active) -ne $state.originalActiveSha256){throw 'Active migration changed; original backup retained.'}
    if ($Phase -in @('RebindStartup','RebindStartupInteractive')) {
        # Build/copy only the approved public programs. No private tree migration.
        & (Join-Path $PSScriptRoot 'build-helpers.ps1') | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Public helper build failed; startup retained.' }
        foreach ($relative in $executables) {
            $source = Join-Path $repo ('artifacts\helpers\' + [IO.Path]::GetFileName($relative))
            $target = Join-Path $destination $relative
            Assert-Regular $source;Assert-Regular $target
            if (-not [IO.File]::Exists($source)) { throw 'Approved public program artifact missing.' }
            $changed = -not [IO.File]::Exists($target) -or (Hash $source) -ne (Hash $target)
            $owned = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and
                ([string]::Equals($_.ExecutablePath,(Join-Path $legacy $relative),[StringComparison]::OrdinalIgnoreCase) -or
                 [string]::Equals($_.ExecutablePath,$target,[StringComparison]::OrdinalIgnoreCase)) })
            if ($owned.Count) { throw 'Approved old helper still running; exit it normally. No process stopped.' }
            if ($changed) {
                [IO.Directory]::CreateDirectory((Split-Path -Parent $target)) | Out-Null
                $temporary=$target+'.'+[Guid]::NewGuid().ToString('N')+'.installing'
                [IO.File]::Copy($source,$temporary,$false)
                Move-Item -LiteralPath $temporary -Destination $target -Force
            }
        }
        Restore-Startup $state $true
        $state.status='rebound'
    } else {
        Restore-Startup $state $false
        $state.status='rolled-back'
    }
    Save-Json $statePath $state
    Save-Json $receipt ([pscustomobject]@{ok=$true;phase=$Phase;recoveryId=$RecoveryId;status=$state.status;originalFailurePreserved=$true})
}catch{
    Save-Json $receipt ([pscustomobject]@{ok=$false;phase=$Phase;recoveryId=$RecoveryId;error=$_.Exception.Message;originalsPreserved=$true})
}finally{
    $mutex.ReleaseMutex();$mutex.Dispose()
    try{
        $scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$tasks=$scheduler.GetFolder('\');$task=$tasks.GetTask($taskName)
        if($task.Definition.RegistrationInfo.Source -eq $taskSource -and $task.Definition.Actions.Item(1).Path -eq $powershell -and
            $task.Definition.Actions.Item(1).Arguments -eq $workerArguments){$tasks.DeleteTask($taskName,0)}
    }catch{}
}
