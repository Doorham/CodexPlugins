from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/plugin-station"))
from core.control import ControlService
from core.source_build import build_voice_bridge


class VoiceFirstInstallTests(unittest.TestCase):
    def prepare(self, root):
        # Only distributed source files; never copy a build or installed EXE.
        for relative in ("helpers/wetype-awesun-bridge/src/Program.cs",
                         "helpers/wetype-awesun-bridge/assets/voice.ico"):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        service = ControlService.__new__(ControlService)
        service.repo_root = root
        plugin = json.loads((ROOT / "apps/plugin-station/plugins/wetype-awesun-bridge/plugin.json").read_text(encoding="utf-8-sig"))
        return service, plugin

    @unittest.skipUnless(os.name == "nt", "Windows compiler required")
    def test_fresh_source_only_install_builds_and_installs(self):
        with tempfile.TemporaryDirectory(prefix="voice source only ") as directory:
            root = Path(directory)
            service, plugin = self.prepare(root)
            exe = root / "installed/WeTypeAweSunBridge.exe"
            built = root / plugin["installSource"]
            self.assertFalse(exe.exists())
            self.assertFalse(built.exists())
            service._ensure_installed(plugin, exe)
            self.assertEqual(exe.read_bytes()[:2], b"MZ")
            self.assertEqual(exe.read_bytes(), built.read_bytes())
            with mock.patch("core.control.build_voice_bridge") as builder:
                service._ensure_installed(plugin, exe)
                builder.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows compiler required")
    def test_first_enable_builds_before_startup_and_launch(self):
        with tempfile.TemporaryDirectory(prefix="first enable ") as directory:
            root = Path(directory)
            service, plugin = self.prepare(root)
            exe = root / "installed/WeTypeAweSunBridge.exe"
            launched = []
            startup = []
            service._plugin_pids = lambda unused: [4242] if launched else []
            service._startup_enabled = lambda *args: False
            def set_startup(*args):
                self.assertTrue(exe.is_file(), "startup must follow successful installation")
                startup.append(args[-1])
            service._set_startup = set_startup
            real_popen = subprocess.Popen
            def launch(args, *positional, **kwargs):
                if args[0] == str(exe):
                    self.assertEqual(exe.read_bytes()[:2], b"MZ")
                    launched.append(args)
                    return object()
                return real_popen(args, *positional, **kwargs)
            with mock.patch("core.control.subprocess.Popen", side_effect=launch), mock.patch("core.control.time.sleep"):
                result = service._toggle_enabled(plugin, exe)
            self.assertEqual(startup, [True])
            self.assertEqual(len(launched), 1)
            self.assertIn("已开启", result)

    @unittest.skipUnless(os.name == "nt", "Windows compiler required")
    def test_build_failure_does_not_enable_startup_or_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service, plugin = self.prepare(root)
            exe = root / "installed/WeTypeAweSunBridge.exe"
            service._plugin_pids = lambda unused: []
            service._startup_enabled = lambda *args: False
            service._set_startup = mock.Mock()
            failed = subprocess.CompletedProcess([], 1, b"failure", b"")
            with mock.patch("core.source_build.subprocess.run", return_value=failed):
                with self.assertRaisesRegex(RuntimeError, "自动构建失败"):
                    service._toggle_enabled(plugin, exe)
            service._set_startup.assert_not_called()
            self.assertFalse(exe.exists())
            self.assertFalse(list((root / "artifacts/helpers").glob("*.building.exe")))

    def test_other_plugins_cannot_trigger_this_builder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service, plugin = self.prepare(root)
            plugin["id"] = "unreviewed-module"
            with mock.patch("core.control.build_voice_bridge") as builder:
                with self.assertRaises(FileNotFoundError):
                    service._ensure_installed(plugin, root / "installed/WeTypeAweSunBridge.exe")
                builder.assert_not_called()

    def test_output_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                build_voice_bridge(root, root / "wrong.exe")

    def test_missing_source_reports_incomplete_distribution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(FileNotFoundError, "安装源码不完整"):
                build_voice_bridge(root, root / "artifacts/helpers/WeTypeAweSunBridge.exe")


if __name__ == "__main__":
    unittest.main()
