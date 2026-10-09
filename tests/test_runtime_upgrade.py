import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/plugin-station'))
from core.runtime_upgrade import request_runtime_upgrade, UpgradeError

class RuntimeUpgradeTests(unittest.TestCase):
    def test_retired_dispatch_never_creates_or_changes_records(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            active = repo / '.runtime/runtime-upgrade/active.json'
            active.parent.mkdir(parents=True)
            active.write_bytes(b'{"state":"failed","fixture":1}')
            before = active.read_bytes()
            for resume in (False, True):
                with self.assertRaises(UpgradeError): request_runtime_upgrade(repo, resume_pending=resume)
            self.assertEqual(active.read_bytes(), before)
            self.assertEqual(list(active.parent.iterdir()), [active])

    def test_retired_stage_and_finalize_leave_fake_private_files_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            private = Path(folder) / 'credentials.json'
            private.write_bytes(b'SYNTHETIC-PRIVATE')
            for phase in ('Stage','Finalize'):
                run = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                    '-File', str(ROOT / 'scripts/migrate-workspace-runtime.ps1'), '-Phase',phase], capture_output=True, timeout=15)
                self.assertNotEqual(run.returncode, 0)
            self.assertEqual(private.read_bytes(), b'SYNTHETIC-PRIVATE')
