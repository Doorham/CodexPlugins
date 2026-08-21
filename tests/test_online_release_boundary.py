from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OnlineReleaseBoundaryTests(unittest.TestCase):
    def test_internal_only_paths_are_absent(self) -> None:
        forbidden = [
            "public" + "-hub",
            "third" + "_party",
            "apps/plugin-station/plugins/codex-" + "network-drive-access",
            "apps/plugin-station/core/network_" + "drive_access.py",
            "scripts/ensure-codex-" + "network-drive-access.py",
            "apps/plugin-station/plugins/logitech-" + "g435-battery",
        ]
        for relative in forbidden:
            self.assertFalse((ROOT / relative).exists(), relative)

    def test_source_tree_has_no_exact_internal_endpoints(self) -> None:
        forbidden_fragments = [
            "192" + ".168.3.",
            "Y:" + "\\Development\\" + "CodexTools",
        ]
        text_extensions = {".py", ".ps1", ".json", ".md", ".txt", ".js", ".html", ".css", ".vbs", ".cs"}
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in text_extensions:
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            for fragment in forbidden_fragments:
                self.assertNotIn(fragment, content, str(path.relative_to(ROOT)))

    def test_release_and_plugins_agree(self) -> None:
        release = json.loads((ROOT / "ONLINE-RELEASE.json").read_text(encoding="utf-8"))
        plugin_root = ROOT / "apps" / "plugin-station" / "plugins"
        plugin_ids = {
            json.loads(path.read_text(encoding="utf-8"))["id"]
            for path in plugin_root.glob("*/plugin.json")
        }
        release_ids = {item["id"] for item in release["modules"]}
        self.assertEqual(release_ids, plugin_ids)
        self.assertEqual(release["update"]["host"], "github.com")
        self.assertTrue(release["update"]["privateRepository"])

    def test_no_binary_payloads_are_shipped(self) -> None:
        forbidden_suffixes = {".exe", ".dll", ".msi", ".msix", ".zip", ".7z", ".rar", ".pfx", ".pem", ".key"}
        payloads = [
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*")
            if path.is_file() and path.suffix.lower() in forbidden_suffixes and "artifacts" not in path.parts
        ]
        self.assertEqual(payloads, [])


if __name__ == "__main__":
    unittest.main()
