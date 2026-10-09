"""Exercise the real updater in disposable local Git repositories, never real helpers."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class PublicUpdateTransaction(unittest.TestCase):
    def test_failed_install_retries_at_same_head_and_only_then_reports_current(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);hub=root/'hub';bare=hub/'git/CodexTools.git';writer=root/'writer';receiver=root/'receiver'
            bare.parent.mkdir(parents=True)
            env=dict(os.environ);env.pop('PSModulePath',None);env.pop('CODEXTOOLS_HUB_PATH',None)
            def git(*args):
                return subprocess.check_output(['git','-c','commit.gpgsign=false','-c','core.hooksPath='+str(root/'no-hooks'),
                    '-c','user.name=Fixture','-c','user.email=fixture@example.invalid',*map(str,args)],stderr=subprocess.STDOUT,env=env).decode().strip()
            git('init','--bare',bare);git('init','-b','main',writer)
            (writer/'scripts').mkdir();(writer/'helpers').mkdir()
            updater='update-from-hub.ps1' if (ROOT/'scripts/update-from-hub.ps1').exists() else 'update-from-origin.ps1'
            shutil.copy2(ROOT/'scripts'/updater,writer/'scripts'/updater)
            (writer/'.gitignore').write_text('.runtime/\nartifacts/\n')
            (writer/'ONLINE-RELEASE.json').write_text('{"version":"0.0.1"}')
            (writer/'scripts/build-helpers.ps1').write_text("throw 'SYNTHETIC-BUILD-FAILURE'",encoding='utf-8-sig')
            (writer/'scripts/build-updream-bridge.ps1').write_text('return',encoding='utf-8-sig')
            source=writer/'helpers/fixture.cs';source.write_text('OLD-FIXTURE')
            git('-C',writer,'add','.');git('-C',writer,'commit','-m','fixture');git('-C',writer,'remote','add','origin',bare);git('-C',writer,'push','origin','main')
            git('clone','-b','main',bare,receiver)
            source.write_text('NEW-FIXTURE');git('-C',writer,'commit','-am','update');git('-C',writer,'push','origin','main')
            head=git('-C',writer,'rev-parse','HEAD')
            (hub/'repository-state.json').write_text(json.dumps({'state':'idle','headCommit':head,'currentVersion':'0.0.2','revision':2}))
            def update(mode='Apply'):
                options=['-HubPath',str(hub),'-RepositoryRoot',str(receiver)] if updater=='update-from-hub.ps1' else ['-AllowNonGitHubRemote','-RepositoryRoot',str(receiver)]
                run=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(receiver/'scripts'/updater),'-Mode',mode,*options],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60)
                return json.loads(run.stdout.splitlines()[-1])
            for attempt in range(2):
                result=update();self.assertFalse(result['ok']);self.assertEqual(result['status'],'install_incomplete')
            self.assertEqual(git('-C',receiver,'rev-parse','HEAD'),head)
            self.assertNotEqual(update('Check')['status'],'current')
            # Replace only this disposable build stub; no executable is ever launched.
            built=['UpdreamClipboardCleaner.exe','WeTypeAweSunBridge.exe','CodexAnswerChime.exe','ArctisNova5BatteryMonitor.exe',
                'ArctisNova5StartupGate.exe','AWToolLIB2.dll','G435BatteryMonitor.exe','G435StartupGate.exe','EnvironmentDetector.exe']
            body="$dest=Join-Path (Split-Path -Parent $PSScriptRoot) 'artifacts\\helpers';[IO.Directory]::CreateDirectory($dest)|Out-Null;"
            body += ''.join("[IO.File]::WriteAllText((Join-Path $dest '"+name+"'),'NONEXECUTABLE-FIXTURE');" for name in built)
            (receiver/'scripts/build-helpers.ps1').write_text(body,encoding='utf-8-sig')
            # Commit the fixed fixture and publish it, preserving the original failed transaction.
            shutil.copy2(receiver/'scripts/build-helpers.ps1',writer/'scripts/build-helpers.ps1')
            git('-C',writer,'commit','-am','fixed builder');git('-C',writer,'push','origin','main')
            git('-C',receiver,'checkout','--','scripts/build-helpers.ps1')
            new_head=git('-C',writer,'rev-parse','HEAD')
            (hub/'repository-state.json').write_text(json.dumps({'state':'idle','headCommit':new_head,'currentVersion':'0.0.3','revision':3}))
            self.assertTrue(update()['ok'])
            self.assertEqual(update('Check')['status'],'current')
            self.assertTrue(json.loads((receiver/'.runtime/updates/public-install.json').read_text())['complete'])
