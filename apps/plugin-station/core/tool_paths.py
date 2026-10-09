"""Workspace-owned runtime storage, independent of the launching application."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_DATA_ROOT = REPO_ROOT / ".runtime" / "CompanyAIHelpers"
LEGACY_COMPONENTS = frozenset(('CodexTools', 'CodexSystemProxy', 'CodexNetworkDriveAccess',
    'ProxyOverrideBypass', 'EnvironmentDetector', 'UpdreamClipboardCleaner', 'WeTypeAweSunBridge',
    'CodexAnswerChime', 'ArctisNova5BatteryMonitor', 'G435BatteryMonitor', 'UpdreamBridge', 'FFmpeg'))
# Child helpers use this specific variable; never repurpose Windows AppData.
os.environ["CODEXTOOLS_DATA_ROOT"] = str(TOOL_DATA_ROOT)


def expand_tool_path(value: str) -> Path:
    # Keep existing private manifests usable without editing private payloads.
    value = value.replace(r"%LOCALAPPDATA%\CompanyAIHelpers", str(TOOL_DATA_ROOT))
    value = value.replace("%CODEXTOOLS_DATA_ROOT%", str(TOOL_DATA_ROOT))
    return Path(os.path.expandvars(value)).expanduser()


def legacy_runtime_roots(local_appdata: Path | None = None) -> list[Path]:
    """Inventory only owned directory names; never read private file contents."""
    local = local_appdata or Path(os.environ.get("LOCALAPPDATA", ""))
    if not local.is_absolute():
        return []
    candidates = [local / "CompanyAIHelpers"]
    packages = local / "Packages"
    if packages.is_dir():
        candidates.extend(package / "LocalCache/Local/CompanyAIHelpers"
                          for package in packages.glob("OpenAI.Codex_*"))
    owned = {name.casefold() for name in LEGACY_COMPONENTS}
    result = []
    for path in candidates:
        if not path.exists():
            continue
        # Keep malformed owned roots visible to the migration validator. Extra
        # backup/trial/private tools remain at their old paths after migration.
        if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
            result.append(path)
        elif path.is_dir() and any(item.name.casefold() in owned for item in path.iterdir()):
            result.append(path)
    return result
