from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "plugin-station"))
from core.control import ControlService  # noqa: E402
from core.updream_bridge import generate_image  # noqa: E402


class UpdreamBridgeTests(unittest.TestCase):
    def test_public_manifest_keeps_credentials_local(self) -> None:
        manifest = json.loads((ROOT / "apps/plugin-station/plugins/updream-bridge/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["moduleVersion"], "1.1.2")
        self.assertTrue(manifest["updateInstallSource"])
        self.assertTrue(manifest["agentAccess"]["enabled"])
        self.assertEqual(manifest["handler"], "updream_bridge")
        self.assertIn("generate_image", manifest["agentAccess"]["actions"])
        self.assertTrue(manifest["localDataPolicy"]["containsCredentials"])
        self.assertFalse(manifest["localDataPolicy"]["upload"])
        self.assertEqual(len(manifest["supportFiles"]), 4)
        self.assertFalse((ROOT / "helpers/updream-bridge/skill/SKILL.md").exists())
        self.assertFalse((ROOT / "scripts/install-updream-bridge-skill.ps1").exists())
        for name in ("bootstrap.ps1", "update-from-origin.ps1"):
            self.assertNotIn("install-updream-bridge-skill", (ROOT / "scripts" / name).read_text(encoding="utf-8"))

    def test_agent_manifest_describes_builtin_generation(self) -> None:
        manifest = json.loads((ROOT / "apps/plugin-station/plugins/updream-bridge/plugin.json").read_text(encoding="utf-8"))
        manifest["_scope"] = "shared"
        service = object.__new__(ControlService)
        service.plugins = {"updream-bridge": manifest}
        entry = service.agent_manifest()["plugins"][0]
        self.assertIn("generate_image", entry["actions"])
        self.assertIn("prompt", entry["actionInfo"]["generate_image"]["payload"])

    def test_builtin_generation_uses_toolbox_script_and_returns_only_local_images(self) -> None:
        response = {"ok": True, "task_id": "task-1", "cost": 5,
                    "images": [{"path": "C:/images/result.png", "bytes": 123, "url": "https://private.example/image"}]}
        with patch("core.updream_bridge.subprocess.run", return_value=SimpleNamespace(
            returncode=0, stdout=json.dumps(response))) as run:
            result = generate_image(ROOT, {"prompt": "一张雪山照片"})
        self.assertEqual(result["images"], [{"path": "C:/images/result.png", "bytes": 123}])
        command = run.call_args.args[0]
        self.assertEqual(Path(command[1]), ROOT / "helpers/updream-bridge/updream_gen.py")
        self.assertIn("--json", command)

    def test_builtin_generation_rejects_unknown_options_before_submit(self) -> None:
        with patch("core.updream_bridge.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "不支持的生图参数"):
                generate_image(ROOT, {"prompt": "测试", "shell": "bad"})
        run.assert_not_called()

    def test_builtin_generation_passes_structured_midjourney_options(self) -> None:
        response = {"ok": True, "task_id": "mj-1", "cost": 5, "images": []}
        with patch("core.updream_bridge.subprocess.run", return_value=SimpleNamespace(
            returncode=0, stdout=json.dumps(response))) as run:
            generate_image(ROOT, {"prompt": "测试", "model": "mj", "mj": {"version": "v8.2", "stylize": 100, "raw": True}})
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--model") + 1], "mj")
        self.assertEqual(command[command.index("--mj-stylize") + 1], "100")
        self.assertIn("--mj-raw", command)

    def test_agent_action_routes_through_toolbox_handler(self) -> None:
        manifest = json.loads((ROOT / "apps/plugin-station/plugins/updream-bridge/plugin.json").read_text(encoding="utf-8"))
        service = object.__new__(ControlService)
        service.plugins = {"updream-bridge": manifest}
        service.repo_root = ROOT
        service._lock = threading.RLock()
        with patch("core.control.generate_updream_image", return_value={"images": [], "message": "图片已保存到本机"}) as generate, \
             patch.object(service, "_plugin_status", return_value={}):
            result = service.perform_action("updream-bridge", "generate_image", {"prompt": "测试"}, origin="agent")
        self.assertTrue(result["ok"])
        generate.assert_called_once_with(ROOT, {"prompt": "测试"})

    def test_installer_refreshes_changed_executable_without_touching_local_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "artifacts/helpers/UpdreamBridgeConfig.exe"
            target = root / ".runtime/CompanyAIHelpers/Fixture/UpdreamBridgeConfig.exe"
            source.parent.mkdir(parents=True)
            target.parent.mkdir(parents=True)
            source.write_bytes(b"public build")
            target.write_bytes(b"old build")
            credentials = root / ".runtime/CompanyAIHelpers/Fixture/credentials.json"
            credentials.write_text("private", encoding="utf-8")
            service = object.__new__(ControlService)
            service.repo_root = root
            plugin = {"executable": str(target), "installSource": "artifacts/helpers/UpdreamBridgeConfig.exe", "updateInstallSource": True,
                      "processName": "UpdreamBridgeConfig.exe"}
            with patch("core.control.process_pids", return_value=[]):
                service._ensure_installed(plugin, target)
            self.assertEqual(target.read_bytes(), b"public build")
            self.assertEqual(credentials.read_text(encoding="utf-8"), "private")
            with patch("core.control.process_pids", side_effect=AssertionError("unchanged binary should not check processes")):
                service._ensure_installed(plugin, target)

    def test_installer_refuses_to_replace_running_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "artifacts/helpers/UpdreamBridgeConfig.exe"
            target = root / ".runtime/CompanyAIHelpers/Fixture/UpdreamBridgeConfig.exe"
            source.parent.mkdir(parents=True)
            target.parent.mkdir(parents=True)
            source.write_bytes(b"new build")
            target.write_bytes(b"running build")
            service = object.__new__(ControlService)
            service.repo_root = root
            plugin = {"executable": str(target), "installSource": "artifacts/helpers/UpdreamBridgeConfig.exe", "updateInstallSource": True,
                      "processName": "UpdreamBridgeConfig.exe"}
            with patch("core.control.process_pids", return_value=[123]):
                with self.assertRaisesRegex(RuntimeError, "仍在运行"):
                    service._ensure_installed(plugin, target)
            self.assertEqual(target.read_bytes(), b"running build")


if __name__ == "__main__":
    unittest.main()
