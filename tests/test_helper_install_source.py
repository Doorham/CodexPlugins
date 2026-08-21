from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1] / "apps" / "plugin-station"
sys.path.insert(0, str(APP_ROOT))

from core.control import ControlService  # noqa: E402


class HelperInstallSourceTests(unittest.TestCase):
    def test_missing_helper_is_installed_atomically_from_build_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            repo_root = Path(temporary_root)
            source = repo_root / "artifacts" / "helpers" / "CodexAnswerChime.exe"
            target = repo_root / "install" / "CodexAnswerChime.exe"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"built-helper")
            service = object.__new__(ControlService)
            service.repo_root = repo_root

            service._ensure_installed({"installSource": "artifacts/helpers/CodexAnswerChime.exe"}, target)

            self.assertEqual(target.read_bytes(), b"built-helper")
            self.assertFalse(target.with_suffix(".installing").exists())

    def test_install_source_cannot_escape_the_build_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            repo_root = Path(temporary_root)
            outside = repo_root / "outside.exe"
            outside.write_bytes(b"not-allowed")
            service = object.__new__(ControlService)
            service.repo_root = repo_root

            with self.assertRaises(ValueError):
                service._ensure_installed({"installSource": "outside.exe"}, repo_root / "install" / "outside.exe")


if __name__ == "__main__":
    unittest.main()
