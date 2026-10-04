"""Exercise the real desktop bridge without opening a system file dialog."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


class CompanyJsonUiTests(unittest.TestCase):
    def bridge(self, selection):
        tree = ast.parse((ROOT / "apps/plugin-station/app.py").read_text("utf-8"))
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        api = next(n for n in main.body if isinstance(n, ast.ClassDef) and n.name == "DesktopApi")
        window = Mock()
        window.create_file_dialog.return_value = selection
        service = Mock()
        namespace = {"APP_WINDOW": window, "webview": SimpleNamespace(FileDialog=SimpleNamespace(OPEN="open"))}
        exec(compile(ast.Module(body=[api], type_ignores=[]), "desktop-api", "exec"), namespace)
        instance = object.__new__(namespace["DesktopApi"])
        instance._service = service
        return instance, window, service

    def test_cancel_does_not_change_module_state(self):
        api, window, service = self.bridge(None)
        self.assertTrue(api.import_company_json()["cancelled"])
        service.import_company_guide.assert_not_called()
        self.assertFalse(window.create_file_dialog.call_args.kwargs["allow_multiple"])

    def test_selected_json_uses_existing_validated_importer(self):
        api, window, service = self.bridge(["received-guide.json"])
        expected = {"ok": True, "message": "imported"}
        service.import_company_guide.return_value = expected
        self.assertIs(api.import_company_json(), expected)
        service.import_company_guide.assert_called_once_with("received-guide.json")
        self.assertEqual(window.create_file_dialog.call_args.kwargs["file_types"], ("Company guide (*.json)",))

    def test_validation_failure_is_returned_without_restart(self):
        api, window, service = self.bridge(["invalid.json"])
        service.import_company_guide.return_value = {"ok": False, "message": "invalid guide"}
        self.assertFalse(api.import_company_json()["ok"])
        window.destroy.assert_not_called()

