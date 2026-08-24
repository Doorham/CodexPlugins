from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "apps" / "plugin-station"
sys.path.insert(0, str(APP_ROOT))

from core.control import ControlService  # noqa: E402


SOFTWARE_MANIFEST = APP_ROOT / "plugins" / "software-environment-checker" / "plugin.json"
CODEX_MANIFEST = APP_ROOT / "plugins" / "codex-environment-helper" / "plugin.json"
SOURCE = ROOT / "helpers" / "environment-detector" / "src" / "Program.cs"
ARTIFACT = ROOT / "artifacts" / "helpers" / "EnvironmentDetector.exe"


class EnvironmentDetectorTests(unittest.TestCase):
    def test_two_modules_share_one_executable_with_distinct_modes(self) -> None:
        software = json.loads(SOFTWARE_MANIFEST.read_text(encoding="utf-8"))
        codex = json.loads(CODEX_MANIFEST.read_text(encoding="utf-8"))

        self.assertEqual(software["moduleVersion"], "1.0.1")
        self.assertEqual(codex["moduleVersion"], "1.0.1")
        self.assertEqual(software["executable"], codex["executable"])
        self.assertEqual(software["installSource"], codex["installSource"])
        self.assertEqual(software["processName"], "EnvironmentDetector.exe")
        self.assertEqual(software["startArguments"], ["--mode", "software"])
        self.assertEqual(codex["startArguments"], ["--mode", "codex"])

    def test_release_index_lists_both_public_modules(self) -> None:
        release = json.loads((ROOT / "ONLINE-RELEASE.json").read_text(encoding="utf-8"))
        versions = {item["id"]: item["version"] for item in release["modules"]}
        self.assertEqual(versions["software-environment-checker"], "1.0.1")
        self.assertEqual(versions["codex-environment-helper"], "1.0.1")

    def test_process_handler_passes_reviewed_start_arguments_without_shell(self) -> None:
        service = object.__new__(ControlService)
        plugin = {
            "executable": str(ROOT / "fake" / "EnvironmentDetector.exe"),
            "processName": "EnvironmentDetector.exe",
            "startArguments": ["--mode", "codex"],
        }
        with patch.object(service, "_ensure_installed"), patch("core.control.subprocess.Popen") as popen, patch(
            "core.control.time.sleep"
        ):
            result = service._process_action(plugin, "start", {})

        self.assertEqual(result, "已启动")
        self.assertEqual(popen.call_args.args[0], [plugin["executable"], "--mode", "codex"])
        self.assertNotIn("shell", popen.call_args.kwargs)

    def test_source_has_public_identity_and_no_personal_or_internal_paths(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("CODEX TOOLS  ·  开发环境工具", source)
        self.assertIn('repairButton.Text = needsRepair ? "一键自动补全" : "已配置齐全"', source)
        self.assertNotIn("私人模块", source)
        self.assertNotIn("C:\\Users\\", source)
        self.assertNotIn("Y:\\", source)
        self.assertNotIn("仅保存在此电脑", source)

    def test_utf8_code_page_changes_have_backup_and_two_way_rollback(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('SaveSnapshot(original, "utf8-original")', source)
        self.assertIn('SaveSnapshot(beforeRestore, "restore-safety")', source)
        self.assertGreaterEqual(source.count("WriteSnapshot(beforeRestore)"), 1)
        self.assertGreaterEqual(source.count("WriteSnapshot(original)"), 2)
        self.assertIn("RunFileFormatSelfTest", source)

    def test_window_can_switch_pages_without_interrupting_background_completion(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("private bool backgroundOperationRunning;", source)
        self.assertIn("private List<CheckResult> lastAllResults", source)
        self.assertIn("List<CheckResult> repairInput = lastResults.ToList();", source)
        self.assertIn("RepairEngine.Repair(repairInput)", source)
        self.assertIn("正在后台继续，可安全查看本页", source)
        timer_start = source.index("requestTimer.Tick += async delegate")
        timer_end = source.index("Shown += async delegate", timer_start)
        self.assertNotIn("if (scanRunning) return", source[timer_start:timer_end])

    def test_online_updater_atomically_deploys_the_single_helper(self) -> None:
        updater = (ROOT / "scripts" / "update-from-origin.ps1").read_text(encoding="utf-8")
        self.assertIn(
            "Install-BuiltHelper 'EnvironmentDetector.exe' 'EnvironmentDetector' 'EnvironmentDetector'",
            updater,
        )

    @unittest.skipUnless(ARTIFACT.is_file(), "run scripts/build-helpers.ps1 first")
    def test_built_helper_runs_non_destructive_scenarios_and_both_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            temporary = Path(temporary_root)
            scenario = temporary / "scenario.txt"
            software_report = temporary / "software.txt"
            codex_report = temporary / "codex.txt"
            subprocess.run([str(ARTIFACT), "--self-test-scenarios", str(scenario)], check=True, timeout=30)
            subprocess.run(
                [str(ARTIFACT), "--mode", "software", "--report", str(software_report)],
                check=True,
                timeout=60,
            )
            subprocess.run(
                [str(ARTIFACT), "--mode", "codex", "--report", str(codex_report)],
                check=True,
                timeout=60,
            )

            scenario_text = scenario.read_text(encoding="utf-8")
            self.assertIn("PYTHON_MISSING=PASS", scenario_text)
            self.assertIn("INTEGRATION_MISSING=PASS", scenario_text)
            self.assertIn("WINGET_MISSING=PASS", scenario_text)
            self.assertIn("UTF8_BACKUP_FORMAT=PASS", scenario_text)
            self.assertIn("SYSTEM_CHANGES=0", scenario_text)
            self.assertIn("软件安装检查 v1.0.1", software_report.read_text(encoding="utf-8"))
            self.assertIn("Codex 环境补全 v1.0.1", codex_report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
