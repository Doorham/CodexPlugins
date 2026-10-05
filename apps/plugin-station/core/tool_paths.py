"""Workspace-owned runtime storage, independent of the launching application."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_DATA_ROOT = REPO_ROOT / ".runtime" / "CompanyAIHelpers"
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
    return [path for path in candidates if path.is_dir()]
