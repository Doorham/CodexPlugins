from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UTF8_BOM = b"\xef\xbb\xbf"


class PowerShellScriptEncodingTests(unittest.TestCase):
    def test_all_powershell_scripts_are_utf8_with_bom(self) -> None:
        scripts = sorted(
            path
            for path in ROOT.rglob("*.ps1")
            if ".git" not in path.parts and ".runtime" not in path.parts
        )
        self.assertGreater(len(scripts), 0)
        for script in scripts:
            with self.subTest(script=script.relative_to(ROOT).as_posix()):
                payload = script.read_bytes()
                self.assertTrue(payload.startswith(UTF8_BOM), "missing UTF-8 BOM")
                payload[len(UTF8_BOM):].decode("utf-8", errors="strict")

    def test_gitattributes_only_normalizes_powershell_line_endings(self) -> None:
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.ps1 text eol=crlf", attributes)
        self.assertNotIn("working-tree-encoding", attributes)

    def test_bootstrap_uses_ascii_json_across_native_process_boundary(self) -> None:
        bootstrap = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8-sig")
        proxy = (ROOT / "scripts" / "ensure-proxy-bypass.py").read_text(encoding="utf-8")
        codex_proxy = (ROOT / "scripts" / "ensure-codex-system-proxy.py").read_text(encoding="utf-8")
        self.assertIn("Invoke-JsonBootstrapScript", bootstrap)
        self.assertIn("ConvertFrom-Json", bootstrap)
        self.assertIn("ensure_ascii=True", proxy)
        self.assertIn("ensure_ascii=True", codex_proxy)


if __name__ == "__main__":
    unittest.main()
