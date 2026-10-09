[CmdletBinding()]
param([ValidateSet('Prepare','Finish','Rollback','Resume','RebindStartup','RebindStartupInteractive','RebindStartupLocal')][string]$Phase='Prepare',
      [Parameter(Mandatory=$true)][string]$RecoveryId, [switch]$Confirmed,
      [switch]$DesktopWorker, [switch]$NoLaunch, [string]$FailedBackupName='',
      [int]$ExpectedSessionId=-1, [string]$AttemptId='')
# Explicit maintenance recovery. Never stop a process or sign out Windows.
$ErrorActionPreference='Stop'
if($Phase -notin @('Rollback','RebindStartup','RebindStartupInteractive','RebindStartupLocal')){throw '整目录迁移恢复已停用；只允许恢复已暂停的原自启。个人原件与备份保持原处。'}
$env:PSModulePath=Join-Path $PSHOME 'Modules'
if(-not $Confirmed){throw 'User authorization to prepare/recover these exact startup entries is required.'}
if($RecoveryId -notmatch '^[a-f0-9]{32}$'){throw 'Invalid recovery identity.'}
if($Phase -eq 'RebindStartupLocal' -and $AttemptId -notmatch '^[a-f0-9]{32}$'){throw 'Local recovery requires a fresh attempt identity.'}
if($Phase -ne 'RebindStartupLocal' -and $AttemptId){throw 'Attempt identity is only valid for local recovery.'}
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
if($DesktopWorker -and $Phase -in @('RebindStartupInteractive','RebindStartupLocal') -and ($ExpectedSessionId -lt 1 -or $session -ne $ExpectedSessionId)){throw 'Recovery must remain in the requesting Windows session.'}
$workerArguments='-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "'+$PSCommandPath+'" -Phase '+$Phase+' -RecoveryId '+$RecoveryId+' -Confirmed -DesktopWorker'
if($NoLaunch){$workerArguments+=' -NoLaunch'}
if($Phase -in @('RebindStartupInteractive','RebindStartupLocal')){$workerArguments+=' -ExpectedSessionId '+$session}
if($Phase -eq 'RebindStartupLocal'){$workerArguments+=' -AttemptId '+$AttemptId}
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
    if($Path.StartsWith('HKCU:\',[StringComparison]::OrdinalIgnoreCase)){
        $key=[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($Path.Substring(6))
        if($null -eq $key){return $null}
        try{return $key.GetValue($Name,$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)}finally{$key.Dispose()}
    }
    if(-not (Test-Path -LiteralPath $Path)){return $null}
    $values=Get-ItemProperty -LiteralPath $Path
    $property=$values.PSObject.Properties[$Name]
    if($property){return $property.Value}
    return $null
}
function Write-RunValue([string]$Name,[string]$Original,[string]$Desired){
    # Use the existing toolbox runtime; direct PowerShell writes may be denied
    # even when the same approved startup operation works in the toolbox.
    $python=Join-Path $repo '.runtime\venv\Scripts\python.exe'
    $writer=Join-Path $PSScriptRoot 'restore-startup-run.py'
    Assert-Regular $python;Assert-Regular $writer
    if(-not [IO.File]::Exists($python) -or -not [IO.File]::Exists($writer)){throw 'Toolbox startup writer is absent.'}
    $entries=@($state.runEntries)
    $matching=@(for($index=0;$index -lt $entries.Count;$index++){
        if($entries[$index].name -ceq $Name -and $entries[$index].command -ceq $Original){$index}
    })
    if($matching.Count -ne 1){throw 'Run write must match one prepared entry.'}
    $mode=if($Original -ceq $Desired){'legacy'}else{'current'}
    $info=[Diagnostics.ProcessStartInfo]::new()
    $info.FileName=$python
    $info.Arguments='"'+$writer+'" --recovery-id '+$RecoveryId+' --session '+$session+' --restore-to '+$mode+' --entry-index '+$matching[0]
    $info.UseShellExecute=$false;$info.CreateNoWindow=$true;$info.WindowStyle='Hidden'
    $info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
    $process=[Diagnostics.Process]::Start($info)
    try{
        $output=$process.StandardOutput.ReadToEnd();$errorOutput=$process.StandardError.ReadToEnd();$process.WaitForExit()
        $result=$output|ConvertFrom-Json
        if($process.ExitCode -ne 0 -or $result.ok -ne $true){
            if($result.failureCategory -eq 'access_denied'){throw [UnauthorizedAccessException]::new('Approved Run write denied.')}
            throw 'Approved Run write did not complete.'
        }
    }finally{$process.Dispose()}
}
function Set-ValidatedRunValue([string]$Name,[string]$Original,[string]$Desired){
    $current=Read-OptionalRunValue $runPath $Name
    if($null -ne $current -and $current -ne $Desired -and $current -ne $Original){throw 'Startup changed at write time; no value overwritten.'}
    if($current -ceq $Desired){return}
    Write-RunValue $Name $Original $Desired
    if((Read-OptionalRunValue $runPath $Name) -cne $Desired){throw 'Run restoration readback failed.'}
}
function Restore-Startup($state,[bool]$Migrated){
    # Preflight all entries before changing any; never compare personal files.
    $shell=New-Object -ComObject WScript.Shell
    foreach($entry in @($state.runEntries)) {
        $script:recoveryOperation='startup_run'
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
        $script:recoveryOperation='startup_shortcut'
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
        $script:recoveryOperation='startup_run'
        $relative=Owned-Relative (Command-Target $entry.command)
        if(-not $relative){throw 'Startup backup is outside the approved components.'}
        $target=if($Migrated){Join-Path $destination $relative}else{Join-Path $legacy $relative}
        Assert-Regular $target
        if(-not [IO.File]::Exists($target)){throw 'Restoration target is absent; backup retained.'}
        $command=$entry.command.Replace((Join-Path $legacy $relative),$target)
        $current=Read-OptionalRunValue $runPath $entry.name
        if($null -ne $current -and $current -ne $command -and $current -ne $entry.command){throw 'Startup changed after preparation; no value overwritten.'}
        Set-ValidatedRunValue $entry.name $entry.command $command
    }
    $shell=New-Object -ComObject WScript.Shell
    foreach($entry in @($state.links)){
        $script:recoveryOperation='startup_shortcut'
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
if($Phase -eq 'RebindStartupLocal'){$receipt=Join-Path $folder ('receipt-'+$Phase+'-'+$AttemptId+'.json')}
function Write-ReceiptSummary($result){
    if($Phase -eq 'RebindStartupLocal'){
        $result|Select-Object ok,phase,operation,failureCategory,failureLine,status|ConvertTo-Json -Compress
    }else{$result|ConvertTo-Json -Compress}
}
if([IO.File]::Exists($receipt)){throw 'This recovery attempt already has a receipt; preserve it and do not repeat.'}
if(-not $DesktopWorker -and $Phase -in @('RebindStartupInteractive','RebindStartupLocal')){
    if($session -lt 1){throw 'An interactive Windows session is required.'}
    if([IO.File]::Exists($receipt)){throw 'This interactive recovery already has a receipt; preserve it and do not repeat.'}
    # Explorer launches in the interactive desktop; no task registration or elevation.
    $desktopShell=New-Object -ComObject Shell.Application
    $desktopShell.ShellExecute($powershell,$workerArguments,$repo,'open',0)
    $deadline=[DateTime]::UtcNow.AddSeconds(50)
    while(-not [IO.File]::Exists($receipt) -and [DateTime]::UtcNow -lt $deadline){Start-Sleep -Milliseconds 200}
    if(-not [IO.File]::Exists($receipt)){throw 'Interactive recovery has not acknowledged completion; do not repeat or terminate it.'}
    $result=[IO.File]::ReadAllText($receipt)|ConvertFrom-Json
    Write-ReceiptSummary $result
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
$script:recoveryOperation='recovery_record'
try {
    $state=[IO.File]::ReadAllText($statePath)|ConvertFrom-Json
    if($state.recoveryId -ne $RecoveryId -or $state.ownerSid -ne $sid -or $state.status -ne 'prepared'){throw 'Recovery ownership/state does not match.'}
    if((Hash $active) -ne $state.originalActiveSha256){throw 'Active migration changed; original backup retained.'}
    if ($Phase -in @('RebindStartup','RebindStartupInteractive','RebindStartupLocal')) {
        # Build/copy only the approved public programs. No private tree migration.
        $script:recoveryOperation='public_build'
        if($Phase -eq 'RebindStartupLocal'){
            & (Join-Path $PSScriptRoot 'build-helpers.ps1') -Scope StartupRecovery | Out-Null
        }else{& (Join-Path $PSScriptRoot 'build-helpers.ps1') | Out-Null}
        if ($LASTEXITCODE -ne 0) { throw 'Public helper build failed; startup retained.' }
        foreach ($relative in $executables) {
            $script:recoveryOperation='public_install'
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
                if($Phase -eq 'RebindStartupLocal' -and [IO.File]::Exists($target)){
                    $programBackup=Join-Path $folder ('public-programs\'+$AttemptId+'\'+[IO.Path]::GetFileName($target))
                    Assert-Regular $programBackup
                    [IO.Directory]::CreateDirectory((Split-Path -Parent $programBackup))|Out-Null
                    [IO.File]::Copy($target,$programBackup,$false)
                }
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
    $script:recoveryOperation='recovery_record'
    Save-Json $statePath $state
    Save-Json $receipt ([pscustomobject]@{ok=$true;phase=$Phase;recoveryId=$RecoveryId;status=$state.status;originalFailurePreserved=$true})
}catch{
    $category='operation_failed'
    $exception=$_.Exception
    while($exception){
        if($exception -is [UnauthorizedAccessException] -or $exception -is [Security.SecurityException]){$category='access_denied';break}
        $exception=$exception.InnerException
    }
    Save-Json $receipt ([pscustomobject]@{ok=$false;phase=$Phase;recoveryId=$RecoveryId;operation=$script:recoveryOperation;failureCategory=$category;failureLine=$_.InvocationInfo.ScriptLineNumber;error=$_.Exception.Message;localStack=$_.ScriptStackTrace;originalsPreserved=$true})
}finally{
    $mutex.ReleaseMutex();$mutex.Dispose()
    try{
        $scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$tasks=$scheduler.GetFolder('\');$task=$tasks.GetTask($taskName)
        if($task.Definition.RegistrationInfo.Source -eq $taskSource -and $task.Definition.Actions.Item(1).Path -eq $powershell -and
            $task.Definition.Actions.Item(1).Arguments -eq $workerArguments){$tasks.DeleteTask($taskName,0)}
    }catch{}
}
