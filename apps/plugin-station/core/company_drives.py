from __future__ import annotations

from .config_transaction import config_lock, replace_config

import ctypes
import os
import re
import shutil
import subprocess
import time
import tomllib
import uuid
import winreg
from ctypes import wintypes
from pathlib import Path
from typing import Any


FULL_ACCESS_PROFILE = ":danger-full-access"
LEGACY_PROFILE_NAME = "codextools-network-drives"
LEGACY_BLOCK_BEGIN = "# >>> CodexTools codex-network-drives >>>"
LEGACY_BLOCK_END = "# <<< CodexTools codex-network-drives <<<"
CONNECT_UPDATE_PROFILE = 0x00000001
NO_ERROR = 0
ERROR_NOT_CONNECTED = 2250


class NETRESOURCEW(ctypes.Structure):
    _fields_ = [
        ("dwScope", wintypes.DWORD),
        ("dwType", wintypes.DWORD),
        ("dwDisplayType", wintypes.DWORD),
        ("dwUsage", wintypes.DWORD),
        ("lpLocalName", wintypes.LPWSTR),
        ("lpRemoteName", wintypes.LPWSTR),
        ("lpComment", wintypes.LPWSTR),
        ("lpProvider", wintypes.LPWSTR),
    ]


def codex_config_path() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    return Path(codex_home).expanduser() / "config.toml" if codex_home else Path.home() / ".codex" / "config.toml"


def expected_drives(plugin: dict[str, Any]) -> list[dict[str, str]]:
    if plugin.get("discoverMappedDrives") is True:
        # Generic functionality only uses the current user's existing mappings.
        discovered = []
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            try:
                remote = _wnet_remote(letter)
            except OSError:
                continue
            if remote:
                discovered.append({"letter": letter, "root": f"{letter}:\\", "remote": remote})
        return discovered
    drives = []
    for item in plugin.get("drives", []):
        letter = str(item.get("letter", "")).strip().upper().rstrip(":")
        remote = str(item.get("remote", "")).strip()
        if not re.fullmatch(r"[WXYZ]", letter) or not re.fullmatch(r'\\\\[a-zA-Z0-9.-]+\\[^\\/:*?"<>|\r\n]+', remote):
            raise ValueError("网络盘清单只允许 W、X、Y、Z 和 UNC 路径")
        drive = {"letter": letter, "root": f"{letter}:\\", "remote": remote}
        if "lanRemote" in item:
            lan = item["lanRemote"]
            if (not isinstance(lan, str) or not re.fullmatch(r'\\\\[a-zA-Z0-9.-]+\\[^\\/:*?"<>|\r\n]+', lan)
                    or lan.rsplit("\\", 1)[-1].casefold() != remote.rsplit("\\", 1)[-1].casefold()):
                raise ValueError("局域网备用地址必须是同一共享的完整 UNC 路径")
            drive["lanRemote"] = lan
        drives.append(drive)
    if [item["letter"] for item in drives] != ["W", "X", "Y", "Z"]:
        raise ValueError("网络盘清单必须按 W、X、Y、Z 排列")
    return drives


def mapping_matches(drive: dict[str, Any], actual: str | None) -> bool:
    """Accept only explicitly configured endpoints, never share-name guesses."""
    return bool(actual and any(
        actual.rstrip("\\").casefold() == remote.rstrip("\\").casefold()
        for remote in (drive["remote"], drive.get("lanRemote")) if remote
    ))


def mapping_route(drive: dict[str, Any], actual: str | None) -> str | None:
    """Classify only explicitly configured addresses, never inferred network state."""
    if not actual:
        return None
    normalized = actual.rstrip("\\").casefold()
    if drive.get("lanRemote") and normalized == drive["lanRemote"].rstrip("\\").casefold():
        return "lan"
    if normalized == drive["remote"].rstrip("\\").casefold():
        return "tailscale"
    return None


def _wnet_remote(letter: str) -> str | None:
    size = wintypes.DWORD(2048)
    buffer = ctypes.create_unicode_buffer(size.value)
    result = ctypes.windll.mpr.WNetGetConnectionW(f"{letter}:", buffer, ctypes.byref(size))
    if result == NO_ERROR:
        return buffer.value
    if result == ERROR_NOT_CONNECTED:
        return None
    raise OSError(result, ctypes.FormatError(result))


def _map_drive(letter: str, remote: str) -> None:
    resource = NETRESOURCEW()
    resource.dwType = 1
    resource.lpLocalName = f"{letter}:"
    resource.lpRemoteName = remote
    result = ctypes.windll.mpr.WNetAddConnection2W(
        ctypes.byref(resource),
        None,
        None,
        CONNECT_UPDATE_PROFILE,
    )
    if result != NO_ERROR:
        raise OSError(result, ctypes.FormatError(result))


def linked_connections_enabled() -> bool:
    path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            return int(winreg.QueryValueEx(key, "EnableLinkedConnections")[0]) == 1
    except (FileNotFoundError, OSError, ValueError):
        return False


def _directory_readable(root: str) -> tuple[bool, str | None]:
    try:
        with os.scandir(root) as entries:
            next(entries, None)
        return True, None
    except OSError as exc:
        return False, str(exc)


def probe_drives(plugin: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for drive in expected_drives(plugin):
        try:
            actual = _wnet_remote(drive["letter"])
        except OSError as exc:
            actual = None
            mapping_error = str(exc)
        else:
            mapping_error = None
        visible = os.path.isdir(drive["root"])
        readable, read_error = _directory_readable(drive["root"]) if visible else (False, None)
        results.append({
            **drive,
            "actualRemote": actual,
            "mappingMatches": mapping_matches(drive, actual),
            "route": mapping_route(drive, actual),
            "visible": visible,
            "readable": readable,
            "writableHint": bool(visible and os.access(drive["root"], os.W_OK)),
            "error": mapping_error or read_error,
        })
    return results


def ensure_mappings(plugin: dict[str, Any]) -> list[dict[str, Any]]:
    if plugin.get("discoverMappedDrives") is True:
        return []  # No generic module may create a company's mappings.
    actions = []
    for drive in expected_drives(plugin):
        actual = _wnet_remote(drive["letter"])
        if actual and not mapping_matches(drive, actual):
            actions.append({
                "letter": drive["letter"],
                "ok": False,
                "changed": False,
                "message": f"{drive['letter']}: 已映射到其他位置，未覆盖",
            })
            continue
        if actual:
            actions.append({"letter": drive["letter"], "ok": True, "changed": False, "message": "映射已存在"})
            continue
        try:
            _map_drive(drive["letter"], drive["remote"])
            actions.append({"letter": drive["letter"], "ok": True, "changed": True, "message": "已恢复映射"})
        except OSError as exc:
            actions.append({
                "letter": drive["letter"],
                "ok": False,
                "changed": False,
                "message": f"映射失败：{exc}",
            })
    return actions


def write_test(plugin: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for drive in expected_drives(plugin):
        target = Path(drive["root"]) / f".codex-access-test-{uuid.uuid4().hex}.tmp"
        created = False
        read_back = False
        cleaned = False
        error = None
        try:
            target.write_text("codex-access-test", encoding="utf-8")
            created = target.is_file()
            read_back = target.read_text(encoding="utf-8") == "codex-access-test"
        except OSError as exc:
            error = str(exc)
        finally:
            try:
                target.unlink(missing_ok=True)
                cleaned = not target.exists()
            except OSError as exc:
                error = f"{error} | 清理失败：{exc}" if error else f"清理失败：{exc}"
        results.append({
            "letter": drive["letter"],
            "ok": created and read_back and cleaned,
            "created": created,
            "readBack": read_back,
            "cleaned": cleaned,
            "error": error,
        })
    return results


def _without_legacy_block(text: str) -> str:
    pattern = re.compile(
        rf"(?ms)^\s*{re.escape(LEGACY_BLOCK_BEGIN)}\r?\n.*?^\s*{re.escape(LEGACY_BLOCK_END)}\s*(?:\r?\n)?"
    )
    return pattern.sub("", text).rstrip()


def config_status(plugin: dict[str, Any], config: Path | None = None) -> dict[str, Any]:
    path = config or codex_config_path()
    try:
        text = path.read_text(encoding="utf-8")
        parsed = tomllib.loads(text)
    except FileNotFoundError:
        text = ""
        parsed = {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return {"path": str(path), "configured": False, "conflict": True, "message": f"Codex 配置无法读取：{exc}"}

    if parsed.get("sandbox_mode") is not None or "sandbox_workspace_write" in parsed:
        return {
            "path": str(path),
            "configured": False,
            "conflict": True,
            "message": "检测到旧版 sandbox_mode 配置，未混用权限配置",
        }
    legacy_present = LEGACY_PROFILE_NAME in parsed.get("permissions", {})
    configured = parsed.get("default_permissions") == FULL_ACCESS_PROFILE and not legacy_present
    return {
        "path": str(path),
        "configured": configured,
        "conflict": bool(legacy_present and LEGACY_BLOCK_BEGIN not in text),
        "broadAccess": parsed.get("default_permissions") == FULL_ACCESS_PROFILE,
        "message": "Codex 保持内置完全访问权限" if configured else "Codex 尚未保持内置完全访问权限",
    }


def ensure_full_access_default(plugin: dict[str, Any], *, config: Path | None = None, backup_root: Path | None = None) -> dict[str, Any]:
    path = (config or codex_config_path()).resolve()
    with config_lock(path):
        return _ensure_full_access_default(plugin, config=path, backup_root=backup_root)


def _ensure_full_access_default(
    plugin: dict[str, Any],
    *,
    config: Path | None = None,
    backup_root: Path | None = None,
) -> dict[str, Any]:
    # Codex defaults are independent of drive discovery and company activation.
    path = config or codex_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        original = path.read_text(encoding="utf-8")
        parsed = tomllib.loads(original)
    except FileNotFoundError:
        original = ""
        parsed = {}
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Codex config.toml 不是有效 TOML：{exc}") from exc

    if parsed.get("sandbox_mode") is not None or "sandbox_workspace_write" in parsed:
        raise ValueError("检测到旧版 sandbox_mode；权限配置不能与旧沙箱设置混用，已保持原文件不变")
    if LEGACY_PROFILE_NAME in parsed.get("permissions", {}) and LEGACY_BLOCK_BEGIN not in original:
        raise ValueError(f"已有同名旧权限配置 {LEGACY_PROFILE_NAME}，但不属于 CodexTools，已停止以避免覆盖")

    current_default = parsed.get("default_permissions")
    content = _without_legacy_block(original)
    default_line = f'default_permissions = "{FULL_ACCESS_PROFILE}"'
    if current_default:
        pattern = re.compile(r"(?m)^default_permissions\s*=\s*[^\r\n]+$")
        if not pattern.search(content):
            raise ValueError("无法安全定位现有 default_permissions，已保持原文件不变")
        content = pattern.sub(default_line, content, count=1)
    else:
        content = f"{default_line}\n\n{content.lstrip()}" if content else default_line

    updated = f"{content.rstrip()}\n"
    tomllib.loads(updated)
    if updated == original:
        return {"changed": False, "backup": None, "message": "Codex 已保持内置完全访问权限"}

    backup = None
    if path.exists():
        from .tool_paths import USER_DATA_ROOT
        destination_root = backup_root or USER_DATA_ROOT / "CodexNetworkDriveAccess" / "Backups"
        destination_root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = destination_root / f"config-pre-full-access-{stamp}.toml"
        counter = 1
        while backup.exists():
            backup = destination_root / f"config-pre-full-access-{stamp}-{counter}.toml"
            counter += 1
        shutil.copy2(path, backup)

    replace_config(path, original, updated)
    return {
        "changed": True,
        "backup": str(backup) if backup else None,
        "message": "已移除旧网络盘权限选项，并设为 Codex 内置完全访问权限",
    }


def enable_linked_connections(elevation_script: Path) -> dict[str, Any]:
    if linked_connections_enabled():
        return {"changed": False, "enabled": True, "restartRequired": False, "message": "跨权限映射已启用"}
    try:
        path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "EnableLinkedConnections", 0, winreg.REG_DWORD, 1)
    except PermissionError:
        if not elevation_script.is_file():
            raise FileNotFoundError(f"管理员修复脚本不存在：{elevation_script}")
        command = (
            "$p=Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -PassThru "
            "-ArgumentList @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',"
            f"'{str(elevation_script).replace("'", "''")}'); exit $p.ExitCode"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            creationflags=0x08000000,
        )
        if result.returncode != 0:
            raise RuntimeError("管理员确认被取消或跨权限映射修复失败")
    if not linked_connections_enabled():
        raise RuntimeError("EnableLinkedConnections 写入后未通过回读验证")
    return {
        "changed": True,
        "enabled": True,
        "restartRequired": True,
        "message": "已启用跨权限映射；重启 Windows 后完全生效",
    }
