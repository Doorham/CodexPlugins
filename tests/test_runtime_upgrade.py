import json
import os
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
from core.runtime_upgrade import UpgradeError, request_runtime_upgrade

PS = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'


class RuntimeUpgradeTests(unittest.TestCase):
    def fixture(self, root):
        (root / 'scripts').mkdir()
        shutil.copy2(ROOT / 'scripts/auto-migrate-runtime.ps1', root / 'scripts')

    def test_dispatch_is_hidden_and_does_not_require_codex(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            self.fixture(repo)
            with patch('core.runtime_upgrade.subprocess.Popen') as launch:
                state = request_runtime_upgrade(repo, caller_pid=123)
                args, kwargs = launch.call_args
                self.assertIn('-Dispatch', args[0])
                self.assertEqual(state['state'], 'pending')
                self.assertEqual(state['callerPid'], 123)
                self.assertNotIn('PSModulePath', kwargs['env'])
                self.assertNotIn('Codex.exe', str(args[0]))
                self.assertTrue(kwargs['close_fds'])
                self.assertEqual(request_runtime_upgrade(repo), state)
                self.assertEqual(launch.call_count, 1)
            self.assertFalse((repo / '.runtime/runtime-upgrade/dispatch.lock').exists())

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
            stub = """param([string]$Phase,[string]$BackupName)
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
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                state = json.loads(state_path.read_text(encoding='utf-8-sig'))
                if state['state'] in ('complete', 'failed'):
                    break
                time.sleep(0.2)
            self.assertEqual(state['state'], 'complete')
            for phase in ('Stage','Finalize'):
                self.assertTrue((repo / '.runtime/migration-backups/runtime-move-20000101-000000' / (phase + '.txt')).exists())
            # Allow the worker's finally block to remove its own temporary task.
            time.sleep(0.5)
            command = "$s=New-Object -ComObject Schedule.Service;$s.Connect();$f=$s.GetFolder('\\');" + \
                      "$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;" + \
                      "try{$null=$f.GetTask('CompanyAIHelpers.RuntimeMigration.'+$sid+'." + request_id + "');exit 1}catch{exit 0}"
            check = subprocess.run([str(PS), '-NoProfile', '-Command', command], env=environment, capture_output=True, timeout=10)
            self.assertEqual(check.returncode, 0, 'Fixture worker left its temporary task behind')


if __name__ == '__main__':
    unittest.main()
