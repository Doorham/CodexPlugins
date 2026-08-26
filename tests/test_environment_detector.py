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
MOON_ASSETS = ROOT / "helpers" / "environment-detector" / "assets" / "fluent-emoji-3d"


class EnvironmentDetectorTests(unittest.TestCase):
    def test_two_modules_share_one_executable_with_distinct_modes(self) -> None:
        software = json.loads(SOFTWARE_MANIFEST.read_text(encoding="utf-8"))
        codex = json.loads(CODEX_MANIFEST.read_text(encoding="utf-8"))

        self.assertEqual(software["moduleVersion"], "1.1.0")
        self.assertEqual(codex["moduleVersion"], "1.1.0")
        self.assertEqual(software["executable"], codex["executable"])
        self.assertEqual(software["installSource"], codex["installSource"])
        self.assertEqual(software["processName"], "EnvironmentDetector.exe")
        self.assertEqual(software["startArguments"], ["--mode", "software"])
        self.assertEqual(codex["startArguments"], ["--mode", "codex"])
        self.assertEqual(software["supportFiles"], codex["supportFiles"])
        self.assertEqual(
            software["supportFiles"][0]["source"],
            "helpers/environment-detector/THIRD-PARTY-NOTICES.md",
        )

    def test_release_index_lists_both_public_modules(self) -> None:
        release = json.loads((ROOT / "ONLINE-RELEASE.json").read_text(encoding="utf-8"))
        versions = {item["id"]: item["version"] for item in release["modules"]}
        self.assertEqual(versions["software-environment-checker"], "1.1.0")
        self.assertEqual(versions["codex-environment-helper"], "1.1.0")

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

    def test_window_blocks_module_switch_and_close_during_background_completion(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("private bool backgroundOperationRunning;", source)
        self.assertIn("private List<CheckResult> lastAllResults", source)
        self.assertIn("List<CheckResult> repairInput = lastResults.ToList();", source)
        self.assertIn("backgroundOperationRunning && requestedCodexMode != codexMode", source)
        self.assertIn("e.CloseReason == CloseReason.UserClosing && backgroundOperationRunning", source)
        self.assertIn("ShowBusyWarning(false)", source)
        self.assertIn("ShowBusyWarning(true)", source)
        timer_start = source.index("requestTimer.Tick += async delegate")
        timer_end = source.index("Shown += async delegate", timer_start)
        self.assertNotIn("if (scanRunning) return", source[timer_start:timer_end])

    def test_background_completion_uses_moon_phase_animation_and_real_item_progress(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("internal sealed class MoonPhaseIndicator : Control", source)
        self.assertIn("private const int MoonPhaseCount = 8", source)
        moon_start = source.index("internal sealed class MoonPhaseIndicator : Control")
        moon_end = source.index("internal sealed class BusyStatusCard", moon_start)
        moon = source[moon_start:moon_end]
        self.assertIn("GetManifestResourceStream", moon)
        self.assertIn("EnvironmentDetector.Moon01Full.png", moon)
        self.assertIn("EnvironmentDetector.Moon08WaxingGibbous.png", moon)
        self.assertIn("Format32bppPArgb", moon)
        self.assertIn("WrapMode.TileFlipXY", moon)
        self.assertNotIn("Segoe UI Emoji", source)
        self.assertIn('StartBusyPresentation("正在补全运行环境", targets.Count)', source)
        self.assertIn("SetBusyProgress(name, position, total)", source)
        self.assertIn("当前项目：", source)
        self.assertIn("处理进度：", source)
        self.assertNotIn("ProgressBar", source)

    def test_official_fluent_moon_assets_and_license_are_packaged(self) -> None:
        expected = [
            "01-full-moon.png",
            "02-waning-gibbous.png",
            "03-last-quarter.png",
            "04-waning-crescent.png",
            "05-new-moon.png",
            "06-waxing-crescent.png",
            "07-first-quarter.png",
            "08-waxing-gibbous.png",
        ]
        self.assertEqual(sorted(path.name for path in MOON_ASSETS.glob("*.png")), expected)
        for name in expected:
            data = (MOON_ASSETS / name).read_bytes()
            self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        notice = (ROOT / "helpers" / "environment-detector" / "THIRD-PARTY-NOTICES.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Microsoft Fluent Emoji", notice)
        self.assertIn("MIT License", notice)
        build = (ROOT / "scripts" / "build-helpers.ps1").read_text(encoding="utf-8")
        self.assertIn("$environmentMoonResources", build)
        self.assertIn("EnvironmentDetector.Moon01Full.png", build)
        self.assertIn("EnvironmentDetector.Moon08WaxingGibbous.png", build)

    def test_installation_preview_is_visible_but_never_runs_repair_commands(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('"--preview-installation"', source)
        preview_start = source.index("private async Task RunInstallationPreview()")
        preview_end = source.index("private void UpdateRepairButtons()", preview_start)
        preview = source[preview_start:preview_end]
        self.assertIn("StartBusyPresentation", preview)
        self.assertIn("SetBusyProgress", preview)
        self.assertIn("Task.Delay", preview)
        self.assertNotIn("RepairEngine.Repair", preview)
        self.assertNotIn("RunRepairCommand", preview)
        self.assertNotIn("Utf8Repair.StartElevated", preview)

    def test_read_only_scan_reuses_moon_animation_without_install_lock(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        scan_start = source.index("private async Task RunScan()")
        scan_end = source.index("private async Task SwitchMode", scan_start)
        scan = source[scan_start:scan_end]
        self.assertIn('StartBusyPresentation(codexMode ? "正在检测可补全环境"', scan)
        self.assertIn('"检测中"', scan)
        self.assertIn("StopBusyPresentation()", scan)
        self.assertNotIn("backgroundOperationRunning = true", scan)

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
            self.assertIn("软件安装检查 v1.1.0", software_report.read_text(encoding="utf-8"))
            self.assertIn("Codex 环境补全 v1.1.0", codex_report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
