from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


APP_ROOT = Path(__file__).resolve().parents[1] / "apps" / "plugin-station"
sys.path.insert(0, str(APP_ROOT))

from core import control  # noqa: E402
from core.control import ControlService  # noqa: E402


class DummyKey:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class ProxyRegistryDefaultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = object.__new__(ControlService)
        self.plugin = {"domains": ["example.com"]}

    def test_status_uses_safe_defaults_when_internet_settings_key_is_missing(self) -> None:
        with (
            patch.object(control.winreg, "OpenKey", side_effect=FileNotFoundError),
            patch.object(self.service, "_load_custom_domain_records", return_value={}),
            patch.object(control, "clash_bypass_status", return_value={"available": False, "complete": False}),
        ):
            status = self.service._proxy_status(self.plugin)

        self.assertFalse(status["installed"])
        self.assertFalse(status["running"])
        self.assertEqual(status["statusText"], "内置 0/2 · 自定义 0")
        self.assertIn("系统代理保持：未设置", status["detailLines"])

    def test_inventory_is_readable_when_proxy_override_is_missing(self) -> None:
        with (
            patch.object(control.winreg, "OpenKey", return_value=DummyKey()),
            patch.object(control.winreg, "QueryValueEx", side_effect=FileNotFoundError),
            patch.object(self.service, "_load_custom_domain_records", return_value={}),
        ):
            inventory = self.service._proxy_domain_inventory(self.plugin)

        self.assertEqual(inventory[0]["domain"], "example.com")
        self.assertEqual(inventory[0]["activeCount"], 0)

    def test_add_domain_creates_only_the_requested_override_value(self) -> None:
        set_value = MagicMock()
        with (
            patch.object(control.winreg, "CreateKeyEx", return_value=DummyKey()),
            patch.object(control.winreg, "QueryValueEx", side_effect=FileNotFoundError),
            patch.object(control.winreg, "SetValueEx", set_value),
            patch.object(self.service, "_load_custom_domain_records", return_value={}),
            patch.object(self.service, "_save_custom_domain_records"),
            patch.object(self.service, "_sync_clash_verge_bypass"),
            patch.object(self.service, "_refresh_wininet"),
        ):
            message = self.service._proxy_action(self.plugin, "add_domain", {"domain": "new.example"})

        self.assertEqual(message, "添加成功：new.example 和 *.new.example")
        set_value.assert_called_once()
        self.assertEqual(set_value.call_args.args[1], "ProxyOverride")
        self.assertEqual(set_value.call_args.args[4], "new.example;*.new.example")

    def test_delete_domain_does_not_create_an_absent_override_value(self) -> None:
        records = {"new.example": {"new.example", "*.new.example"}}
        save_records = MagicMock()
        set_value = MagicMock()
        with (
            patch.object(control.winreg, "OpenKey", return_value=DummyKey()),
            patch.object(control.winreg, "QueryValueEx", side_effect=FileNotFoundError),
            patch.object(control.winreg, "SetValueEx", set_value),
            patch.object(self.service, "_load_custom_domain_records", return_value=records),
            patch.object(self.service, "_save_custom_domain_records", save_records),
            patch.object(self.service, "_sync_clash_verge_bypass"),
            patch.object(self.service, "_refresh_wininet"),
        ):
            message = self.service._proxy_action(self.plugin, "delete_domain", {"domain": "new.example"})

        self.assertEqual(message, "已删除自定义主站：new.example")
        set_value.assert_not_called()
        self.assertEqual(save_records.call_args.args[1], {})


if __name__ == "__main__":
    unittest.main()
