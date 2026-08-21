from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "apps" / "plugin-station" / "plugins" / "proxy-bypass" / "plugin.json"
RELEASE_PATH = REPO_ROOT / "ONLINE-RELEASE.json"
INSTALLER_PATH = REPO_ROOT / "system" / "proxy-override" / "install.ps1"
APP_PATH = REPO_ROOT / "apps" / "plugin-station" / "app.py"
BOOTSTRAP_PATH = REPO_ROOT / "scripts" / "bootstrap.ps1"
UPDATER_PATH = REPO_ROOT / "scripts" / "update-from-origin.ps1"
EXPECTED_DOMAINS = {
    "xiaoheihe.cn",
    "max-c.com",
    "maxjia.com",
    "360.cn",
    "360safe.com",
    "360tpcdn.com",
}


class ProxyBuiltinDomainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        cls.module = next(item for item in cls.release["modules"] if item["id"] == "cn-proxy-bypass")

    def test_shared_app_domains_are_builtin(self) -> None:
        domains = self.manifest["domains"]
        self.assertTrue(EXPECTED_DOMAINS.issubset(domains))
        self.assertEqual(len(domains), len(set(domains)))

    def test_manifest_and_module_index_agree(self) -> None:
        self.assertEqual(self.manifest["moduleVersion"], "1.2.0")
        self.assertEqual(self.module["version"], self.manifest["moduleVersion"])
        self.assertEqual(self.module["developers"], self.manifest["developers"])
        self.assertIn("Doorham", self.manifest["developers"])
        self.assertIn("Althy", self.manifest["developers"])

    def test_installer_and_manifest_domains_agree(self) -> None:
        installer = INSTALLER_PATH.read_text(encoding="utf-8")
        match = re.search(r"\$domains\s*=\s*@\((.*?)\n\)", installer, re.DOTALL)
        self.assertIsNotNone(match)
        installer_domains = set(re.findall(r"'([a-z0-9.-]+)'", match.group(1)))
        self.assertEqual(installer_domains, set(self.manifest["domains"]))

    def test_domains_are_plain_main_domains(self) -> None:
        for domain in EXPECTED_DOMAINS:
            self.assertNotIn("://", domain)
            self.assertFalse(domain.startswith("*."))
            self.assertEqual(domain, domain.lower())

    def test_bootstrap_update_and_first_restart_run_persistent_sync(self) -> None:
        app = APP_PATH.read_text(encoding="utf-8")
        bootstrap = BOOTSTRAP_PATH.read_text(encoding="utf-8")
        updater = UPDATER_PATH.read_text(encoding="utf-8")
        self.assertIn("def synchronize_proxy_bypass()", app)
        self.assertLess(
            app.index("synchronize_proxy_bypass()", app.index("def main()")),
            app.index("ControlService(ROOT)"),
        )
        self.assertIn("ensure-proxy-bypass.py", bootstrap)
        self.assertIn("ensure-proxy-bypass.py", updater)


if __name__ == "__main__":
    unittest.main()
