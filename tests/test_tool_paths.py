import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/plugin-station"))
from core.tool_paths import TOOL_DATA_ROOT, expand_tool_path, legacy_runtime_roots
from core.company_access import CompanyAccess


class ToolPathsTests(unittest.TestCase):
    def test_runtime_is_derived_from_workspace(self):
        self.assertEqual(TOOL_DATA_ROOT, ROOT / ".runtime" / "CompanyAIHelpers")
        self.assertNotIn("Packages", TOOL_DATA_ROOT.parts)

    def test_old_private_manifest_resolves_without_editing_appdata(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Other\AppData\Local"}):
            self.assertEqual(expand_tool_path(r"%LOCALAPPDATA%\CompanyAIHelpers\Example\tool.exe"),
                             TOOL_DATA_ROOT / "Example" / "tool.exe")
            self.assertEqual(os.environ["LOCALAPPDATA"], r"C:\Other\AppData\Local")

    def test_current_manifest_uses_workspace_variable(self):
        self.assertEqual(expand_tool_path(r"%CODEXTOOLS_DATA_ROOT%\Example\tool.exe"),
                         TOOL_DATA_ROOT / "Example" / "tool.exe")

    def test_company_default_does_not_depend_on_launching_app(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Packaged\LocalCache"}):
            self.assertEqual(CompanyAccess().root, TOOL_DATA_ROOT / "CodexTools" / "CompanyAccess")

    def test_public_module_owned_paths_are_not_appdata(self):
        for manifest in (ROOT / "apps/plugin-station/plugins").glob("*/plugin.json"):
            with self.subTest(manifest=manifest.parent.name):
                text = manifest.read_text(encoding="utf-8")
                json.loads(text)
                self.assertNotIn(r"%LOCALAPPDATA%\\CompanyAIHelpers", text)

    def test_webview_cache_is_explicit_and_private_runtime_is_ignored(self):
        app = (ROOT / "apps/plugin-station/app.py").read_text(encoding="utf-8")
        self.assertIn('storage_path=str(TOOL_DATA_ROOT', app)
        self.assertIn('.runtime/', (ROOT / '.gitignore').read_text(encoding='utf-8'))

    def test_legacy_inventory_is_only_owned_roots(self):
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder)
            normal = local / 'CompanyAIHelpers'
            cache = local / 'Packages/OpenAI.Codex_example/LocalCache/Local/CompanyAIHelpers'
            normal.mkdir()
            cache.mkdir(parents=True)
            (local / 'Packages/Unrelated.App/LocalCache/Local/CompanyAIHelpers').mkdir(parents=True)
            self.assertEqual(set(legacy_runtime_roots(local)), {normal, cache})
            self.assertEqual(legacy_runtime_roots(local / 'Missing'), [])

    def test_startup_guards_before_creating_an_empty_private_layer(self):
        app = (ROOT / 'apps/plugin-station/app.py').read_text(encoding='utf-8')
        self.assertLess(app.index('if legacy_runtime_roots():'), app.index('mutex = acquire_single_instance()'))
        migration = (ROOT / 'scripts/migrate-workspace-runtime.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('if ($priorRestoreEnabled)', migration)
        self.assertIn('a.refresh_connector()', migration)
        self.assertIn('Complete Exit', migration)
        self.assertNotIn("Start-Process -FilePath (Join-Path $env:WINDIR 'System32\\wscript.exe')", migration)

    def test_updater_only_stops_the_owned_installed_executable(self):
        updater = ROOT / 'scripts/update-from-hub.ps1'
        if not updater.is_file():
            updater = ROOT / 'scripts/update-from-origin.ps1'
        self.assertIn('[string]::Equals($_.Path, $target, [StringComparison]::OrdinalIgnoreCase)',
                      updater.read_text(encoding='utf-8-sig'))


if __name__ == "__main__":
    unittest.main()
