import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "apps" / "plugin-station"
sys.path.insert(0, str(APP_ROOT))

from core.workbuddy_chime import (  # noqa: E402
    HOOK_MARKER,
    ensure_workbuddy_hook,
    remove_workbuddy_hook,
    workbuddy_hook_status,
)


class WorkBuddyChimeTests(unittest.TestCase):
    def test_merge_preserves_existing_settings_and_hooks_with_backup(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder)
            settings = profile / ".workbuddy" / "settings.json"
            settings.parent.mkdir()
            original = {
                "sandbox": {"enabled": True},
                "hooks": {
                    "Stop": [{"hooks": [{"type": "command", "command": "echo existing"}]}],
                    "SessionStart": [{"hooks": [{"type": "command", "command": "echo start"}]}],
                },
            }
            settings.write_text(json.dumps(original), encoding="utf-8")
            executable = profile / "Agent Chime" / "CodexAnswerChime.exe"
            backups = profile / "backups"

            result = ensure_workbuddy_hook(executable, backups, user_profile=profile)

            self.assertTrue(result["changed"])
            self.assertEqual(json.loads(Path(result["backup"]).read_text(encoding="utf-8")), original)
            updated = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(updated["sandbox"], original["sandbox"])
            self.assertEqual(updated["hooks"]["SessionStart"], original["hooks"]["SessionStart"])
            commands = [
                hook["command"]
                for group in updated["hooks"]["Stop"]
                for hook in group.get("hooks", [])
                if hook.get("type") == "command"
            ]
            self.assertIn("echo existing", commands)
            owned = [command for command in commands if HOOK_MARKER in command]
            self.assertEqual(len(owned), 1)
            self.assertIn("/Agent Chime/CodexAnswerChime.exe", owned[0])

    def test_repeated_install_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder)
            (profile / ".workbuddy").mkdir()
            (profile / ".workbuddy" / "settings.json").write_text("{}", encoding="utf-8")
            executable = profile / "CodexAnswerChime.exe"
            backups = profile / "backups"

            first = ensure_workbuddy_hook(executable, backups, user_profile=profile)
            second = ensure_workbuddy_hook(executable, backups, user_profile=profile)

            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            self.assertEqual(len(list(backups.glob("*.json"))), 1)
            self.assertTrue(workbuddy_hook_status(executable, user_profile=profile)["enabled"])

    def test_remove_deletes_only_owned_hook(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder)
            settings = profile / ".workbuddy" / "settings.json"
            settings.parent.mkdir()
            settings.write_text(json.dumps({
                "enabledPlugins": {"example": True},
                "hooks": {"Stop": [{"hooks": [
                    {"type": "command", "command": "echo keep"},
                    {"type": "command", "command": f"tool.exe {HOOK_MARKER}"},
                ]}]},
            }), encoding="utf-8")

            result = remove_workbuddy_hook(profile / "backups", user_profile=profile)

            self.assertTrue(result["changed"])
            updated = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(updated["enabledPlugins"], {"example": True})
            self.assertEqual(updated["hooks"]["Stop"][0]["hooks"], [
                {"type": "command", "command": "echo keep"}
            ])

    def test_invalid_json_stops_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder)
            settings = profile / ".workbuddy" / "settings.json"
            settings.parent.mkdir()
            settings.write_text("{invalid", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "无法安全解析"):
                ensure_workbuddy_hook(
                    profile / "CodexAnswerChime.exe",
                    profile / "backups",
                    user_profile=profile,
                )

            self.assertEqual(settings.read_text(encoding="utf-8"), "{invalid")
            self.assertFalse((profile / "backups").exists())

    def test_codebuddy_directory_is_supported_as_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder)
            (profile / ".codebuddy").mkdir()
            executable = profile / "CodexAnswerChime.exe"

            ensure_workbuddy_hook(executable, profile / "backups", user_profile=profile)

            self.assertTrue((profile / ".codebuddy" / "settings.json").is_file())
            self.assertTrue(workbuddy_hook_status(executable, user_profile=profile)["enabled"])


if __name__ == "__main__":
    unittest.main()
