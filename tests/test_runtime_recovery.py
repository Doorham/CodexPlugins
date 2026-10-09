"""Real desktop task recovery, with synthetic files, startup, and processes."""
import hashlib
import json
import os
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'


@unittest.skipUnless(os.name == 'nt' and PS.exists(), 'Windows desktop scheduler required')
class RuntimeRecoveryTests(unittest.TestCase):
    def fixture(self, repo, real_registry=False):
        # The real worker deliberately uses a standard desktop token. Grant
        # this synthetic directory to the SID even if Python is elevated and
        # mkdtemp inherited only an Administrators ACL.
        quoted=str(repo).replace("'", "''")
        self.ps_command("$p='"+quoted+"';$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User;"+
            "$a=[IO.Directory]::GetAccessControl($p);"+
            "$rule=[Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow');"+
            "$a.AddAccessRule($rule);[IO.Directory]::SetAccessControl($p,$a)")
        scripts = repo / 'scripts'
        scripts.mkdir()
        local = repo / 'synthetic-local'
        old = local / 'CompanyAIHelpers'
        startup = repo / 'synthetic-startup'
        startup.mkdir()
        owned = old / 'CodexAnswerChime/CodexAnswerChime.exe'
        owned.parent.mkdir(parents=True)
        owned.write_bytes(b'Synthetic non-executable helper')
        private = old / 'CodexTools/PrivatePlugins/Fixture/settings.json'
        private.parent.mkdir(parents=True)
        private.write_bytes(b'{"fixture":1}')
        for name in ('MigrationBackups', 'WeTypeAweSunDirectTrial', 'WorkBuddyDailyPoints'):
            path = old / name / 'preserved.bin'
            path.parent.mkdir()
            path.write_bytes(('synthetic-' + name).encode())
        foreign = old / 'WorkBuddyDailyPoints/WorkBuddyDailyPoints.exe'
        run = repo / 'synthetic-run.json'
        run.write_text(json.dumps({'Owned': '"' + str(owned) + '" --synthetic',
                                  'Foreign': '"' + str(foreign) + '"'}))
        link = {'TargetPath': str(owned), 'Arguments': '--synthetic', 'WorkingDirectory': str(owned.parent),
                'IconLocation': str(owned) + ',0', 'Description': 'Fixture shortcut'}
        (startup / 'Owned.lnk').write_text(json.dumps(link))
        (startup / 'Foreign.lnk').write_text(json.dumps(dict(link, TargetPath=str(foreign))))
        recovery_id = uuid.uuid4().hex
        active = repo / '.runtime/runtime-upgrade/active.json'
        active.parent.mkdir(parents=True)
        active.write_text(json.dumps({'schemaVersion': 1, 'state': 'failed', 'requestId': recovery_id,
                                      'backupName': 'runtime-move-20000101-000000', 'resumeAttemptedAt': 1}))
        backup = repo / '.runtime/migration-backups/runtime-move-20000101-000000'
        backup.mkdir(parents=True)
        (backup / 'failure.json').write_text(json.dumps({'phase': 'Stage',
                    'error': 'Source contains unrecognized files; nothing will be removed.'}))
        quote = lambda value: str(value).replace("'", "''")
        # The production COM scheduler is real; only startup/registry/process
        # providers are substituted. No actual Windows startup entry is touched.
        hooks = r"""
function Get-CimInstance { [pscustomobject]@{Name='WorkBuddyDailyPoints.exe';ExecutablePath='FOREIGN';ProcessId=0;CommandLine='synthetic'} }
function Get-ScheduledTask { return $null }
function Get-ItemProperty { [CmdletBinding()]param($LiteralPath)
 if($LiteralPath -like 'HKCU:\Software\CompanyAIHelpers.Tests.*'){return Microsoft.PowerShell.Management\Get-ItemProperty -LiteralPath $LiteralPath}
 [IO.File]::ReadAllText('RUNFILE')|ConvertFrom-Json
}
function Get-ItemPropertyValue { [CmdletBinding()]param($LiteralPath,$Name)
 if($LiteralPath -like 'HKCU:\Software\CompanyAIHelpers.Tests.*'){return Microsoft.PowerShell.Management\Get-ItemPropertyValue -LiteralPath $LiteralPath -Name $Name}
 $values=[IO.File]::ReadAllText('RUNFILE')|ConvertFrom-Json
 $property=$values.PSObject.Properties[$Name];if($property){return $property.Value};throw 'Missing registry value, matching Windows PowerShell 5.1'
}
function Set-ItemProperty { param($LiteralPath,$Name,$Value)
 if($LiteralPath -like 'HKCU:\Software\CompanyAIHelpers.Tests.*'){Microsoft.PowerShell.Management\Set-ItemProperty -LiteralPath $LiteralPath -Name $Name -Value $Value;return}
 $values=[IO.File]::ReadAllText('RUNFILE')|ConvertFrom-Json
 $values|Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
 [IO.File]::WriteAllText('RUNFILE',($values|ConvertTo-Json -Compress))
}
function Remove-ItemProperty { param($LiteralPath,$Name)
 if($LiteralPath -like 'HKCU:\Software\CompanyAIHelpers.Tests.*'){Microsoft.PowerShell.Management\Remove-ItemProperty -LiteralPath $LiteralPath -Name $Name;return}
 $values=[IO.File]::ReadAllText('RUNFILE')|ConvertFrom-Json
 $values.PSObject.Properties.Remove($Name)
 [IO.File]::WriteAllText('RUNFILE',($values|ConvertTo-Json -Compress))
}
function Stop-Process { throw 'Unexpected process termination' }
function Stop-ScheduledTask { throw 'Unexpected task termination' }
function Start-Process { throw 'Unexpected fixture launch' }
function New-Object { param($ComObject)
 if($ComObject -ne 'WScript.Shell'){return Microsoft.PowerShell.Utility\New-Object -ComObject $ComObject}
 $shell=[pscustomobject]@{}
 $shell|Add-Member -MemberType ScriptMethod -Name CreateShortcut -Value {
  param($path)
  if([IO.File]::Exists($path)){$link=[IO.File]::ReadAllText($path)|ConvertFrom-Json}
  else{$link=[pscustomobject]@{TargetPath='';Arguments='';WorkingDirectory='';IconLocation='';Description=''}}
  $link|Add-Member -NotePropertyName FixturePath -NotePropertyValue $path
  $link|Add-Member -MemberType ScriptMethod -Name Save -Value {
   $value=[ordered]@{};foreach($name in @('TargetPath','Arguments','WorkingDirectory','IconLocation','Description')){$value[$name]=$this.$name}
   [IO.File]::WriteAllText($this.FixturePath,($value|ConvertTo-Json -Compress))
  }
  return $link
 }
 return $shell
}
""".replace('FOREIGN', quote(foreign)).replace('RUNFILE', quote(run))
        if real_registry:
            registry = r'HKCU:\Software\CompanyAIHelpers.Tests.' + uuid.uuid4().hex
            # Creation, observation and cleanup use the same normal desktop
            # context as recovery, avoiding packaged-parent registry views.
            setup = "if($DesktopWorker -and $Phase -eq 'Prepare'){$fixtureKey='" + registry + "';" + \
                "New-Item -Path $fixtureKey|Out-Null;$values=[IO.File]::ReadAllText('" + quote(run) + "')|ConvertFrom-Json;" + \
                "foreach($property in $values.PSObject.Properties){New-ItemProperty -LiteralPath $fixtureKey -Name $property.Name -Value $property.Value -PropertyType String|Out-Null};" + \
                "try{Microsoft.PowerShell.Management\\Get-ItemPropertyValue -LiteralPath $fixtureKey -Name CompanyAIHelpers.NasSavedMappings -ErrorAction SilentlyContinue;throw 'Expected missing-value exception'}" + \
                "catch{[IO.File]::WriteAllText('" + quote(repo / 'registry-proof.txt') + "',$_.Exception.GetType().Name)}}\n"
            run = registry
        for name in ('recover-mixed-runtime.ps1', 'migrate-workspace-runtime.ps1'):
            body = (ROOT / 'scripts' / name).read_text(encoding='utf-8-sig')
            body = body.replace("$ErrorActionPreference='Stop'", "$ErrorActionPreference='Stop'\n" + hooks, 1)
            body = body.replace("$ErrorActionPreference = 'Stop'", "$ErrorActionPreference = 'Stop'\n" + hooks, 1)
            body = body.replace("[Environment]::GetFolderPath('LocalApplicationData')", "'" + quote(local) + "'")
            body = body.replace("[Environment]::GetFolderPath('Startup')", "'" + quote(startup) + "'")
            body = body.replace("'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run'", "'" + quote(run) + "'")
            if real_registry and name == 'recover-mixed-runtime.ps1':
                body = body.replace("function Assert-Regular", setup + "function Assert-Regular", 1)
                observe = "try{if($Phase -in @('Finish','Rollback')){$fixtureKey='" + registry + "';" + \
                    "try{$value=Microsoft.PowerShell.Management\\Get-ItemPropertyValue -LiteralPath $fixtureKey -Name Owned;" + \
                    "[IO.File]::WriteAllText('" + quote(repo / 'registry-restored.txt') + "',[string]$value)}" + \
                    "finally{Remove-Item -LiteralPath $fixtureKey -Force}}}catch{}\n"
                body = body.replace('$mutex.ReleaseMutex();', observe + '$mutex.ReleaseMutex();', 1)
            (scripts / name).write_text(body, encoding='utf-8-sig')
        return recovery_id, old, startup, run, active

    def ps_command(self, command):
        env = dict(os.environ)
        env.pop('PSModulePath', None)
        return subprocess.check_output([str(PS), '-NoProfile', '-Command', command], env=env,
                                      text=True, encoding='utf-8', errors='replace', timeout=15).strip()

    def phase(self, repo, recovery_id, phase, expected=0, failed_backup=None, desktop_worker=False):
        env = dict(os.environ)
        env.pop('PSModulePath', None)
        env.pop('CODEX_CLI_PATH', None)
        args = [str(PS), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
            str(repo / 'scripts/recover-mixed-runtime.ps1'), '-Phase', phase, '-RecoveryId', recovery_id,
            '-Confirmed', '-NoLaunch']
        if desktop_worker:
            args += ['-DesktopWorker']
        if failed_backup:
            args += ['-FailedBackupName', failed_backup]
        result = subprocess.run(args, env=env, capture_output=True, timeout=65)
        self.assertEqual(result.returncode, expected, (result.stdout + result.stderr).decode(errors='replace'))
        receipt = json.loads((repo / '.runtime/runtime-recovery' / recovery_id / ('receipt-' + phase + '.json')).read_text())
        # Receipt precedes the worker's finally block; wait for its exact task.
        check = "$s=New-Object -ComObject Schedule.Service;$s.Connect();$f=$s.GetFolder('\\');" + \
                "$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;" + \
                "try{$null=$f.GetTask('CompanyAIHelpers.RuntimeRecovery.'+$sid+'." + recovery_id + "." + phase + "');exit 1}catch{exit 0}"
        for attempt in range(30):
            task = subprocess.run([str(PS), '-NoProfile', '-Command', check], env=env, capture_output=True, timeout=10)
            if task.returncode == 0:
                break
            time.sleep(0.2)
        self.assertEqual(task.returncode, 0, 'Recovery fixture left its task behind')
        self.assertEqual(receipt['ok'], expected == 0, receipt)
        return receipt

    def prepare_fixture_state(self, repo, recovery_id, old, startup, run, active):
        operation = repo / '.runtime/runtime-recovery' / recovery_id
        operation.mkdir(parents=True)
        original = active.read_bytes()
        original_run = json.loads(run.read_text())
        link = startup / 'Owned.lnk'
        link_bytes = link.read_bytes()
        (operation / 'fixture.lnk').write_bytes(link_bytes)
        state = {'schemaVersion':1,'recoveryId': recovery_id,'status':'prepared',
            'ownerSid': self.ps_command('[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'),
            'originalActiveSha256': hashlib.sha256(original).hexdigest().upper(),
            'runEntries':[{'name':'Owned','command':original_run['Owned']}],
            'links':[{'path':str(link),'backup':'fixture.lnk','sha256':hashlib.sha256(link_bytes).hexdigest().upper(),
                'target':str(old / 'CodexAnswerChime/CodexAnswerChime.exe'),
                'arguments':'--synthetic','workingDirectory':str(old/'CodexAnswerChime'),
                'description':'Fixture shortcut','iconLocation':str(old/'CodexAnswerChime/CodexAnswerChime.exe')+',0'}]}
        (operation / 'state.json').write_text(json.dumps(state))
        original_run.pop('Owned')
        run.write_text(json.dumps(original_run))
        link.unlink()
        return original, link_bytes

    def test_previously_paused_startup_restores_without_migrating_private_data(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            recovery_id, old, startup, run, active = self.fixture(repo)
            original, link_bytes = self.prepare_fixture_state(repo, recovery_id, old, startup, run, active)
            self.phase(repo, recovery_id, 'Rollback')
            self.assertEqual(active.read_bytes(), original)
            self.assertEqual((startup / 'Owned.lnk').read_bytes(), link_bytes)
            self.assertIn(str(old), json.loads(run.read_text())['Owned'])
            self.assertFalse((repo / '.runtime/CompanyAIHelpers').exists())
            self.assertEqual((old / 'CodexTools/PrivatePlugins/Fixture/settings.json').read_bytes(), b'{"fixture":1}')

    def test_changed_startup_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            recovery_id, old, startup, run, active = self.fixture(repo)
            original, _ = self.prepare_fixture_state(repo, recovery_id, old, startup, run, active)
            values = json.loads(run.read_text());values['Owned']='unrelated replacement'
            run.write_text(json.dumps(values))
            self.phase(repo, recovery_id, 'Rollback', expected=1)
            self.assertEqual(json.loads(run.read_text())['Owned'],'unrelated replacement')
            self.assertEqual(active.read_bytes(),original)

    def test_rebind_installs_only_public_programs_and_restores_paused_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            recovery_id, old, startup, run, active = self.fixture(repo)
            original, _ = self.prepare_fixture_state(repo, recovery_id, old, startup, run, active)
            build = repo / 'scripts/build-helpers.ps1'
            build.write_text("$r=Split-Path -Parent $PSScriptRoot;$p=Join-Path $r 'artifacts/helpers';" +
                "[IO.Directory]::CreateDirectory($p)|Out-Null;" +
                "foreach($n in @('UpdreamClipboardCleaner.exe','CodexAnswerChime.exe'," +
                "'ArctisNova5BatteryMonitor.exe','ArctisNova5StartupGate.exe')){" +
                "[IO.File]::WriteAllText((Join-Path $p $n),'SYNTHETIC-PUBLIC-PROGRAM')};$global:LASTEXITCODE=0")
            self.phase(repo, recovery_id, 'RebindStartup', desktop_worker=True)
            destination = repo / '.runtime/CompanyAIHelpers'
            self.assertEqual(active.read_bytes(), original)
            self.assertIn(str(destination), json.loads(run.read_text())['Owned'])
            link = json.loads((startup / 'Owned.lnk').read_text())
            self.assertEqual(link['TargetPath'], str(destination / 'CodexAnswerChime/CodexAnswerChime.exe'))
            self.assertTrue((startup / 'Foreign.lnk').exists())
            self.assertFalse((destination / 'CodexTools').exists())
            self.assertEqual((old / 'CodexTools/PrivatePlugins/Fixture/settings.json').read_bytes(), b'{"fixture":1}')

    def test_new_migration_recovery_requests_fail_before_pausing_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            repo=Path(folder)
            recovery_id, old, startup, run, active=self.fixture(repo)
            before=run.read_bytes()
            for phase in ('Prepare','Finish','Resume'):
                result=subprocess.run([str(PS),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
                    str(repo/'scripts/recover-mixed-runtime.ps1'),'-Phase',phase,'-RecoveryId',recovery_id,'-Confirmed'],capture_output=True,timeout=15)
                self.assertNotEqual(result.returncode,0)
            self.assertEqual(run.read_bytes(),before)
            self.assertTrue((startup/'Owned.lnk').exists())

if __name__ == '__main__': unittest.main()
