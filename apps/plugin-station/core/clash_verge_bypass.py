from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Iterable


DEFAULT_WINDOWS_BYPASS = (
    "localhost",
    "127.*",
    "192.168.*",
    "10.*",
    "172.16.*",
    "172.17.*",
    "172.18.*",
    "172.19.*",
    "172.20.*",
    "172.21.*",
    "172.22.*",
    "172.23.*",
    "172.24.*",
    "172.25.*",
    "172.26.*",
    "172.27.*",
    "172.28.*",
    "172.29.*",
    "172.30.*",
    "172.31.*",
    "<local>",
)


def clash_verge_config_path() -> Path:
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return appdata / "io.github.clash-verge-rev.clash-verge-rev" / "verge.yaml"


def split_bypass(value: str | None) -> list[str]:
    return [item.strip() for item in re.split(r"[,;\r\n]+", value or "") if item.strip()]


def required_bypass_entries(domains: Iterable[str]) -> list[str]:
    entries: list[str] = []
    for value in domains:
        domain = str(value).strip().lower().removeprefix("*.")
        if domain:
            entries.extend((domain, f"*.{domain}"))
    return _deduplicate(entries)


def _deduplicate(entries: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in entries:
        item = str(value).strip()
        folded = item.casefold()
        if item and folded not in seen:
            seen.add(folded)
            result.append(item)
    return result


def _top_level_scalar(text: str, key: str) -> tuple[str, re.Pattern[str]]:
    pattern = re.compile(rf"(?m)^{re.escape(key)}:\s*([^\r\n]*?)\s*$")
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError(f"Clash Verge 配置中的 {key} 不是唯一顶层字段")
    return matches[0].group(1), pattern


def _decode_yaml_scalar(raw: str) -> str | None:
    value = raw.strip()
    if value.lower() in {"", "null", "~"}:
        return None
    if value.startswith('"') and value.endswith('"'):
        decoded = json.loads(value)
        return str(decoded)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def clash_bypass_status(required: Iterable[str], *, config: Path | None = None) -> dict[str, object]:
    path = config or clash_verge_config_path()
    if not path.is_file():
        return {"available": False, "path": str(path), "installed": 0, "required": 0, "complete": False}
    try:
        text = path.read_text(encoding="utf-8")
        raw, _ = _top_level_scalar(text, "system_proxy_bypass")
        use_default_raw, _ = _top_level_scalar(text, "use_default_bypass")
        entries = split_bypass(_decode_yaml_scalar(raw))
        if use_default_raw.strip().lower() == "true":
            entries = [*DEFAULT_WINDOWS_BYPASS, *entries]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "available": True,
            "path": str(path),
            "installed": 0,
            "required": 0,
            "complete": False,
            "error": str(exc),
        }
    requested = _deduplicate(required)
    current = {item.casefold() for item in entries}
    installed = sum(1 for item in requested if item.casefold() in current)
    return {
        "available": True,
        "path": str(path),
        "installed": installed,
        "required": len(requested),
        "complete": installed == len(requested),
    }


def sync_clash_verge_bypass(
    required: Iterable[str],
    *,
    config: Path | None = None,
    backup_root: Path | None = None,
    remove: Iterable[str] = (),
) -> dict[str, object]:
    path = config or clash_verge_config_path()
    if not path.is_file():
        return {"available": False, "changed": False, "backup": None, "path": str(path)}

    original = path.read_text(encoding="utf-8")
    raw, bypass_pattern = _top_level_scalar(original, "system_proxy_bypass")
    use_default_raw, default_pattern = _top_level_scalar(original, "use_default_bypass")
    current = split_bypass(_decode_yaml_scalar(raw))
    if use_default_raw.strip().lower() == "true":
        current = [*DEFAULT_WINDOWS_BYPASS, *current]

    removed = {str(item).strip().casefold() for item in remove if str(item).strip()}
    current = [item for item in current if item.casefold() not in removed]
    merged = _deduplicate([*DEFAULT_WINDOWS_BYPASS, *current, *required])
    encoded = json.dumps(";".join(merged), ensure_ascii=False)
    updated = default_pattern.sub(lambda _: "use_default_bypass: false", original, count=1)
    updated = bypass_pattern.sub(lambda _: f"system_proxy_bypass: {encoded}", updated, count=1)
    if updated == original:
        return {"available": True, "changed": False, "backup": None, "path": str(path), "entries": len(merged)}

    destination_root = backup_root or path.parent / "CodexToolsBackups"
    destination_root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = destination_root / f"clash-verge-pre-bypass-{stamp}.yaml"
    counter = 1
    while backup.exists():
        backup = destination_root / f"clash-verge-pre-bypass-{stamp}-{counter}.yaml"
        counter += 1
    shutil.copy2(path, backup)

    temporary = path.with_name(f"{path.name}.codextools-updating")
    temporary.write_text(updated, encoding="utf-8", newline="\n")
    temporary.replace(path)
    return {
        "available": True,
        "changed": True,
        "backup": str(backup),
        "path": str(path),
        "entries": len(merged),
    }
