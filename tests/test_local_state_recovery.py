import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

class LocalStateRecovery(unittest.TestCase):
    def test_copy_is_local_owned_nonoverwriting_and_excludes_program_files(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder); scripts = repo/'scripts';scripts.mkdir()
            for name in ('restore-personal-state','initialize-user-data'):
                shutil.copy2(ROOT/'scripts'/(name+'.ps1'),scripts/(name+'.ps1'))
            origin=repo/'.runtime/CompanyAIHelpers/UpdreamBridge';origin.mkdir(parents=True)
            (origin/'credentials.json').write_bytes(b'FAKE-CREDENTIAL-NOT-AN-ACCOUNT')
            (origin/'updream_gen.py').write_bytes(b'PUBLIC-CODE-FIXTURE')
            cache=origin/'webview2-data';cache.mkdir();(cache/'prefs.json').write_bytes(b'FAKE-BROWSER-STATE')
            env=dict(os.environ);env.pop('PSModulePath',None)
            args=['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
                str(scripts/'restore-personal-state.ps1'),'-Component','UpdreamBridge','-Source','WorkspaceLegacy','-Confirmed']
            # Test fixture directories may inherit an Administrators owner under elevation.
            # Explicitly assign only this synthetic source to the current Windows SID.
            quoted=str(origin).replace("'", "''")
            command="$p='"+quoted+"';$a=[IO.Directory]::GetAccessControl($p);$a.SetOwner([Security.Principal.WindowsIdentity]::GetCurrent().User);[IO.Directory]::SetAccessControl($p,$a)"
            subprocess.run(['powershell.exe','-NoProfile','-Command',command],env=env,capture_output=True,check=True,timeout=15)
            first=subprocess.run(args,capture_output=True,env=env,timeout=20)
            self.assertEqual(first.returncode,0,first.stderr.decode(errors='replace'))
            self.assertNotIn(b'FAKE-CREDENTIAL',first.stdout)
            users=list((repo/'.runtime/CompanyAIHelpers/Users').iterdir())
            target=users[0]/'UpdreamBridge'
            self.assertEqual((target/'credentials.json').read_bytes(),b'FAKE-CREDENTIAL-NOT-AN-ACCOUNT')
            self.assertFalse((target/'updream_gen.py').exists())
            self.assertTrue((origin/'credentials.json').exists())
            (target/'credentials.json').write_bytes(b'NEW-LOCAL-FIXTURE')
            second=subprocess.run(args,capture_output=True,env=env,timeout=20)
            self.assertNotEqual(second.returncode,0)
            self.assertEqual((target/'credentials.json').read_bytes(),b'NEW-LOCAL-FIXTURE')
            self.assertEqual((origin/'credentials.json').read_bytes(),b'FAKE-CREDENTIAL-NOT-AN-ACCOUNT')
