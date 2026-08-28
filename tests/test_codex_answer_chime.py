import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "helpers" / "codex-answer-chime" / "src" / "Program.cs"
MANIFEST_PATH = ROOT / "apps" / "plugin-station" / "plugins" / "codex-answer-chime" / "plugin.json"


class CodexAnswerChimeTests(unittest.TestCase):
    def test_manifest_records_completion_event_fix(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(manifest["moduleVersion"], "1.0.3")
        self.assertEqual(manifest["developers"], ["Doorham", "Althy"])

    def test_listener_uses_one_task_complete_signal(self) -> None:
        source = SOURCE_PATH.read_text(encoding="utf-8")
        self.assertIn('EqualsText(payload, "type", "task_complete")', source)
        self.assertIn('"task_complete:" + turnId', source)
        self.assertNotIn('EqualsText(payload, "type", "agent_message")', source)
        self.assertNotIn("GetForegroundWindow", source)

    def test_built_helper_event_schema_self_test(self) -> None:
        helper = ROOT / "artifacts" / "helpers" / "CodexAnswerChime.exe"
        if not helper.is_file():
            self.skipTest("Run scripts/build-helpers.ps1 before the binary self-test")
        completed = subprocess.run([str(helper), "--test-event-schema"], check=False, timeout=10)
        self.assertEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
