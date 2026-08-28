from __future__ import annotations

import ctypes
import json
import os
import sys
import winreg
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "apps" / "plugin-station"
sys.path.insert(0, str(APP_ROOT))

from core.clash_verge_bypass import required_bypass_entries, sync_clash_verge_bypass  # noqa: E402


INTERNET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


def _custom_domains(record_folder: Path) -> list[str]:
    try:
        raw = json.loads((record_folder / "custom-domains.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    domains = [str(item.get("domain", "")).strip().lower() for item in raw.get("items", []) if isinstance(item, dict)]
    domains.extend(str(item).strip().lower() for item in raw.get("domains", []))
    return [item for item in domains if item]


def _refresh_wininet() -> None:
    wininet = ctypes.windll.wininet
    wininet.InternetSetOptionW(None, 39, None, 0)
    wininet.InternetSetOptionW(None, 37, None, 0)


def main() -> int:
    manifest = APP_ROOT / "plugins" / "proxy-bypass" / "plugin.json"
    if not manifest.is_file():
        print(json.dumps({"ok": False, "message": "直连白名单插件清单不存在"}, ensure_ascii=True))
        return 0
    plugin = json.loads(manifest.read_text(encoding="utf-8"))
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    record_folder = local_app_data / "CompanyAIHelpers" / "ProxyOverrideBypass"
    required = required_bypass_entries([*plugin.get("domains", []), *_custom_domains(record_folder)])

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        INTERNET_SETTINGS,
        0,
        winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
    ) as key:
        try:
            override = str(winreg.QueryValueEx(key, "ProxyOverride")[0] or "")
        except FileNotFoundError:
            override = ""
        current = [item.strip() for item in override.split(";") if item.strip()]
        seen = {item.casefold() for item in current}
        missing = [item for item in required if item.casefold() not in seen]
        if missing:
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, ";".join([*current, *missing]))

    clash = sync_clash_verge_bypass(
        [*current, *missing],
        backup_root=record_folder / "Backups",
    )
    if missing:
        _refresh_wininet()
    print(json.dumps({
        "ok": True,
        "registryAdded": len(missing),
        "clashVergeDetected": clash["available"],
        "clashVergeChanged": clash["changed"],
        "configBackup": clash.get("backup"),
        "message": "Windows 与 Clash Verge 直连白名单已同步",
    }, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
