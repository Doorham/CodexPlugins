from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[1] / "apps" / "plugin-station"
sys.path.insert(0, str(APP_ROOT))

from core.control import ControlService  # noqa: E402


class PrivateStatusMetricTests(unittest.TestCase):
    def test_voltage_estimate_is_rendered_without_sound_details(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            status_file = root / "status.json"
            status_file.write_text(json.dumps({
                "online": True,
                "percent": 97,
                "voltageMv": 4134,
                "estimated": True,
            }), encoding="utf-8")
            plugin = {
                "id": "private-test-battery",
                "handler": "process_app",
                "executable": str(root / "TestBatteryMonitor.exe"),
                "processName": "TestBatteryMonitor.exe",
                "startup": {"type": "run", "name": "Test Battery Monitor"},
                "statusFile": str(status_file),
            }
            service = object.__new__(ControlService)
            service._startup_enabled = lambda *_: True
            with patch("core.control.process_pids", return_value=[321]):
                result = service._process_status(plugin)
            self.assertEqual(result["metric"], {
                "value": "≈97%",
                "label": "4134 mV · 电压估算",
                "state": "online",
            })
            self.assertNotIn("提示音", " ".join(result["detailLines"]))

    def test_offline_headset_is_distinct_from_disabled_monitor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            status_file = Path(temporary_root) / "status.json"
            status_file.write_text('{"online": false}', encoding="utf-8")
            service = object.__new__(ControlService)
            plugin = {"statusFile": str(status_file)}
            metric, _ = service._local_status_metric(plugin, True)
            self.assertEqual(metric["value"], "离线")
            metric, _ = service._local_status_metric(plugin, False)
            self.assertEqual(metric["value"], "已停用")


if __name__ == "__main__":
    unittest.main()
