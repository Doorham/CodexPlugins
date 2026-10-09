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
    def fixture(self, repo):
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
function Get-ItemProperty { [CmdletBinding()]param($LiteralPath) [IO.File]::ReadAllText('RUNFILE')|ConvertFrom-Json }
function Get-ItemPropertyValue { [CmdletBinding()]param($LiteralPath,$Name)
 $values=[IO.File]::ReadAllText('RUNFILE')|ConvertFrom-Json
 $property=$values.PSObject.Properties[$Name];if($property){return $property.Value}
}
function Set-ItemProperty { param($LiteralPath,$Name,$Value)
 $values=[IO.File]::ReadAllText('RUNFILE')|ConvertFrom-Json
 $values|Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
 [IO.File]::WriteAllText('RUNFILE',($values|ConvertTo-Json -Compress))
}
function Remove-ItemProperty { param($LiteralPath,$Name)
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
        for name in ('recover-mixed-runtime.ps1', 'migrate-workspace-runtime.ps1'):
            body = (ROOT / 'scripts' / name).read_text(encoding='utf-8-sig')
            body = body.replace("$ErrorActionPreference='Stop'", "$ErrorActionPreference='Stop'\n" + hooks, 1)
            body = body.replace("$ErrorActionPreference = 'Stop'", "$ErrorActionPreference = 'Stop'\n" + hooks, 1)
            body = body.replace("[Environment]::GetFolderPath('LocalApplicationData')", "'" + quote(local) + "'")
            body = body.replace("[Environment]::GetFolderPath('Startup')", "'" + quote(startup) + "'")
            body = body.replace("'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run'", "'" + quote(run) + "'")
            (scripts / name).write_text(body, encoding='utf-8-sig')
        return recovery_id, old, startup, run, active

    def phase(self, repo, recovery_id, phase, expected=0):
        env = dict(os.environ)
        env.pop('PSModulePath', None)
        env.pop('CODEX_CLI_PATH', None)
        result = subprocess.run([str(PS), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
            str(repo / 'scripts/recover-mixed-runtime.ps1'), '-Phase', phase, '-RecoveryId', recovery_id,
            '-Confirmed', '-NoLaunch'], env=env, capture_output=True, timeout=65)
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

    def test_prepare_finish_preserves_failed_record_and_unrelated_program(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            recovery_id, old, startup, run, active = self.fixture(repo)
            original = active.read_bytes()
            foreign_link = (startup / 'Foreign.lnk').read_bytes()
            foreign_run = json.loads(run.read_text())['Foreign']
            self.phase(repo, recovery_id, 'Prepare')
            self.assertEqual(active.read_bytes(), original)
            self.assertNotIn('Owned', json.loads(run.read_text()))
            self.assertFalse((startup / 'Owned.lnk').exists())
            self.assertTrue((old / 'CodexAnswerChime/CodexAnswerChime.exe').exists())
            self.phase(repo, recovery_id, 'Finish')
            complete = json.loads(active.read_text())
            self.assertEqual(complete['state'], 'complete')
            self.assertEqual(complete['previousRequestId'], recovery_id)
            self.assertNotEqual(complete['requestId'], recovery_id)
            operation = repo / '.runtime/runtime-recovery' / recovery_id
            self.assertEqual((operation / 'failed-active-original.json').read_bytes(), original)
            self.assertEqual(json.loads((operation / 'state.json').read_text())['originalActiveSha256'], hashlib.sha256(original).hexdigest().upper())
            target = repo / '.runtime/CompanyAIHelpers/CodexAnswerChime/CodexAnswerChime.exe'
            self.assertEqual(json.loads(run.read_text())['Owned'], '"' + str(target) + '" --synthetic')
            restored = json.loads((startup / 'Owned.lnk').read_text())
            self.assertEqual(restored['TargetPath'], str(target))
            self.assertEqual(restored['Arguments'], '--synthetic')
            self.assertEqual((startup / 'Foreign.lnk').read_bytes(), foreign_link)
            self.assertEqual(json.loads(run.read_text())['Foreign'], foreign_run)
            for name in ('MigrationBackups', 'WeTypeAweSunDirectTrial', 'WorkBuddyDailyPoints'):
                self.assertEqual((old / name / 'preserved.bin').read_bytes(), ('synthetic-' + name).encode())
                self.assertFalse((repo / '.runtime/CompanyAIHelpers' / name).exists())
            self.assertEqual((repo / '.runtime/CompanyAIHelpers/CodexTools/PrivatePlugins/Fixture/settings.json').read_bytes(), b'{"fixture":1}')

    def test_prepare_rollback_restores_exact_startup_without_changing_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            recovery_id, old, startup, run, active = self.fixture(repo)
            original = active.read_bytes()
            original_run = json.loads(run.read_text())
            original_link = (startup / 'Owned.lnk').read_bytes()
            self.phase(repo, recovery_id, 'Prepare')
            self.phase(repo, recovery_id, 'Rollback')
            self.assertEqual(active.read_bytes(), original)
            self.assertEqual(json.loads(run.read_text()), original_run)
            self.assertEqual((startup / 'Owned.lnk').read_bytes(), original_link)
            self.assertTrue((old / 'CodexTools/PrivatePlugins/Fixture/settings.json').exists())

    def test_changed_startup_is_not_overwritten_during_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            recovery_id, old, startup, run, active = self.fixture(repo)
            original = active.read_bytes()
            self.phase(repo, recovery_id, 'Prepare')
            values = json.loads(run.read_text())
            values['Owned'] = 'synthetic unrelated replacement'
            run.write_text(json.dumps(values))
            self.phase(repo, recovery_id, 'Rollback', expected=1)
            self.assertEqual(json.loads(run.read_text())['Owned'], 'synthetic unrelated replacement')
            self.assertEqual(active.read_bytes(), original)

    def test_private_conflict_leaves_failure_originals_and_startup_paused(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            recovery_id, old, startup, run, active = self.fixture(repo)
            original = active.read_bytes()
            self.phase(repo, recovery_id, 'Prepare')
            conflict = repo / '.runtime/CompanyAIHelpers/CodexTools/PrivatePlugins/Fixture/settings.json'
            conflict.parent.mkdir(parents=True)
            conflict.write_bytes(b'{"fixture":2}')
            self.phase(repo, recovery_id, 'Finish', expected=1)
            self.assertEqual(active.read_bytes(), original)
            self.assertEqual(conflict.read_bytes(), b'{"fixture":2}')
            self.assertEqual((old / 'CodexTools/PrivatePlugins/Fixture/settings.json').read_bytes(), b'{"fixture":1}')
            self.assertNotIn('Owned', json.loads(run.read_text()))
            self.assertFalse((startup / 'Owned.lnk').exists())
            self.assertEqual(json.loads((repo / '.runtime/runtime-recovery' / recovery_id / 'state.json').read_text())['status'], 'prepared')


if __name__ == '__main__':
    unittest.main()
