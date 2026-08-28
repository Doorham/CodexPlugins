import json
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "apps" / "plugin-station"

import sys

sys.path.insert(0, str(APP_ROOT))

from core.control import ControlService  # noqa: E402


class ProcessKeepAliveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = object.__new__(ControlService)
        self.service.repo_root = ROOT
        self.service._keep_alive_attempts = {}
        self.service._keep_alive_errors = {}
        self.plugin = {
            "id": "test-helper",
            "name": "Test Helper",
            "moduleVersion": "1.0.0",
            "developers": ["Tester"],
            "description": "test",
            "category": "test",
            "handler": "process_app",
            "executable": r"%LOCALAPPDATA%\CompanyAIHelpers\TestHelper\TestHelper.exe",
            "processName": "TestHelper.exe",
            "startup": {"type": "run", "name": "Test Helper"},
            "keepAlive": True,
            "actions": ["toggle_enabled", "toggle_startup"],
            "uiActions": [{"id": "toggle_enabled", "label": "切换状态", "kind": "toggle"}],
            "agentAccess": {"enabled": False, "actions": []},
            "_scope": "shared",
        }

    def test_missing_enabled_process_is_recovered_once(self) -> None:
        with patch("core.control.process_pids", side_effect=[[], [4321]]), patch.object(
            self.service, "_startup_enabled", return_value=True
        ), patch.object(self.service, "_ensure_installed") as ensure, patch.object(
            self.service, "_start_plugin_process"
        ) as start, patch("core.control.time.sleep"):
            recovered = self.service._recover_keep_alive(self.plugin)

        self.assertTrue(recovered)
        ensure.assert_called_once()
        start.assert_called_once()
        self.assertNotIn(self.plugin["id"], self.service._keep_alive_errors)

    def test_disabled_startup_is_never_recovered(self) -> None:
        with patch("core.control.process_pids", return_value=[]), patch.object(
            self.service, "_startup_enabled", return_value=False
        ), patch.object(self.service, "_start_plugin_process") as start:
            recovered = self.service._recover_keep_alive(self.plugin)

        self.assertFalse(recovered)
        start.assert_not_called()

    def test_non_keep_alive_plugin_is_never_reconciled(self) -> None:
        plugin = dict(self.plugin, keepAlive=False)
        with patch.object(self.service, "_recover_keep_alive") as recover:
            self.service._sync_keep_alive_lifecycle(plugin)
        recover.assert_not_called()

    def test_three_failures_pause_automatic_recovery_for_ten_minutes(self) -> None:
        self.service._keep_alive_attempts[self.plugin["id"]] = [100.0, 101.0, 102.0]
        with patch("core.control.time.monotonic", return_value=103.0), patch(
            "core.control.process_pids", return_value=[]
        ), patch.object(self.service, "_startup_enabled", return_value=True), patch.object(
            self.service, "_start_plugin_process"
        ) as start:
            recovered = self.service._recover_keep_alive(self.plugin)

        self.assertFalse(recovered)
        start.assert_not_called()
        self.assertIn("停止自动重试", self.service._keep_alive_errors[self.plugin["id"]])

    def test_toggle_recovers_degraded_process_without_disabling_startup(self) -> None:
        with patch("core.control.process_pids", side_effect=[[], [], [4321]]), patch.object(
            self.service, "_startup_enabled", return_value=True
        ), patch.object(self.service, "_ensure_installed"), patch.object(
            self.service, "_start_plugin_process"
        ), patch.object(self.service, "_set_startup") as set_startup, patch("core.control.time.sleep"):
            message = self.service._toggle_enabled(self.plugin, Path("TestHelper.exe"))

        self.assertIn("已恢复运行", message)
        set_startup.assert_not_called()

    def test_degraded_card_offers_recovery_and_startup_disable(self) -> None:
        detail = {
            "installed": True,
            "running": False,
            "pids": [],
            "startupEnabled": True,
            "enabled": True,
            "recoveryAvailable": True,
            "statusText": "自动恢复已暂停",
            "detailLines": ["常驻保护：测试"],
            "metric": None,
        }
        with patch.object(self.service, "_process_status", return_value=detail):
            card = self.service._plugin_status(self.plugin)

        actions = {item["id"]: item for item in card["actions"]}
        self.assertEqual(actions["toggle_enabled"]["label"], "恢复运行")
        self.assertEqual(actions["toggle_startup"]["label"], "关闭自启")
        web = (APP_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("plugin.recoveryAvailable", web)

    def test_public_manifests_opt_in_only_the_two_non_hardware_background_helpers(self) -> None:
        manifests = {}
        for path in (APP_ROOT / "plugins").glob("*/plugin.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            manifests[payload["id"]] = payload

        self.assertTrue(manifests["codex-answer-chime"]["keepAlive"])
        self.assertTrue(manifests["updream-clipboard-cleaner"]["keepAlive"])
        self.assertEqual(manifests["codex-answer-chime"]["moduleVersion"], "1.1.0")
        self.assertEqual(manifests["updream-clipboard-cleaner"]["moduleVersion"], "1.0.3")
        self.assertFalse(manifests["software-environment-checker"].get("keepAlive", False))
        self.assertFalse(manifests["codex-environment-helper"].get("keepAlive", False))
        self.assertFalse(manifests["arctis-nova-5-battery"].get("keepAlive", False))


if __name__ == "__main__":
    unittest.main()
