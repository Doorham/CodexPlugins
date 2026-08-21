from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1] / "apps" / "plugin-station"
import sys

sys.path.insert(0, str(APP_ROOT))

from core.clash_verge_bypass import (  # noqa: E402
    DEFAULT_WINDOWS_BYPASS,
    clash_bypass_status,
    split_bypass,
    sync_clash_verge_bypass,
)


class ClashVergeBypassTests(unittest.TestCase):
    def _config(self, root: Path, bypass: str = "null", use_default: str = "true") -> Path:
        config = root / "verge.yaml"
        config.write_text(
            "language: zh\n"
            f"use_default_bypass: {use_default}\n"
            f"system_proxy_bypass: {bypass}\n"
            "secret: do-not-touch\n",
            encoding="utf-8",
        )
        return config

    def test_sync_expands_defaults_backs_up_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = self._config(root)
            backups = root / "backups"
            first = sync_clash_verge_bypass(
                ["example.cn", "*.example.cn"],
                config=config,
                backup_root=backups,
            )
            self.assertTrue(first["changed"])
            self.assertIn("use_default_bypass: false", config.read_text(encoding="utf-8"))
            self.assertIn("secret: do-not-touch", config.read_text(encoding="utf-8"))
            self.assertEqual(Path(first["backup"]).read_text(encoding="utf-8"), (
                "language: zh\nuse_default_bypass: true\nsystem_proxy_bypass: null\nsecret: do-not-touch\n"
            ))
            status = clash_bypass_status(["example.cn", "*.example.cn"], config=config)
            self.assertTrue(status["complete"])
            self.assertEqual(status["installed"], 2)

            second = sync_clash_verge_bypass(
                ["example.cn", "*.example.cn"],
                config=config,
                backup_root=backups,
            )
            self.assertFalse(second["changed"])

    def test_sync_preserves_user_entries_and_removes_only_owned_entries(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = self._config(root, '"user.example;remove.example;*.remove.example"', "false")
            sync_clash_verge_bypass(
                ["required.example", "*.required.example"],
                config=config,
                backup_root=root / "backups",
                remove=["remove.example", "*.remove.example"],
            )
            line = next(
                item for item in config.read_text(encoding="utf-8").splitlines()
                if item.startswith("system_proxy_bypass:")
            )
            entries = split_bypass(line.split(":", 1)[1].strip().strip('"'))
            folded = {item.casefold() for item in entries}
            self.assertIn("user.example", folded)
            self.assertIn("required.example", folded)
            self.assertNotIn("remove.example", folded)
            self.assertTrue(set(DEFAULT_WINDOWS_BYPASS).issubset(entries))

    def test_missing_clash_verge_is_a_safe_noop(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "missing.yaml"
            result = sync_clash_verge_bypass(["example.cn"], config=missing)
            self.assertFalse(result["available"])
            self.assertFalse(result["changed"])


if __name__ == "__main__":
    unittest.main()
