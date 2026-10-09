[CmdletBinding()]
param([ValidateSet('Prepare','Finish','Rollback')][string]$Phase='Prepare',
      [Parameter(Mandatory=$true)][string]$RecoveryId, [switch]$Confirmed,
      [switch]$DesktopWorker, [switch]$NoLaunch)
# Explicit maintenance recovery. Never stop a process or sign out Windows.
$ErrorActionPreference='Stop'
$env:PSModulePath=$null
if(-not $Confirmed){throw 'User authorization to prepare/recover these exact startup entries is required.'}
if($RecoveryId -notmatch '^[a-f0-9]{32}$'){throw 'Invalid recovery identity.'}
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
$workerArguments='-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "'+$PSCommandPath+'" -Phase '+$Phase+' -RecoveryId '+$RecoveryId+' -Confirmed -DesktopWorker'
if($NoLaunch){$workerArguments+=' -NoLaunch'}
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
function Restore-Startup($state,[bool]$Migrated){
    # Validate every stored entry again; JSON cannot authorize arbitrary paths.
    foreach($entry in @($state.runEntries)){
        $relative=Owned-Relative (Command-Target $entry.command)
        if(-not $relative){throw 'Startup backup is outside the approved components.'}
        $target=if($Migrated){Join-Path $destination $relative}else{Join-Path $legacy $relative}
        Assert-Regular $target
        if(-not [IO.File]::Exists($target)){throw 'Restoration target is absent; backup retained.'}
        $command=$entry.command.Replace((Join-Path $legacy $relative),$target)
        $current=Get-ItemPropertyValue -LiteralPath $runPath -Name $entry.name -ErrorAction SilentlyContinue
        if($current -and $current -ne $command -and $current -ne $entry.command){throw 'Startup changed after preparation; no value overwritten.'}
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
            if((Hash $path) -ne $entry.sha256){throw 'Shortcut changed after preparation.'}
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
    while(-not [IO.File]::Exists($receipt) -and [DateTime]::UtcNow -lt $deadline){Start-Sleep -Milliseconds 200}
    if(-not [IO.File]::Exists($receipt)){throw 'Desktop recovery has not acknowledged completion; do not terminate or repeat it.'}
    $result=[IO.File]::ReadAllText($receipt)|ConvertFrom-Json
    $result|ConvertTo-Json -Compress
    if(-not $result.ok){exit 1};exit 0
}
$mutex=[Threading.Mutex]::new($false,('Local\CompanyAIHelpers.RuntimeRecovery.'+$RecoveryId))
if(-not $mutex.WaitOne(0)){throw 'Another recovery worker owns this operation.'}
$state=$null
try {
    if($Phase -eq 'Prepare'){
        if([IO.File]::Exists($statePath)){throw 'A recovery already exists; inspect its state before repeating.'}
        $originalActiveHash=Hash $active
        $old=[IO.File]::ReadAllText($active)|ConvertFrom-Json
        if($old.state -ne 'failed' -or $old.requestId -ne $RecoveryId -or $old.backupName -notmatch '^runtime-move-[0-9-]+$'){throw 'Only the documented failed request can be prepared.'}
        $oldBackup=Join-Path $runtime ('migration-backups\'+$old.backupName)
        Assert-Regular $oldBackup
        $failurePath=Join-Path $oldBackup 'failure.json';Assert-Regular $failurePath
        $failure=[IO.File]::ReadAllText($failurePath)|ConvertFrom-Json
        if($failure.phase -ne 'Stage' -or $failure.error -ne 'Source contains unrecognized files; nothing will be removed.' -or
            [IO.File]::Exists((Join-Path $oldBackup 'stage-result.json')) -or [IO.File]::Exists((Join-Path $oldBackup 'result.json'))){throw 'Failure is outside the reviewed pre-Stage recovery case.'}
        $migration=Join-Path $PSScriptRoot 'migrate-workspace-runtime.ps1'
        Assert-Regular $migration
        if(-not [IO.File]::ReadAllText($migration).Contains('function Get-OwnedSourceItems')){throw 'Update to the partial-component migration repair first.'}
        $oldTaskName='CompanyAIHelpers.RuntimeMigration.'+$sid+'.'+$RecoveryId
        $scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect()
        if(@($scheduler.GetFolder('\').GetTasks(1)|Where-Object{$_.Name -eq $oldTaskName}).Count){throw 'Old request still has a task; preparation stopped.'}
        $pattern=[regex]::Escape((Join-Path $PSScriptRoot 'auto-migrate-runtime.ps1'))
        if(@(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'"|Where-Object{$_.CommandLine -match $pattern}).Count){throw 'Old migration worker still exists.'}
        $runs=@();$links=@();$shell=New-Object -ComObject WScript.Shell
        if(Test-Path -LiteralPath $runPath){
            foreach($property in (Get-ItemProperty -LiteralPath $runPath).PSObject.Properties){
                if($property.Name -like 'PS*' -or $property.Value -isnot [string]){continue}
                $relative=Owned-Relative (Command-Target $property.Value)
                if($relative){$runs += [pscustomobject]@{name=$property.Name;command=$property.Value}}
            }
        }
        $startupLinks=if([IO.Directory]::Exists($startup)){@(Get-ChildItem -LiteralPath $startup -Filter '*.lnk' -File)}else{@()}
        foreach($file in $startupLinks){
            Assert-Regular $file.FullName
            $link=$shell.CreateShortcut($file.FullName)
            if(-not (Owned-Relative $link.TargetPath)){continue}
            $name=[Guid]::NewGuid().ToString('N')+'.lnk'
            [IO.File]::Copy($file.FullName,(Join-Path $folder $name),$false)
            $links += [pscustomobject]@{path=$file.FullName;backup=$name;sha256=(Hash $file.FullName);target=$link.TargetPath;
                arguments=$link.Arguments;workingDirectory=$link.WorkingDirectory;iconLocation=$link.IconLocation;description=$link.Description}
        }
        if((Hash $active) -ne $originalActiveHash){throw 'Active migration changed before preparation.'}
        [IO.File]::Copy($active,(Join-Path $folder 'failed-active-original.json'),$false)
        if((Hash (Join-Path $folder 'failed-active-original.json')) -ne $originalActiveHash){throw 'Original failed record copy differs.'}
        $state=[pscustomobject]@{schemaVersion=1;recoveryId=$RecoveryId;status='preparing';ownerSid=$sid;
            originalActiveSha256=$originalActiveHash;migrationSha256=(Hash $migration);runEntries=$runs;links=$links}
        Save-Json $statePath $state
        if((Hash $active) -ne $originalActiveHash){throw 'Active migration changed before startup pause.'}
        foreach($entry in $runs){
            if((Get-ItemPropertyValue -LiteralPath $runPath -Name $entry.name) -ne $entry.command){throw 'Run entry changed before pause.'}
            Remove-ItemProperty -LiteralPath $runPath -Name $entry.name
        }
        foreach($entry in $links){
            if((Hash $entry.path) -ne $entry.sha256){throw 'Shortcut changed before pause.'}
            # Resolved source is a direct Startup child; destination is the
            # verified operation folder. Keep the original, never delete it.
            $paused=[IO.Path]::GetFullPath((Join-Path $folder ('paused-'+$entry.backup)))
            if([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($entry.path)) -ne $startup -or
                -not $paused.StartsWith($folder+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Pause move escaped its scope.'}
            [IO.File]::Move($entry.path,$paused)
        }
        $state.status='prepared';Save-Json $statePath $state
        Save-Json $receipt ([pscustomobject]@{ok=$true;phase=$Phase;recoveryId=$RecoveryId;pausedRunCount=$runs.Count;pausedShortcutCount=$links.Count;
            nextAction='Save work and sign out of Windows normally; after signing in, authorize Finish in Codex. No process was stopped.'})
    }else{
        $state=[IO.File]::ReadAllText($statePath)|ConvertFrom-Json
        if($state.recoveryId -ne $RecoveryId -or $state.ownerSid -ne $sid -or $state.status -ne 'prepared'){throw 'Recovery ownership/state does not match.'}
        if((Hash $active) -ne $state.originalActiveSha256){throw 'Active migration changed; original backup retained.'}
        if($Phase -eq 'Rollback'){
            Restore-Startup $state $false
            $state.status='rolled-back';Save-Json $statePath $state
        }else{
            $migration=Join-Path $PSScriptRoot 'migrate-workspace-runtime.ps1'
            if((Hash $migration) -ne $state.migrationSha256){throw 'Prepared migrator changed; do not resume with different code.'}
            $backupName='runtime-move-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[DateTime]::UtcNow.Ticks
            foreach($migrationPhase in @('Stage','Finalize')){
                & $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $migration -Phase $migrationPhase -BackupName $backupName -NoForce | Out-Null
                if($LASTEXITCODE -ne 0){throw ('Controlled migration failed: '+$migrationPhase+'. Originals and both backups retained.')}
            }
            $result=[IO.File]::ReadAllText((Join-Path $runtime ('migration-backups\'+$backupName+'\result.json')))|ConvertFrom-Json
            if($result.phase -ne 'complete' -or $result.oldRootsRemain -ne 0){throw 'Owned-component migration did not verify.'}
            Restore-Startup $state $true
            if((Hash $active) -ne $state.originalActiveSha256){throw 'Active migration changed before completion.'}
            $complete=[pscustomobject]@{schemaVersion=1;requestId=[Guid]::NewGuid().ToString('N');previousRequestId=$RecoveryId;
                backupName=$backupName;state='complete';updatedAt=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds();maintenanceRecovery=$true}
            Save-Json $active $complete
            $state.status='complete';$state|Add-Member -NotePropertyName completedBackupName -NotePropertyValue $backupName
            Save-Json $statePath $state
            if(-not $NoLaunch){
                foreach($relative in @('UpdreamClipboardCleaner\UpdreamClipboardCleaner.exe','CodexAnswerChime\CodexAnswerChime.exe','ArctisNova5BatteryMonitor\ArctisNova5StartupGate.exe')){
                    $wasEnabled=@($state.runEntries|Where-Object{(Owned-Relative (Command-Target $_.command)) -eq $relative}).Count -gt 0 -or
                        @($state.links|Where-Object{(Owned-Relative $_.target) -eq $relative -or
                            ($_.target -eq (Join-Path $legacy 'ArctisNova5BatteryMonitor\ArctisNova5BatteryMonitor.exe') -and $relative -like '*StartupGate.exe')}).Count -gt 0
                    $program=Join-Path $destination $relative
                    if($wasEnabled -and [IO.File]::Exists($program)){Start-Process -FilePath $program -WorkingDirectory (Split-Path -Parent $program) -WindowStyle Hidden}
                }
                Start-Process -FilePath (Join-Path $runtime 'venv\Scripts\pythonw.exe') -ArgumentList ('"'+(Join-Path $repo 'apps\plugin-station\app.py')+'"') -WorkingDirectory $repo -WindowStyle Hidden
            }
        }
        Save-Json $receipt ([pscustomobject]@{ok=$true;phase=$Phase;recoveryId=$RecoveryId;status=$state.status;originalFailurePreserved=$true})
    }
}catch{
    if($Phase -eq 'Prepare' -and $state){try{Restore-Startup $state $false}catch{}}
    Save-Json $receipt ([pscustomobject]@{ok=$false;phase=$Phase;recoveryId=$RecoveryId;error=$_.Exception.Message;originalsPreserved=$true})
}finally{
    $mutex.ReleaseMutex();$mutex.Dispose()
    try{
        $scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$tasks=$scheduler.GetFolder('\');$task=$tasks.GetTask($taskName)
        if($task.Definition.RegistrationInfo.Source -eq $taskSource -and $task.Definition.Actions.Item(1).Path -eq $powershell -and
            $task.Definition.Actions.Item(1).Arguments -eq $workerArguments){$tasks.DeleteTask($taskName,0)}
    }catch{}
}
