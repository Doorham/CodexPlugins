"""Architecture regressions. All file contents and processes below are fixtures."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'apps/plugin-station'
sys.path.insert(0, str(APP))
from core.control import ControlService, command_targets

from core.tool_paths import TOOL_DATA_ROOT, USER_DATA_ROOT, USER_SID
from core.codex_system_proxy import ensure_system_proxy_feature


class PrivacyContracts(unittest.TestCase):
    def test_user_identity_is_separate_from_program_root(self):
        self.assertRegex(USER_SID, r'^S-1-5-')
        self.assertEqual(USER_DATA_ROOT, TOOL_DATA_ROOT / 'Users' / USER_SID)
        self.assertNotEqual(USER_DATA_ROOT, TOOL_DATA_ROOT / 'Users' / 'S-1-5-21-000-fixture')
        for plugin in (APP / 'plugins').glob('*/plugin.json'):
            data = json.loads(plugin.read_text())
            for path in data.get('localDataPolicy', {}).get('paths', []):
                self.assertNotIn('%CODEXTOOLS_DATA_ROOT%', path)


    def test_same_named_unowned_process_is_never_stopped(self):
        service = ControlService.__new__(ControlService)
        plugin = {'processName': 'Example.exe', 'executable': str(TOOL_DATA_ROOT / 'Example/Example.exe')}
        with patch('core.control.process_pids', return_value=[]) as pids, patch('core.control.hidden_run') as stop:
            service._stop_plugin_process(plugin)
        stop.assert_not_called()
        self.assertEqual(pids.call_args.args[1], Path(plugin['executable']))
        self.assertFalse(command_targets('"C:\\Foreign\\Example.exe"', Path(plugin['executable'])))

    def test_package_rejects_state_paths_without_opening_their_body(self):
        spec = importlib.util.spec_from_file_location('boundary', ROOT / 'scripts/check-public-boundary.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        for name in ['helpers/Example/credentials.json', 'helpers/Example/WebView2-data/Default/Cookies',
                     '.RUNTIME/Users/fixture/prefs.json', 'helpers/Example/custom-domains.json', 'unexpected/prefs.json']:
            self.assertTrue(module.path_problems(name))
            # The public checker short-circuits before decoding rejected content.
            class Unreadable:
                def decode(self, *args, **kwargs): raise AssertionError('private body opened')
            self.assertTrue(module.problems(name, Unreadable()))

    def test_support_file_cannot_overwrite_declared_personal_state(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            target = repo / '.runtime/CompanyAIHelpers/Example/prefs.json'
            target.parent.mkdir(parents=True); target.write_bytes(b'PRIVATE-FIXTURE')
            source = repo / 'helpers/Example/public.txt'
            source.parent.mkdir(parents=True); source.write_bytes(b'PUBLIC-FIXTURE')
            service = ControlService.__new__(ControlService); service.repo_root = repo
            plugin = {'supportFiles': [{'source': 'helpers/Example/public.txt', 'target': str(target)}],
                'localDataPolicy': {'paths': [str(target)], 'preserveOnUpdate': True}}
            with self.assertRaises(ValueError): service._ensure_installed(plugin, target.parent / 'Example.exe')
            self.assertEqual(target.read_bytes(), b'PRIVATE-FIXTURE')




    def test_dashboard_is_pure_and_one_fault_leaves_other_card_available(self):
        service = ControlService.__new__(ControlService)
        service._lock = threading.RLock(); service.private_root = Path('fixture-private'); service.private_errors=[]
        service.company_access=SimpleNamespace(status=lambda: {})
        service.plugins={name:{'id':name,'name':name,'keepAlive':True} for name in ('broken','working')}
        def status(plugin):
            if plugin['id']=='broken': raise FileNotFoundError('fixture')
            return {'id':'working'}
        with patch.object(service,'_plugin_status',side_effect=status), patch.object(service,'_sync_keep_alive_lifecycle') as lifecycle:
            result=service.dashboard()
        lifecycle.assert_not_called()
        self.assertEqual([c['id'] for c in result['plugins']],['broken','working'])

    def test_manual_stop_survives_restart_and_prevents_keepalive(self):
        with tempfile.TemporaryDirectory() as folder:
            service = ControlService.__new__(ControlService);service.private_root=Path(folder)/'PrivatePlugins'
            plugin={'id':'fixture','processName':'Example.exe','executable':'Example.exe','keepAlive':True}
            with patch.object(service,'_stop_plugin_process'),patch('core.control.time.sleep'):
                service._process_action(plugin,'stop',{})
            other=ControlService.__new__(ControlService);other.private_root=service.private_root
            other._manual_stops=other._read_intent()
            with patch.object(other,'_plugin_pids',side_effect=AssertionError('stopped helper probed for respawn')):
                self.assertFalse(other._recover_keep_alive(plugin))

    def test_two_real_config_writer_processes_preserve_both_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);config=base/'config.toml'; config.write_text('model = "fixture"\n')
            code='''import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from core.codex_system_proxy import ensure_system_proxy_feature
from core.company_drives import ensure_full_access_default
path=Path(sys.argv[2]); backup=Path(sys.argv[3])
time.sleep(.1)
if sys.argv[4]=='proxy': ensure_system_proxy_feature(config=path,backup_root=backup)
else: ensure_full_access_default({},config=path,backup_root=backup)
'''
            children=[subprocess.Popen([sys.executable,'-c',code,str(APP),str(config),str(base/'backup'),kind],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for kind in ('proxy','network')]
            for child in children:
                out,err=child.communicate(timeout=20);self.assertEqual(child.returncode,0,err.decode())
            import tomllib
            value=tomllib.loads(config.read_text())
            self.assertTrue(value['features']['respect_system_proxy'])
            self.assertEqual(value['default_permissions'],':danger-full-access')
            self.assertEqual(value['model'],'fixture')

    def test_external_editor_change_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.toml';path.write_text('model = "before"\n')
            from core import config_transaction
            real=config_transaction.os.replace
            real_write=Path.write_text
            def write(target,*args,**kwargs):
                result=real_write(target,*args,**kwargs)
                if target.suffix=='.tmp': real_write(path,'model = "editor"\n')
                return result
            with patch.object(Path,'write_text',write):
                with self.assertRaises(RuntimeError): ensure_system_proxy_feature(config=path,backup_root=Path(folder)/'backup')
            self.assertEqual(path.read_text(),'model = "editor"\n')

    def test_stale_account_helper_never_runs_when_current_build_fails(self):
        from core.source_build import ensure_helper_artifact_current
        with tempfile.TemporaryDirectory() as folder:
            repo=Path(folder)
            for name in ('helpers/updream-bridge/src/Program.cs','helpers/common/RuntimePaths.cs','scripts/build-updream-bridge.ps1'):
                path=repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'PUBLIC-SOURCE-FIXTURE')
            artifact=repo/'artifacts/UpdreamBridgeConfig.exe';artifact.parent.mkdir();artifact.write_bytes(b'OLD-PROGRAM-FIXTURE')
            with patch('core.source_build.subprocess.run',return_value=SimpleNamespace(returncode=1)) as build:
                with self.assertRaises(RuntimeError):ensure_helper_artifact_current(repo,'updream-bridge',artifact)
            build.assert_called_once()
            self.assertEqual(artifact.read_bytes(),b'OLD-PROGRAM-FIXTURE')
            self.assertFalse(artifact.with_name(artifact.name+'.public-source.json').exists())
