from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "apps" / "plugin-station"
sys.path.insert(0, str(APP_ROOT))

from core.codex_system_proxy import (  # noqa: E402
    config_status,
    diagnose_websocket,
    ensure_system_proxy_feature,
    find_codex_cli,
)
from core.control import ControlService  # noqa: E402


MANIFEST_PATH = APP_ROOT / "plugins" / "codex-system-proxy" / "plugin.json"
RELEASE_PATH = REPO_ROOT / "ONLINE-RELEASE.json"


class CodexSystemProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plugin = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_online_manifest_and_release_agree(self) -> None:
        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        module = next(item for item in release["modules"] if item["id"] == self.plugin["id"])
        self.assertEqual(release["version"], "0.11.5")
        self.assertEqual(self.plugin["moduleVersion"], "1.1.0")
        self.assertEqual(self.plugin["name"], "Codex 对话 timeout 修复")
        self.assertEqual(self.plugin["developers"], ["Althy"])
        self.assertEqual(module["version"], self.plugin["moduleVersion"])
        self.assertEqual(module["developers"], self.plugin["developers"])
        self.assertEqual(release["update"]["host"], "github.com")

    def test_adds_feature_with_backup_and_preserves_unrelated_config(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / ".codex" / "config.toml"
            backups = root / "backups"
            config.parent.mkdir(parents=True)
            original = 'model = "gpt-test"\n\n[desktop]\nlocaleOverride = "zh-CN"\n'
            config.write_text(original, encoding="utf-8")
            result = ensure_system_proxy_feature(config=config, backup_root=backups)
            self.assertTrue(result["changed"])
            self.assertEqual(Path(result["backup"]).read_text(encoding="utf-8"), original)
            parsed = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(parsed["model"], "gpt-test")
            self.assertEqual(parsed["desktop"]["localeOverride"], "zh-CN")
            self.assertIs(parsed["features"]["respect_system_proxy"], True)
            self.assertTrue(config_status(config)["configured"])

    def test_existing_false_feature_is_replaced_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / "config.toml"
            backups = root / "backups"
            original = "[features]\njs_repl = false\nrespect_system_proxy = false # employee setting\n"
            config.write_text(original, encoding="utf-8")
            first = ensure_system_proxy_feature(config=config, backup_root=backups)
            updated = config.read_text(encoding="utf-8")
            self.assertTrue(first["changed"])
            self.assertIn("respect_system_proxy = true # employee setting", updated)
            self.assertIs(tomllib.loads(updated)["features"]["js_repl"], False)
            second = ensure_system_proxy_feature(config=config, backup_root=backups)
            self.assertFalse(second["changed"])
            self.assertIsNone(second["backup"])
            self.assertEqual(config.read_text(encoding="utf-8"), updated)

    def test_dotted_feature_is_updated_without_duplicate_table(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.toml"
            config.write_text("features.respect_system_proxy = false\nmodel = 'test'\n", encoding="utf-8")
            ensure_system_proxy_feature(config=config)
            content = config.read_text(encoding="utf-8")
            self.assertIn("features.respect_system_proxy = true", content)
            self.assertNotIn("[features]", content)
            self.assertIs(tomllib.loads(content)["features"]["respect_system_proxy"], True)

    def test_nested_dotted_key_is_not_mistaken_for_top_level_feature(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.toml"
            config.write_text("[other]\nfeatures.respect_system_proxy = false\n", encoding="utf-8")
            ensure_system_proxy_feature(config=config)
            parsed = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertIs(parsed["other"]["features"]["respect_system_proxy"], False)
            self.assertIs(parsed["features"]["respect_system_proxy"], True)

    def test_invalid_toml_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.toml"
            original = "[features\nrespect_system_proxy = false\n"
            config.write_text(original, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "不是有效 TOML"):
                ensure_system_proxy_feature(config=config)
            self.assertEqual(config.read_text(encoding="utf-8"), original)

    def test_doctor_result_extracts_only_websocket_status(self) -> None:
        report = {
            "checks": {
                "auth.credentials": {"details": {"secret": "must-not-leak"}},
                "network.websocket_reachability": {
                    "status": "ok",
                    "summary": "Responses WebSocket handshake succeeded",
                    "details": {"handshake result": "HTTP 101 Switching Protocols"},
                    "durationMs": 1978,
                },
            }
        }

        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 1, json.dumps(report), "")

        result = diagnose_websocket(cli=Path("codex.exe"), runner=runner)
        self.assertTrue(result["ok"])
        self.assertEqual(result["handshake"], "HTTP 101 Switching Protocols")
        self.assertEqual(result["durationMs"], 1978)
        self.assertEqual(result["message"], "WebSocket 握手成功（HTTP 101）")
        self.assertNotIn("secret", json.dumps(result))

    def _plugin_status(self, *, configured: bool, proxy_enabled: bool = True, diagnostic=None):
        service = ControlService.__new__(ControlService)
        service._codex_proxy_diagnostic = diagnostic
        config = {
            "configured": configured,
            "conflict": False,
            "message": "Codex 已遵循 Windows 系统代理" if configured else "Codex 尚未遵循 Windows 系统代理",
        }
        system_proxy = {
            "enabled": proxy_enabled,
            "message": "系统代理已开启" if proxy_enabled else "系统代理未开启",
        }
        with mock.patch("core.control.codex_proxy_config_status", return_value=config), mock.patch(
            "core.control.windows_system_proxy_status", return_value=system_proxy
        ):
            return service._codex_proxy_status({})

    def test_unconfigured_state_only_offers_configuration(self) -> None:
        status = self._plugin_status(configured=False)
        self.assertEqual(status["statusText"], "待配置")
        self.assertFalse(status["running"])
        self.assertEqual(status["actions"], [{"id": "repair", "label": "配置系统代理", "kind": "primary"}])

    def test_configured_state_disables_repair_and_keeps_diagnostic(self) -> None:
        status = self._plugin_status(configured=True)
        self.assertEqual(status["statusText"], "已配置")
        self.assertTrue(status["running"])
        self.assertEqual([item["label"] for item in status["actions"]], ["已配置", "检测连接"])
        self.assertTrue(status["actions"][0]["disabled"])

    def test_failed_diagnostic_is_not_presented_as_missing_configuration(self) -> None:
        status = self._plugin_status(
            configured=True,
            diagnostic={"ok": False, "message": "WebSocket 仍未连接成功"},
        )
        self.assertEqual(status["statusText"], "连接检测失败")
        self.assertFalse(status["running"])
        self.assertEqual(status["actions"][0]["label"], "已配置")

    def test_system_proxy_off_is_visible_even_when_codex_is_configured(self) -> None:
        status = self._plugin_status(configured=True, proxy_enabled=False)
        self.assertEqual(status["statusText"], "已配置 · 系统代理未开启")
        self.assertFalse(status["running"])

    def test_web_ui_honors_disabled_status_actions(self) -> None:
        app_js = (APP_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("Boolean(action.disabled)", app_js)

    def test_local_codex_runtime_precedes_windowsapps_path(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            local = root / "OpenAI" / "Codex" / "bin" / "current" / "codex.exe"
            local.parent.mkdir(parents=True)
            local.write_bytes(b"test")
            with mock.patch.dict("os.environ", {"LOCALAPPDATA": str(root)}, clear=False), mock.patch(
                "core.codex_system_proxy.shutil.which", return_value=r"C:\Program Files\WindowsApps\OpenAI.Codex\codex.exe"
            ):
                self.assertEqual(find_codex_cli(), local)

    def test_bootstrap_update_and_startup_keep_feature_enabled(self) -> None:
        bootstrap = (REPO_ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        updater = (REPO_ROOT / "scripts" / "update-from-origin.ps1").read_text(encoding="utf-8")
        app = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("ensure-codex-system-proxy.py", bootstrap)
        self.assertIn("ensure-codex-system-proxy.py", updater)
        self.assertIn("def synchronize_codex_system_proxy()", app)
        self.assertLess(
            app.index("synchronize_codex_system_proxy()", app.index("def main()")),
            app.index("ControlService(ROOT)"),
        )


if __name__ == "__main__":
    unittest.main()
