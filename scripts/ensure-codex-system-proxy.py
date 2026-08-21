from __future__ import annotations

import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "apps" / "plugin-station"
sys.path.insert(0, str(APP_ROOT))

from core.codex_system_proxy import config_status, ensure_system_proxy_feature  # noqa: E402


def main() -> int:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    backup_root = local_app_data / "CompanyAIHelpers" / "CodexSystemProxy" / "Backups"
    try:
        result = ensure_system_proxy_feature(backup_root=backup_root)
        status = config_status()
        payload = {
            "ok": status["configured"],
            "changed": result["changed"],
            "configBackup": result.get("backup"),
            "message": result["message"],
        }
    except (OSError, ValueError, RuntimeError) as exc:
        payload = {"ok": False, "changed": False, "configBackup": None, "message": str(exc)}
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
