from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
UPDATER = REPO_ROOT / "scripts" / "update-from-origin.ps1"
WINDOWS_POWERSHELL = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"


class UpdaterGitDiscoveryTests(unittest.TestCase):
    def test_updater_is_github_origin_only(self) -> None:
        source = UPDATER.read_text(encoding="utf-8")
        self.assertIn("function Resolve-GitExecutable", source)
        self.assertIn("function Test-GitHubRemote", source)
        self.assertIn("github.com", source)
        self.assertIn("'fetch', '--tags', $RemoteName, $Branch", source)
        self.assertNotIn("update-from-hub", source)
        self.assertNotIn("repository-state.json", source)

    @unittest.skipUnless(os.name == "nt" and WINDOWS_POWERSHELL.is_file(), "Windows PowerShell is required")
    def test_check_uses_bundled_git_with_a_local_test_remote(self) -> None:
        runtime_root = Path.home() / ".cache" / "codex-runtimes"
        bundled = list(runtime_root.glob("*/dependencies/native/git/cmd/git.exe"))
        if not bundled:
            self.skipTest("Codex bundled Git is not present")
        git = str(bundled[0])

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            bare = root / "remote.git"
            clone = root / "clone"
            source.mkdir()
            release = {
                "schemaVersion": 1,
                "edition": "online",
                "version": "0.10.0",
                "update": {"remote": "origin", "branch": "main", "host": "github.com"},
            }
            (source / "ONLINE-RELEASE.json").write_text(json.dumps(release), encoding="utf-8")
            subprocess.run([git, "-C", str(source), "init", "-b", "main"], check=True, capture_output=True)
            subprocess.run([git, "-C", str(source), "config", "user.name", "Codex Tools Test"], check=True)
            subprocess.run([git, "-C", str(source), "config", "user.email", "codex-tools-test@local.invalid"], check=True)
            subprocess.run([git, "-C", str(source), "add", "ONLINE-RELEASE.json"], check=True)
            subprocess.run([git, "-C", str(source), "commit", "-m", "test: seed online release"], check=True, capture_output=True)
            subprocess.run([git, "init", "--bare", str(bare)], check=True, capture_output=True)
            subprocess.run([git, "-C", str(source), "remote", "add", "origin", str(bare)], check=True)
            subprocess.run([git, "-C", str(source), "push", "origin", "main"], check=True, capture_output=True)
            subprocess.run([git, "clone", "--branch", "main", str(bare), str(clone)], check=True, capture_output=True)

            environment = os.environ.copy()
            environment["PATH"] = os.pathsep.join([
                str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32"),
                str(Path(os.environ.get("WINDIR", r"C:\Windows"))),
                str(WINDOWS_POWERSHELL.parent),
            ])
            environment.pop("CODEXTOOLS_GIT", None)
            result = subprocess.run(
                [
                    str(WINDOWS_POWERSHELL),
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(UPDATER),
                    "-Mode",
                    "Check",
                    "-RepositoryRoot",
                    str(clone),
                    "-AllowNonGitHubRemote",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            payload = json.loads(result.stdout.splitlines()[-1])
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["status"], "current")
            self.assertEqual(payload["source"], "GitHub")


if __name__ == "__main__":
    unittest.main()
