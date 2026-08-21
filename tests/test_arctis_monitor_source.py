import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ArctisMonitorSourceTests(unittest.TestCase):
    def test_public_manifest_uses_maintained_monitor_build(self):
        manifest = json.loads(
            (ROOT / "apps/plugin-station/plugins/arctis-nova-5-battery/plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["moduleVersion"], "1.0.2")
        self.assertEqual(manifest["installSource"], "artifacts/helpers/ArctisNova5BatteryMonitor.exe")
        self.assertNotIn("bundle", manifest)
        self.assertTrue((ROOT / "helpers/arctis-nova-5-battery-monitor/src/Program.cs").is_file())

    def test_monitor_icon_is_numeric_rounded_square(self):
        source = (ROOT / "helpers/arctis-nova-5-battery-monitor/src/Program.cs").read_text(encoding="utf-8")
        self.assertIn("RoundedRectangle", source)
        self.assertIn("LinearGradientBrush", source)
        self.assertIn("reading.Percent.ToString()", source)
        self.assertNotIn("FillEllipse", source)

    def test_updater_installs_the_monitor_atomically(self):
        updater = (ROOT / "scripts/update-from-origin.ps1").read_text(encoding="utf-8")
        self.assertIn(
            "Install-BuiltHelper 'ArctisNova5BatteryMonitor.exe' 'ArctisNova5BatteryMonitor' 'ArctisNova5BatteryMonitor'",
            updater,
        )


if __name__ == "__main__":
    unittest.main()
