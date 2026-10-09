import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/plugin-station'))
from core.runtime_upgrade import PendingUpgradeError, UpgradeError, request_runtime_upgrade

PS = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'


class RuntimeUpgradeTests(unittest.TestCase):
    def fixture(self, root):
        (root / 'scripts').mkdir()
        shutil.copy2(ROOT / 'scripts/auto-migrate-runtime.ps1', root / 'scripts')

    def accepted(self, repo, launch):
        def wait(timeout):
            self.assertEqual(timeout, 30)
            state = json.loads((repo / '.runtime/runtime-upgrade/active.json').read_text())
            (repo / '.runtime/runtime-upgrade' / (state['requestId'] + '.dispatch.json')).write_text(
                json.dumps({'requestId': state['requestId'], 'state': 'dispatched'}))
            return 0
        launch.return_value.wait.side_effect = wait

    def test_dispatch_is_hidden_and_does_not_require_codex(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            self.fixture(repo)
            with patch('core.runtime_upgrade.subprocess.Popen') as launch:
                self.accepted(repo, launch)
                state = request_runtime_upgrade(repo, caller_pid=123)
                args, kwargs = launch.call_args
                self.assertIn('-Dispatch', args[0])
                self.assertEqual(state['state'], 'pending')
                self.assertEqual(state['callerPid'], 123)
                self.assertNotIn('PSModulePath', kwargs['env'])
                self.assertNotIn('Codex.exe', str(args[0]))
                self.assertTrue(kwargs['close_fds'])
                self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
                self.assertEqual(kwargs['stdout'], subprocess.DEVNULL)
                self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
                self.assertEqual(kwargs['creationflags'] & getattr(subprocess, 'DETACHED_PROCESS', 0), 0)
                self.assertEqual(request_runtime_upgrade(repo), state)
                self.assertEqual(launch.call_count, 1)
            self.assertFalse((repo / '.runtime/runtime-upgrade/dispatch.lock').exists())

    def test_confirmed_stalled_pending_reuses_request_and_backup_only_once(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            self.fixture(repo)
            destination = repo / '.runtime/runtime-upgrade'
            destination.mkdir(parents=True)
            state = {'requestId': uuid.uuid4().hex, 'state': 'pending', 'updatedAt': 0,
                     'backupName': 'runtime-move-20000101-000000'}
            (destination / 'active.json').write_text(json.dumps(state))
            with patch('core.runtime_upgrade.subprocess.Popen') as launch:
                with self.assertRaises(PendingUpgradeError):
                    request_runtime_upgrade(repo)
                launch.assert_not_called()
                self.accepted(repo, launch)
                resumed = request_runtime_upgrade(repo, resume_pending=True)
                self.assertIn('-ResumePending', launch.call_args.args[0])
                self.assertEqual(resumed['requestId'], state['requestId'])
                self.assertEqual(resumed['backupName'], state['backupName'])
                resumed['updatedAt'] = 0
                (destination / 'active.json').write_text(json.dumps(resumed))
                with self.assertRaises(UpgradeError):
                    request_runtime_upgrade(repo, resume_pending=True)
                self.assertEqual(launch.call_count, 1)

    def test_unacknowledged_exit_and_timeout_do_not_claim_handoff_or_kill_worker(self):
        for result in (0, 1, subprocess.TimeoutExpired('fixture', 30)):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as folder:
                repo = Path(folder)
                self.fixture(repo)
                with patch('core.runtime_upgrade.subprocess.Popen') as launch:
                    launch.return_value.wait.side_effect = result if isinstance(result, Exception) else None
                    launch.return_value.wait.return_value = result
                    with self.assertRaises(UpgradeError):
                        request_runtime_upgrade(repo)
                    launch.return_value.kill.assert_not_called()
                    launch.return_value.terminate.assert_not_called()
                self.assertEqual(json.loads((repo / '.runtime/runtime-upgrade/active.json').read_text())['state'], 'pending')

    def test_failures_and_stale_requests_never_automatically_loop(self):
        for phase, updated_at in [('failed', time.time()), ('pending', 0), ('running', 0)]:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as folder:
                repo = Path(folder)
                self.fixture(repo)
                destination = repo / '.runtime/runtime-upgrade'
                destination.mkdir(parents=True)
                (destination / 'active.json').write_text(json.dumps({'state': phase, 'updatedAt': updated_at}))
                with patch('core.runtime_upgrade.subprocess.Popen') as launch:
                    with self.assertRaises(UpgradeError):
                        request_runtime_upgrade(repo)
                    launch.assert_not_called()

    def test_dispatch_error_is_persisted_without_touching_legacy_data(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            self.fixture(repo)
            with patch('core.runtime_upgrade.subprocess.Popen', side_effect=OSError('unavailable')):
                with self.assertRaises(UpgradeError):
                    request_runtime_upgrade(repo)
            state = json.loads((repo / '.runtime/runtime-upgrade/active.json').read_text())
            self.assertEqual(state['state'], 'failed')

    def test_reparse_runtime_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            self.fixture(repo)
            with patch.object(Path, 'is_symlink', return_value=True):
                with self.assertRaises(UpgradeError):
                    request_runtime_upgrade(repo)

    @unittest.skipUnless(os.name == 'nt' and PS.exists(), 'Windows PowerShell required')
    def test_stage_rejects_conflicting_profiles_without_overwriting_either(self):
        for collision in ('legacy', 'workspace', 'none'):
            with self.subTest(collision=collision), tempfile.TemporaryDirectory() as folder:
                repo = Path(folder)
                self.fixture(repo)
                local = repo / 'synthetic-local'
                source = local / 'CompanyAIHelpers/CodexTools/PrivatePlugins/Example'
                source.mkdir(parents=True)
                (source / 'settings.json').write_text('{"fixture":1}')
                if collision == 'legacy':
                    other = local / 'Packages/OpenAI.Codex_fixture/LocalCache/Local/CompanyAIHelpers/CodexTools/PrivatePlugins/Example'
                else:
                    other = repo / '.runtime/CompanyAIHelpers/CodexTools/PrivatePlugins/Example'
                if collision != 'none':
                    other.mkdir(parents=True)
                    (other / 'settings.json').write_text('{"fixture":2}')
                body = (ROOT / 'scripts/migrate-workspace-runtime.ps1').read_text(encoding='utf-8-sig')
                original = "$local = [Environment]::GetFolderPath('LocalApplicationData')"
                self.assertIn(original, body)
                body = body.replace(original, "$local = '" + str(local).replace("'", "''") + "'", 1)
                script = repo / 'scripts/migrate-workspace-runtime.ps1'
                script.write_text(body, encoding='utf-8-sig')
                environment = dict(os.environ)
                environment.pop('PSModulePath', None)
                result = subprocess.run([str(PS), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                         '-File', str(script), '-Phase', 'Stage', '-BackupName', 'runtime-move-20000101-000000'],
                                        env=environment, capture_output=True, timeout=15)
                failure = repo / '.runtime/migration-backups/runtime-move-20000101-000000/failure.json'
                self.assertEqual(result.returncode, 0 if collision == 'none' else 1,
                                 failure.read_text(encoding='utf-8-sig') if failure.exists()
                                 else result.stderr.decode(errors='replace'))
                self.assertEqual((source / 'settings.json').read_text(), '{"fixture":1}')
                if collision != 'none':
                    self.assertEqual((other / 'settings.json').read_text(), '{"fixture":2}')
                else:
                    self.assertEqual((other / 'settings.json').read_text(), '{"fixture":1}')

    @unittest.skipUnless(os.name == 'nt' and PS.exists(), 'Windows PowerShell required')
    def test_automatic_migration_refuses_live_legacy_helper_before_copying(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            self.fixture(repo)
            local = repo / 'synthetic-local'
            source = local / 'CompanyAIHelpers/UpdreamClipboardCleaner'
            source.mkdir(parents=True)
            (source / 'settings.json').write_text('{"fixture":1}')
            body = (ROOT / 'scripts/migrate-workspace-runtime.ps1').read_text(encoding='utf-8-sig')
            body = body.replace("$local = [Environment]::GetFolderPath('LocalApplicationData')",
                                "$local = '" + str(local).replace("'", "''") + "'", 1)
            body = body.replace("$ErrorActionPreference = 'Stop'", "$ErrorActionPreference = 'Stop'\n"
                                "function Get-CimInstance { [pscustomobject]@{ExecutablePath='" +
                                str(source / 'fixture.exe').replace("'", "''") + "';ProcessId=0} }\n"
                                "function Stop-Process { throw 'Unexpected process termination' }\n"
                                "function Stop-ScheduledTask { throw 'Unexpected task termination' }", 1)
            script = repo / 'scripts/migrate-workspace-runtime.ps1'
            script.write_text(body, encoding='utf-8-sig')
            environment = dict(os.environ)
            environment.pop('PSModulePath', None)
            result = subprocess.run([str(PS), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                                     '-Phase', 'Stage', '-NoForce', '-BackupName', 'runtime-move-20000101-000000'],
                                    env=environment, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 1)
            failure = json.loads((repo / '.runtime/migration-backups/runtime-move-20000101-000000/failure.json').read_text(encoding='utf-8-sig'))
            self.assertIn('Exit the legacy toolbox helpers normally', failure['error'])
            self.assertFalse((repo / '.runtime/CompanyAIHelpers/UpdreamClipboardCleaner/settings.json').exists())
            self.assertEqual((source / 'settings.json').read_text(), '{"fixture":1}')

    @unittest.skipUnless(os.name == 'nt' and PS.exists(), 'Windows PowerShell required')
    def test_partial_migration_retains_extra_tools_their_processes_and_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            self.fixture(repo)
            local = repo / 'synthetic-local'
            old = local / 'CompanyAIHelpers'
            private = old / 'CodexTools/PrivatePlugins/Fixture/settings.json'
            private.parent.mkdir(parents=True)
            private.write_bytes(b'{"fixture":1}')
            helper = old / 'CodexAnswerChime/CodexAnswerChime.exe'
            helper.parent.mkdir()
            helper.write_bytes(b'synthetic non-executable')
            extras = {}
            for name in ('MigrationBackups', 'WeTypeAweSunDirectTrial', 'WorkBuddyDailyPoints'):
                path = old / name / 'preserved.bin'
                path.parent.mkdir()
                path.write_bytes(('synthetic-' + name).encode())
                extras[path] = path.read_bytes()
            startup = repo / 'synthetic-startup'
            startup.mkdir()
            run = repo / 'synthetic-run'
            run.write_text('fixture')
            quote = lambda p: str(p).replace("'", "''")
            foreign_exe = old / 'WorkBuddyDailyPoints/WorkBuddyDailyPoints.exe'
            updated = repo / 'startup-updated.txt'
            hooks = """
function Get-CimInstance { [pscustomobject]@{Name='WorkBuddyDailyPoints.exe';ExecutablePath='FOREIGN';ProcessId=0;CommandLine='fixture'} }
function Get-ScheduledTask { return $null }
function Get-ItemPropertyValue { return $null }
function Get-ItemProperty { [pscustomobject]@{Owned='"HELPER"';Foreign='"FOREIGN" --fixture "OWNEDARG"'} }
function Set-ItemProperty { param($LiteralPath,$Name,$Value)
 if ($Name -ne 'Owned') {throw 'Unrelated startup was changed'}
 [IO.File]::WriteAllText('UPDATED',[string]$Value)
}
function Stop-Process { throw 'Unexpected process termination' }
function Stop-ScheduledTask { throw 'Unexpected task termination' }
""".replace('FOREIGN', quote(foreign_exe)).replace('HELPER', quote(helper)).replace(
                'OWNEDARG', quote(private)).replace('UPDATED', quote(updated))
            body = (ROOT / 'scripts/migrate-workspace-runtime.ps1').read_text(encoding='utf-8-sig')
            body = body.replace("$ErrorActionPreference = 'Stop'", "$ErrorActionPreference = 'Stop'\n" + hooks, 1)
            body = body.replace("$local = [Environment]::GetFolderPath('LocalApplicationData')", "$local = '" + quote(local) + "'", 1)
            body = body.replace("$runPath = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run'", "$runPath = '" + quote(run) + "'", 1)
            body = body.replace("$startup = [Environment]::GetFolderPath('Startup')", "$startup = '" + quote(startup) + "'", 1)
            script = repo / 'scripts/migrate-workspace-runtime.ps1'
            script.write_text(body, encoding='utf-8-sig')
            environment = dict(os.environ)
            environment.pop('PSModulePath', None)
            for phase in ('Stage', 'Finalize'):
                result = subprocess.run([str(PS), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                                         '-Phase', phase, '-NoForce', '-BackupName', 'runtime-move-20000101-000000'],
                                        env=environment, capture_output=True, timeout=20)
                failure = repo / '.runtime/migration-backups/runtime-move-20000101-000000/failure.json'
                self.assertEqual(result.returncode, 0, failure.read_text(encoding='utf-8-sig') if failure.exists()
                                 else result.stderr.decode(errors='replace'))
                for path, original in extras.items():
                    self.assertEqual(path.read_bytes(), original)
                    self.assertFalse((repo / '.runtime/CompanyAIHelpers' / path.relative_to(old)).exists())
            backup = repo / '.runtime/migration-backups/runtime-move-20000101-000000'
            self.assertEqual(json.loads((backup / 'result.json').read_text(encoding='utf-8-sig'))['oldRootsRemain'], 0)
            self.assertEqual((repo / '.runtime/CompanyAIHelpers/CodexTools/PrivatePlugins/Fixture/settings.json').read_bytes(), b'{"fixture":1}')
            self.assertEqual((backup / 'originals/normal/CodexTools/PrivatePlugins/Fixture/settings.json').read_bytes(), b'{"fixture":1}')
            self.assertFalse((old / 'CodexTools').exists())
            self.assertEqual(updated.read_text(), '"' + str(repo / '.runtime/CompanyAIHelpers/CodexAnswerChime/CodexAnswerChime.exe') + '"')

    @unittest.skipUnless(os.name == 'nt' and PS.exists(), 'Windows desktop scheduler required')
    def test_owned_selector_accepts_venv_children_but_rejects_other_apps_and_sessions(self):
        body = (ROOT / 'scripts/auto-migrate-runtime.ps1').read_text(encoding='utf-8-sig')
        selector = re.search(r'(function Get-OwnedToolboxProcesses.*?)(?=\n# End owned-process selector)',
                             body, re.S).group(1)
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            venv = str(repo / '.runtime/venv/Scripts/pythonw.exe')
            app = str(repo / 'apps/plugin-station/app.py')
            command = '"' + venv + '" "' + app + '"'
            base = str(repo / 'base/pythonw.exe')
            rows = []
            for pid, parent, exe, argv, session in [
                (10, 1, venv, command, 1), (11, 10, base, command, 1),
                (12, 11, base, command, 1), (20, 999, base, command, 1),
                (21, 10, base, command, 2), (22, 10, base, 'other.py', 1),
                (23, 10, str(repo / 'other.exe'), command, 1),
            ]:
                rows.append(dict(ProcessId=pid, ParentProcessId=parent, ExecutablePath=exe,
                                 CommandLine=argv, SessionId=session))
            script = repo / 'selector-fixture.ps1'
            script.write_text(selector + "\n$rows='" + json.dumps(rows).replace("'", "''") +
                              "'|ConvertFrom-Json\n$owned=@('" + venv.replace("'", "''") +
                              "')\n$pattern='(?:^|\\s)\"?' + [regex]::Escape('" +
                              app.replace("'", "''") + "') + '(?:\"|\\s|$)'\n" +
                              '@(Get-OwnedToolboxProcesses $rows $owned $pattern 1 | '
                              'ForEach-Object {[int]$_.ProcessId} | Sort-Object) | ConvertTo-Json -Compress',
                              encoding='utf-8-sig')
            environment = dict(os.environ)
            environment.pop('PSModulePath', None)
            result = subprocess.run([str(PS), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)],
                                    env=environment, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertEqual(json.loads(result.stdout), [10, 11, 12])

    @unittest.skipUnless(os.name == 'nt' and PS.exists(), 'Windows desktop scheduler required')
    def test_hidden_fixture_window_closes_gracefully_without_touching_other_processes(self):
        body = (ROOT / 'scripts/auto-migrate-runtime.ps1').read_text(encoding='utf-8-sig')
        native = re.search(r"Add-Type -TypeDefinition @'\n(.*?)\n'@", body, re.S).group(1)
        environment = dict(os.environ)
        environment.pop('PSModulePath', None)
        with tempfile.TemporaryDirectory() as folder:
            ready = Path(folder) / 'ready.json'
            child_script = Path(folder) / 'hidden-fixture.ps1'
            child_script.write_text("""Add-Type -AssemblyName System.Windows.Forms
$ErrorActionPreference='Stop'
$f=New-Object Windows.Forms.Form
$f.Text='Synthetic migration test'
$f.add_FormClosed({[Windows.Forms.Application]::ExitThread()})
$f.Show();$f.Hide()
[IO.File]::WriteAllText('""" + str(ready).replace("'", "''") + """',
    ('{"pid":'+$PID+',"visible":'+$f.Visible.ToString().ToLower()+'}'))
[Windows.Forms.Application]::Run()
""", encoding='utf-8-sig')
            child = subprocess.Popen([str(PS), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(child_script)],
                                     env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline = time.monotonic() + 25
                while not ready.exists() and time.monotonic() < deadline:
                    if child.poll() is not None:
                        break
                    time.sleep(0.1)
                self.assertTrue(ready.exists(), child.communicate(timeout=2)[1].decode(errors='replace')
                                if child.poll() is not None else 'Synthetic window did not become ready')
                data = json.loads(ready.read_text())
                self.assertEqual(data['pid'], child.pid)
                self.assertFalse(data['visible'])
                command = "Add-Type -TypeDefinition @'\n" + native + "\n'@\n" + \
                          '[ToolboxUpgradeWindows]::CloseOwned(' + str(child.pid) + ')'
                result = subprocess.run([str(PS), '-NoProfile', '-Command', command], env=environment,
                                        capture_output=True, timeout=35)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                self.assertEqual(child.wait(timeout=20), 0)
            finally:
                if child.poll() is None:
                    child.terminate()  # Only this test's synthetic child.
                    child.wait(timeout=10)
                child.communicate(timeout=2)

    @unittest.skipUnless(os.name == 'nt' and PS.exists(), 'Windows desktop scheduler required')
    def test_real_one_shot_worker_uses_only_synthetic_fixture_and_removes_task(self):
        # The actual scheduled worker runs only fixture phases; no real private
        # data, NAS, startup settings, application windows or launchers touched.
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            self.fixture(repo)
            destination = repo / '.runtime/runtime-upgrade'
            destination.mkdir(parents=True)
            request_id = uuid.uuid4().hex
            state_path = destination / 'active.json'
            state_path.write_text(json.dumps({'requestId': request_id, 'state': 'pending',
                                              'backupName': 'runtime-move-20000101-000000',
                                              'updatedAt': time.time()}), encoding='utf-8')
            stub = """param([string]$Phase,[string]$BackupName,[switch]$NoForce)
$root=Split-Path -Parent $PSScriptRoot
$backup=Join-Path $root ('.runtime\\migration-backups\\'+$BackupName)
[IO.Directory]::CreateDirectory($backup) | Out-Null
[IO.File]::WriteAllText((Join-Path $backup ($Phase+'.txt')),'fixture')
if ($Phase -eq 'Finalize') {
 [IO.File]::WriteAllText((Join-Path $backup 'result.json'),'{"phase":"complete","oldRootsRemain":0}')
}
exit 0
"""
            (repo / 'scripts/migrate-workspace-runtime.ps1').write_text(stub, encoding='utf-8-sig')
            environment = dict(os.environ)
            environment.pop('PSModulePath', None)
            result = subprocess.run([str(PS), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                     '-File', str(repo / 'scripts/auto-migrate-runtime.ps1'), '-Dispatch',
                                     '-RequestId', request_id, '-NoLaunch', '-NoDialog'],
                                    cwd=repo, env=environment, capture_output=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            deadline = time.monotonic() + 100
            while time.monotonic() < deadline:
                try:
                    state = json.loads(state_path.read_text(encoding='utf-8-sig'))
                except (PermissionError, FileNotFoundError):  # Windows replacement can briefly hide the name.
                    time.sleep(0.02)
                    continue
                if state['state'] in ('complete', 'failed'):
                    break
                time.sleep(0.2)
            self.assertEqual(state['state'], 'complete')
            for phase in ('Stage','Finalize'):
                self.assertTrue((repo / '.runtime/migration-backups/runtime-move-20000101-000000' / (phase + '.txt')).exists())
            # Allow the worker's finally block to remove its own temporary task.
            time.sleep(1)
            command = "$s=New-Object -ComObject Schedule.Service;$s.Connect();$f=$s.GetFolder('\\');" + \
                      "$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;" + \
                      "try{$null=$f.GetTask('CompanyAIHelpers.RuntimeMigration.'+$sid+'." + request_id + "');exit 1}catch{exit 0}"
            check = subprocess.run([str(PS), '-NoProfile', '-Command', command], env=environment, capture_output=True, timeout=10)
            self.assertEqual(check.returncode, 0, 'Fixture worker left its temporary task behind')

    @unittest.skipUnless(os.name == 'nt' and PS.exists(), 'Windows desktop scheduler required')
    def test_real_pythonw_parent_waits_for_dispatch_before_exiting(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            self.fixture(repo)
            script = repo / 'scripts/auto-migrate-runtime.ps1'
            script.write_text(script.read_text(encoding='utf-8-sig').replace(
                '[switch]$NoLaunch, [switch]$NoDialog,', '[switch]$NoLaunch=$true, [switch]$NoDialog=$true,'),
                encoding='utf-8-sig')
            core = repo / 'apps/plugin-station/core'
            core.mkdir(parents=True)
            shutil.copy2(ROOT / 'apps/plugin-station/core/runtime_upgrade.py', core)
            (repo / 'scripts/migrate-workspace-runtime.ps1').write_text("""param([string]$Phase,[string]$BackupName,[switch]$NoForce)
if (-not $NoForce) {exit 2}
$root=Split-Path -Parent $PSScriptRoot
$backup=Join-Path $root ('.runtime\\migration-backups\\'+$BackupName)
[IO.Directory]::CreateDirectory($backup)|Out-Null
[IO.File]::WriteAllText((Join-Path $backup ($Phase+'.txt')),'fixture')
if ($Phase -eq 'Finalize') {
 [IO.File]::WriteAllText((Join-Path $backup 'result.json'),'{"phase":"complete","oldRootsRemain":0}')
}
""", encoding='utf-8-sig')
            caller = repo / 'apps/plugin-station/app.py'
            destination = repo / '.runtime/runtime-upgrade'
            destination.mkdir(parents=True)
            request_id = uuid.uuid4().hex
            (destination / 'active.json').write_text(json.dumps({'requestId': request_id, 'state': 'pending',
                'updatedAt': 0, 'backupName': 'runtime-move-20000101-000000'}))
            caller.write_text("from pathlib import Path\nfrom core.runtime_upgrade import request_runtime_upgrade\n"
                              "request_runtime_upgrade(Path(__file__).resolve().parents[2], resume_pending=True)\n", encoding='utf-8')
            pythonw = ROOT / '.runtime/venv/Scripts/pythonw.exe'
            self.assertTrue(pythonw.exists(), 'Regression requires a real Windows venv redirector')
            environment = dict(os.environ)
            environment.pop('PSModulePath', None)
            parent = subprocess.Popen([str(pythonw), str(caller)], env=environment,
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.assertEqual(parent.wait(timeout=45), 0)
            state_path = repo / '.runtime/runtime-upgrade/active.json'
            deadline = time.monotonic() + 50
            while time.monotonic() < deadline:
                try:
                    state = json.loads(state_path.read_text(encoding='utf-8-sig'))
                except (PermissionError, FileNotFoundError):
                    time.sleep(0.05)
                    continue
                if state['state'] in ('complete', 'failed'):
                    break
                time.sleep(0.2)
            self.assertEqual(state['state'], 'complete', state)
            self.assertEqual(state['requestId'], request_id)
            self.assertEqual(state['backupName'], 'runtime-move-20000101-000000')
            self.assertTrue((state_path.parent / (state['requestId'] + '.dispatch.json')).exists())
            backup = repo / '.runtime/migration-backups' / state['backupName']
            self.assertEqual((backup / 'Stage.txt').read_text(), 'fixture')
            self.assertEqual((backup / 'Finalize.txt').read_text(), 'fixture')
            time.sleep(1)  # The worker removes its own task in finally.


if __name__ == '__main__':
    unittest.main()
