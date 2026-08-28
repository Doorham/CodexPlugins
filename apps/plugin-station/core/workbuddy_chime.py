from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


HOOK_MARKER = "--codextools-workbuddy-hook"
WORKBUDDY_SETTINGS_DIRS = (".workbuddy", ".codebuddy")


def find_workbuddy_settings(user_profile: Path | None = None) -> Path | None:
    profile = user_profile or Path(os.environ.get("USERPROFILE", Path.home()))
    candidates = [profile / name / "settings.json" for name in WORKBUDDY_SETTINGS_DIRS]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    for candidate in candidates:
        if candidate.parent.is_dir():
            return candidate
    return None


def _load_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("WorkBuddy settings.json 无法安全解析，未进行修改") from exc
    if not isinstance(payload, dict):
        raise ValueError("WorkBuddy settings.json 顶层必须是 JSON 对象，未进行修改")
    hooks = payload.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        raise ValueError("WorkBuddy hooks 配置格式异常，未进行修改")
    if isinstance(hooks, dict):
        stop = hooks.get("Stop")
        if stop is not None and not isinstance(stop, list):
            raise ValueError("WorkBuddy Stop hooks 配置格式异常，未进行修改")
    return payload


def _owned_hook(hook: Any) -> bool:
    return (
        isinstance(hook, dict)
        and hook.get("type") == "command"
        and HOOK_MARKER in str(hook.get("command", ""))
    )


def _owned_commands(payload: dict[str, Any]) -> list[dict[str, Any]]:
    hooks = payload.get("hooks")
    if not isinstance(hooks, dict):
        return []
    stop = hooks.get("Stop")
    if not isinstance(stop, list):
        return []
    owned: list[dict[str, Any]] = []
    for group in stop:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            continue
        owned.extend(hook for hook in group["hooks"] if _owned_hook(hook))
    return owned


def _remove_owned_hooks(payload: dict[str, Any]) -> bool:
    hooks = payload.get("hooks")
    if not isinstance(hooks, dict):
        return False
    stop = hooks.get("Stop")
    if not isinstance(stop, list):
        return False
    changed = False
    kept_groups: list[Any] = []
    for group in stop:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            kept_groups.append(group)
            continue
        kept_hooks = [hook for hook in group["hooks"] if not _owned_hook(hook)]
        if len(kept_hooks) != len(group["hooks"]):
            changed = True
        if kept_hooks:
            updated = dict(group)
            updated["hooks"] = kept_hooks
            kept_groups.append(updated)
    if not changed:
        return False
    if kept_groups:
        hooks["Stop"] = kept_groups
    else:
        hooks.pop("Stop", None)
    if not hooks:
        payload.pop("hooks", None)
    return True


def _hook_command(executable: Path) -> str:
    bash_path = str(executable.resolve()).replace("\\", "/")
    return f'"{bash_path}" {HOOK_MARKER}'


def _backup(path: Path, backup_root: Path) -> Path | None:
    if not path.is_file():
        return None
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = backup_root / f"workbuddy-settings-{stamp}.json"
    shutil.copy2(path, destination)
    return destination


def _write_settings(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.codextools-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def workbuddy_hook_status(executable: Path, *, user_profile: Path | None = None) -> dict[str, Any]:
    settings = find_workbuddy_settings(user_profile)
    if settings is None:
        return {"detected": False, "enabled": False, "valid": True, "settings": None, "error": None}
    try:
        payload = _load_settings(settings)
        owned = _owned_commands(payload)
    except ValueError as exc:
        return {
            "detected": True,
            "enabled": False,
            "valid": False,
            "settings": settings,
            "error": str(exc),
        }
    expected = _hook_command(executable)
    return {
        "detected": True,
        "enabled": any(str(item.get("command", "")) == expected for item in owned),
        "valid": True,
        "settings": settings,
        "error": None,
    }


def ensure_workbuddy_hook(
    executable: Path,
    backup_root: Path,
    *,
    user_profile: Path | None = None,
) -> dict[str, Any]:
    settings = find_workbuddy_settings(user_profile)
    if settings is None:
        raise FileNotFoundError("没有检测到 WorkBuddy，未创建配置目录")
    payload = _load_settings(settings)
    expected_hook = {
        "type": "command",
        "command": _hook_command(executable),
        "timeout": 10,
    }
    owned = _owned_commands(payload)
    if len(owned) == 1 and owned[0] == expected_hook:
        return {"changed": False, "backup": None, "settings": settings}

    _remove_owned_hooks(payload)
    hooks = payload.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("WorkBuddy hooks 配置格式异常，未进行修改")
    stop = hooks.setdefault("Stop", [])
    if not isinstance(stop, list):
        raise ValueError("WorkBuddy Stop hooks 配置格式异常，未进行修改")
    stop.append({"hooks": [expected_hook]})
    backup = _backup(settings, backup_root)
    _write_settings(settings, payload)
    return {"changed": True, "backup": backup, "settings": settings}


def remove_workbuddy_hook(
    backup_root: Path,
    *,
    user_profile: Path | None = None,
) -> dict[str, Any]:
    settings = find_workbuddy_settings(user_profile)
    if settings is None or not settings.is_file():
        return {"changed": False, "backup": None, "settings": settings}
    payload = _load_settings(settings)
    if not _remove_owned_hooks(payload):
        return {"changed": False, "backup": None, "settings": settings}
    backup = _backup(settings, backup_root)
    _write_settings(settings, payload)
    return {"changed": True, "backup": backup, "settings": settings}
