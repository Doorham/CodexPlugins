from __future__ import annotations
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'apps' / 'plugin-station'
sys.path.insert(0, str(APP))
from core.company_access import CompanyAccess, COMPANY_ID, MODULE_IDS, protect, read_guide
from core.control import ControlService
from core.company_drives import ensure_mappings, expected_drives

class CompanyAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.access = CompanyAccess(self.base / 'CompanyAccess')
        self.guide = self.base / 'guide.json'
        self.data = {'format':'codextools-company-guide/v1', 'companyId':COMPANY_ID, 'modules':MODULE_IDS,
                     'config':{'defaultUser':'ExampleUser','drives':[{'letter':d,'remote':chr(92)*2+'nas.example'+chr(92)+'share-'+d} for d in 'WXYZ']},
                     'instructions':'Descriptive text; never executed'}
        self.write_guide()

    def tearDown(self): self.temp.cleanup()
    def write_guide(self): self.guide.write_text(json.dumps(self.data),encoding='utf-8')
    def import_guide(self):
        def build(folder): (folder/'NasRemoteConnect.exe').write_bytes(b'test-only stub; never executed')
        with patch('core.company_access.build_connector',side_effect=build):
            return self.access.import_guide(self.guide)

    def test_dpapi_roundtrip_and_tampering(self):
        secret=b'example-record'
        sealed=protect(secret)
        self.assertNotIn(secret,sealed)
        self.assertEqual(protect(sealed,decrypt=True),secret)
        with self.assertRaises(ValueError): protect(sealed[:-1],decrypt=True)

    def test_invalid_fields_rejected_before_build_or_state(self):
        for key,value in [('command','arbitrary'),('companyId','other'),('modules',['codex-network-drive-access']),('config',{'password':'forbidden'})]:
            with self.subTest(key=key):
                changed=dict(self.data);changed[key]=value
                self.guide.write_text(json.dumps(changed),encoding='utf-8')
                with patch('core.company_access.build_connector') as build, self.assertRaises(ValueError):
                    self.access.import_guide(self.guide)
                build.assert_not_called()
                self.assertFalse(self.access.root.exists())

    def test_missing_oversized_and_unsafe_config(self):
        with self.assertRaises(OSError): read_guide(self.base/'missing.json')
        self.guide.write_bytes(b' '*65537)
        with self.assertRaises(ValueError): read_guide(self.guide)
        self.data['config']['drives'][0]['remote']='not-a-share'
        self.write_guide()
        with self.assertRaises(ValueError): read_guide(self.guide)

    def test_file_is_portable_and_restart_preserves_activation(self):
        self.assertTrue(self.import_guide()['ok'])
        self.guide.unlink()
        self.assertTrue(CompanyAccess(self.access.root).active())
        self.assertTrue(self.access.payload_root().is_dir())
        self.assertFalse(self.access.active('other-company'))

    def test_tamper_and_deactivate_preserve_payload(self):
        self.import_guide();folder=self.access.payload_root()
        (folder/'nas-drives.json').write_text('{}')
        self.assertFalse(self.access.active())
        self.import_guide();folder=self.access.payload_root()
        self.access.deactivate()
        self.assertFalse(self.access.active())
        self.assertTrue((folder/'nas-drives.json').exists())

    def test_build_failure_preserves_previous_record(self):
        self.import_guide();before=self.access.record_file.read_bytes()
        folders=list((self.access.root/'payloads').iterdir())
        with patch('core.company_access.build_connector',side_effect=ValueError('failed')),self.assertRaises(ValueError):
            self.access.import_guide(self.guide)
        self.assertEqual(before,self.access.record_file.read_bytes())
        self.assertEqual(folders,list((self.access.root/'payloads').iterdir()))
        self.assertTrue(self.access.active())

    def test_actual_reviewed_compiler_and_no_mapping_on_import(self):
        with patch('core.company_drives._map_drive') as mapping:
            self.assertTrue(self.access.import_guide(self.guide)['ok'])
            mapping.assert_not_called()
        self.assertTrue(self.access.active())
        self.assertTrue((self.access.payload_root()/'NasRemoteConnect.exe').stat().st_size>1000)
        self.assertFalse((self.access.payload_root()/'tailscale-setup-1.102.4.exe').exists())

    def test_company_hidden_and_ui_agent_backend_gated(self):
        with patch('core.control.CompanyAccess', return_value=self.access), patch.dict(os.environ, {'LOCALAPPDATA':str(self.base)}), patch('core.company_drives._wnet_remote', return_value=None):
            service = ControlService(APP)
            self.assertNotIn('company-nas-remote-connect', service.plugins)
            self.assertNotIn('company-network-drive-access', service.plugins)
            self.assertFalse(service.perform_action('company-nas-remote-connect','start',{},origin='ui')['ok'])
            self.import_guide()
            service.plugins = service._load_plugins()
            self.assertEqual(service.plugins['company-nas-remote-connect']['_scope'], 'company')
            self.assertEqual(len(service.plugins['company-network-drive-access']['drives']),4)
            self.assertFalse(service.perform_action('company-nas-remote-connect','start',{},origin='agent')['ok'])
            with patch.object(service,'_process_action', return_value='started') as start, patch.object(service,'_plugin_status',return_value={}):
                self.assertTrue(service.perform_action('company-nas-remote-connect','start',{},origin='ui')['ok'])
                start.assert_called_once()
                self.access.deactivate()
                self.assertFalse(service.perform_action('company-nas-remote-connect','start',{},origin='ui')['ok'])
                self.assertFalse(service.perform_action('company-network-drive-access','refresh',{},origin='agent')['ok'])
                self.assertNotIn('company-network-drive-access',[p['id'] for p in service.agent_manifest()['plugins']])
                start.assert_called_once()

    def test_public_generic_preserves_non_company_network_drives(self):
        plugin = {'discoverMappedDrives':True}
        with patch('core.company_drives._wnet_remote', side_effect=lambda letter: r'\\user-server\documents' if letter=='N' else None), patch('core.company_drives._map_drive') as mapping:
            self.assertEqual(expected_drives(plugin)[0]['letter'],'N')
            self.assertEqual(ensure_mappings(plugin),[])
            mapping.assert_not_called()

    def test_company_repair_cannot_skip_nas_credentials(self):
        service=object.__new__(ControlService)
        with patch('core.control.probe_drives', return_value=[{'mappingMatches':False}]), patch('core.control.ensure_mappings') as mapper:
            with self.assertRaisesRegex(ValueError,'凭据'):
                service._network_drive_action({'companyId':COMPANY_ID},'repair')
            mapper.assert_not_called()

    def test_activation_does_not_gate_any_original_public_module(self):
        with patch('core.control.CompanyAccess',return_value=self.access), patch.dict(os.environ, {'LOCALAPPDATA':str(self.base)}), patch('core.company_drives._wnet_remote',return_value=None):
            service=ControlService(APP)
            originals={json.loads(p.read_text(encoding='utf-8'))['id'] for p in (APP/'plugins').glob('*/plugin.json') if not json.loads(p.read_text(encoding='utf-8')).get('companyId')}
            self.assertEqual(originals,{p['id'] for p in service.plugins.values() if p['_scope']=='shared'})
            self.assertEqual(len(originals),8)
            for plugin_id in originals:
                self.assertTrue(service._company_allowed(service.plugins[plugin_id]))
if __name__ == '__main__': unittest.main()
