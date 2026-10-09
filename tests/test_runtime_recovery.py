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

    def phase(self, repo, recovery_id, phase, expected=0, failed_backup=None):
        env = dict(os.environ)
        env.pop('PSModulePath', None)
        env.pop('CODEX_CLI_PATH', None)
        args = [str(PS), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
            str(repo / 'scripts/recover-mixed-runtime.ps1'), '-Phase', phase, '-RecoveryId', recovery_id,
            '-Confirmed', '-NoLaunch']
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

    def test_empty_startup_value_is_a_change_not_an_absent_value(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            recovery_id, old, startup, run, active = self.fixture(repo)
            original = active.read_bytes()
            self.phase(repo, recovery_id, 'Prepare')
            values = json.loads(run.read_text())
            values['Owned'] = ''
            run.write_text(json.dumps(values))
            self.phase(repo, recovery_id, 'Rollback', expected=1)
            self.assertEqual(json.loads(run.read_text())['Owned'], '')
            self.assertEqual(active.read_bytes(), original)

    def test_real_registry_absent_nas_and_paused_run_finish_or_rollback(self):
        for last_phase in ('Finish', 'Rollback'):
            with self.subTest(phase=last_phase), tempfile.TemporaryDirectory() as folder:
                repo = Path(folder)
                recovery_id, old, startup, registry, active = self.fixture(repo, real_registry=True)
                original = active.read_bytes()
                self.assertRegex(registry, r'^HKCU:\\Software\\CompanyAIHelpers\.Tests\.[a-f0-9]{32}$')
                prepared = self.phase(repo, recovery_id, 'Prepare')
                self.assertEqual(prepared['pausedRunCount'], 1)
                self.assertEqual((repo / 'registry-proof.txt').read_text(), 'PSArgumentException')
                self.phase(repo, recovery_id, last_phase)
                restored = (repo / 'registry-restored.txt').read_text()
                helper = (repo / '.runtime/CompanyAIHelpers' if last_phase == 'Finish' else old) / 'CodexAnswerChime/CodexAnswerChime.exe'
                self.assertEqual(restored, '"' + str(helper) + '" --synthetic')
                if last_phase == 'Rollback':
                    self.assertEqual(active.read_bytes(), original)
                else:
                    self.assertEqual(json.loads(active.read_text())['state'], 'complete')

    def test_reviewed_resume_preserves_old_receipt_and_rejects_copied_stage(self):
        for copied in (False, True):
            with self.subTest(copied=copied), tempfile.TemporaryDirectory() as folder:
                repo = Path(folder)
                recovery_id, old, startup, run, active = self.fixture(repo)
                self.phase(repo, recovery_id, 'Prepare')
                operation = repo / '.runtime/runtime-recovery' / recovery_id
                state_path = operation / 'state.json'
                state = json.loads(state_path.read_text())
                old_hash = 'A' * 64
                state['migrationSha256'] = old_hash
                state_path.write_text(json.dumps(state))
                script = repo / 'scripts/recover-mixed-runtime.ps1'
                script.write_text(script.read_text(encoding='utf-8-sig').replace(
                    'ED356E06137EF12430B773C2EC282B4AC7832AEA4375801B540BFEF437F7B7C5', old_hash), encoding='utf-8-sig')
                receipt = operation / 'receipt-Finish.json'
                receipt.write_text(json.dumps({'ok': False, 'phase': 'Finish', 'recoveryId': recovery_id,
                    'error': 'Controlled migration failed: Stage. Originals and both backups retained.'}))
                receipt_bytes = receipt.read_bytes()
                failed_name = 'runtime-move-20000102-000000'
                backup = repo / '.runtime/migration-backups' / failed_name
                backup.mkdir()
                failure = backup / 'failure.json'
                failure.write_text(json.dumps({'phase': 'Stage', 'error': 'Property CompanyAIHelpers.NasSavedMappings does not exist'}))
                original_failure = failure.read_bytes()
                if copied:
                    (backup / 'snapshots').mkdir()
                original_active = active.read_bytes()
                self.phase(repo, recovery_id, 'Resume', expected=1 if copied else 0, failed_backup=failed_name)
                self.assertEqual(receipt.read_bytes(), receipt_bytes)
                self.assertEqual(failure.read_bytes(), original_failure)
                if copied:
                    self.assertEqual(active.read_bytes(), original_active)
                    self.assertEqual(json.loads(state_path.read_text())['migrationSha256'], old_hash)
                else:
                    result = json.loads(active.read_text())
                    self.assertEqual(result['state'], 'complete')
                    self.assertEqual((operation / 'failed-active-original.json').read_bytes(), original_active)
                    self.assertEqual(json.loads(state_path.read_text())['resumeFromMissingNas']['finishReceiptSha256'], hashlib.sha256(receipt_bytes).hexdigest().upper())


if __name__ == '__main__':
    unittest.main()
