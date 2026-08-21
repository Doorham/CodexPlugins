from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import tomllib
import winreg
from pathlib import Path
from typing import Any, Callable


CREATE_NO_WINDOW = 0x08000000
INTERNET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
FEATURE_NAME = "respect_system_proxy"


def codex_config_path() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    return Path(codex_home).expanduser() / "config.toml" if codex_home else Path.home() / ".codex" / "config.toml"


def config_status(config: Path | None = None) -> dict[str, Any]:
    path = config or codex_config_path()
    try:
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        parsed = {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return {
            "path": str(path),
            "configured": False,
            "conflict": True,
            "message": f"Codex 配置无法读取：{exc}",
        }
    features = parsed.get("features", {})
    if not isinstance(features, dict):
        return {
            "path": str(path),
            "configured": False,
            "conflict": True,
            "message": "Codex 的 features 配置格式异常，未修改",
        }
    value = features.get(FEATURE_NAME)
    if value is not None and not isinstance(value, bool):
        return {
            "path": str(path),
            "configured": False,
            "conflict": True,
            "message": "respect_system_proxy 不是布尔值，未修改",
        }
    return {
        "path": str(path),
        "configured": value is True,
        "conflict": False,
        "value": value,
        "message": "Codex 已遵循 Windows 系统代理" if value is True else "Codex 尚未遵循 Windows 系统代理",
    }


def _updated_config(original: str) -> str:
    parsed = tomllib.loads(original) if original.strip() else {}
    features = parsed.get("features", {})
    if not isinstance(features, dict):
        raise ValueError("Codex 的 features 配置格式异常，已保持原文件不变")
    current = features.get(FEATURE_NAME)
    if current is not None and not isinstance(current, bool):
        raise ValueError("respect_system_proxy 不是布尔值，已保持原文件不变")
    if current is True:
        return original

    newline = "\r\n" if "\r\n" in original else "\n"
    section_pattern = re.compile(r"(?m)^\s*\[features\]\s*(?:#.*)?$")
    section_matches = list(section_pattern.finditer(original))
    if len(section_matches) > 1:
        raise ValueError("检测到重复的 [features]，已保持原文件不变")

    dotted_pattern = re.compile(
        r"(?m)^(\s*features\.respect_system_proxy\s*=\s*)(true|false)(\s*(?:#.*)?)$"
    )
    first_table = re.search(r"(?m)^\s*\[[^\]]+\]\s*(?:#.*)?$", original)
    top_level_end = first_table.start() if first_table else len(original)
    top_level = original[:top_level_end]
    dotted_matches = list(dotted_pattern.finditer(top_level))
    if len(dotted_matches) > 1:
        raise ValueError("检测到重复的 features.respect_system_proxy，已保持原文件不变")
    if dotted_matches:
        updated_top_level = dotted_pattern.sub(r"\g<1>true\g<3>", top_level, count=1)
        updated = updated_top_level + original[top_level_end:]
        tomllib.loads(updated)
        return updated

    if section_matches:
        section_start = section_matches[0].end()
        next_section = re.search(r"(?m)^\s*\[[^\]]+\]\s*(?:#.*)?$", original[section_start:])
        section_end = section_start + next_section.start() if next_section else len(original)
        body = original[section_start:section_end]
        key_pattern = re.compile(
            r"(?m)^(\s*respect_system_proxy\s*=\s*)(true|false)(\s*(?:#.*)?)$"
        )
        key_matches = list(key_pattern.finditer(body))
        if len(key_matches) > 1:
            raise ValueError("检测到重复的 respect_system_proxy，已保持原文件不变")
        if key_matches:
            updated_body = key_pattern.sub(r"\g<1>true\g<3>", body, count=1)
        else:
            prefix = "" if body.startswith(("\n", "\r")) else newline
            updated_body = f"{prefix}{newline}{FEATURE_NAME} = true{body}" if body.strip() else f"{newline}{FEATURE_NAME} = true{newline}"
        updated = original[:section_start] + updated_body + original[section_end:]
        tomllib.loads(updated)
        return updated

    suffix = "" if not original or original.endswith(("\n", "\r")) else newline
    separator = newline if original.strip() else ""
    updated = f"{original}{suffix}{separator}[features]{newline}{FEATURE_NAME} = true{newline}"
    tomllib.loads(updated)
    return updated


def ensure_system_proxy_feature(
    *,
    config: Path | None = None,
    backup_root: Path | None = None,
) -> dict[str, Any]:
    path = config or codex_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        original = ""
    except OSError as exc:
        raise ValueError(f"Codex config.toml 无法读取：{exc}") from exc
    try:
        updated = _updated_config(original)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Codex config.toml 不是有效 TOML：{exc}") from exc
    if updated == original:
        return {"changed": False, "backup": None, "message": "Codex 已遵循 Windows 系统代理"}
    verified_parsed = tomllib.loads(updated)
    if verified_parsed.get("features", {}).get(FEATURE_NAME) is not True:
        raise ValueError("无法安全写入 respect_system_proxy，已保持原文件不变")

    backup = None
    if path.exists():
        destination = backup_root or Path(os.environ.get("LOCALAPPDATA", path.parent)) / "CompanyAIHelpers" / "CodexSystemProxy" / "Backups"
        destination.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = destination / f"config-before-system-proxy-{stamp}.toml"
        counter = 1
        while backup.exists():
            backup = destination / f"config-before-system-proxy-{stamp}-{counter}.toml"
            counter += 1
        shutil.copy2(path, backup)

    temporary = path.with_name(f"{path.name}.codextools-updating")
    temporary.write_text(updated, encoding="utf-8", newline="")
    temporary.replace(path)
    verified = config_status(path)
    if not verified["configured"]:
        raise RuntimeError("配置写入后未通过回读验证")
    return {
        "changed": True,
        "backup": str(backup) if backup else None,
        "message": "已让 Codex WebSocket 从第一次连接开始遵循 Windows 系统代理",
    }


def windows_system_proxy_status() -> dict[str, Any]:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS) as key:
            try:
                enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0]) == 1
            except (FileNotFoundError, OSError, TypeError, ValueError):
                enabled = False
            try:
                server = str(winreg.QueryValueEx(key, "ProxyServer")[0]).strip()
            except (FileNotFoundError, OSError):
                server = ""
    except OSError:
        enabled = False
        server = ""
    return {"enabled": enabled, "server": server, "message": "系统代理已开启" if enabled else "系统代理未开启"}


def find_codex_cli() -> Path | None:
    candidates: list[Path] = []
    explicit = os.environ.get("CODEX_CLI_PATH")
    if explicit:
        candidates.append(Path(explicit))
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    bundled_root = local_app_data / "OpenAI" / "Codex" / "bin"
    if bundled_root.is_dir():
        candidates.extend(sorted(bundled_root.glob("*/codex.exe"), key=lambda item: item.stat().st_mtime, reverse=True))
    located = shutil.which("codex.exe") or shutil.which("codex")
    if located:
        candidates.append(Path(located))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def diagnose_websocket(
    *,
    cli: Path | None = None,
    timeout: int = 35,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    executable = cli or find_codex_cli()
    if executable is None:
        return {"available": False, "ok": False, "message": "未找到 Codex 自带诊断程序"}
    try:
        result = runner(
            [str(executable), "doctor", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": True, "ok": False, "message": f"Codex WebSocket 诊断未完成：{exc}"}
    try:
        report = json.loads(result.stdout)
        check = report["checks"]["network.websocket_reachability"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return {"available": True, "ok": False, "message": f"Codex 诊断结果无法解析：{exc}"}
    details = check.get("details", {}) if isinstance(check, dict) else {}
    ok = check.get("status") == "ok"
    return {
        "available": True,
        "ok": ok,
        "status": check.get("status"),
        "summary": check.get("summary", ""),
        "handshake": details.get("handshake result"),
        "durationMs": check.get("durationMs"),
        "message": "WebSocket 已通过系统代理连接（HTTP 101）" if ok else "WebSocket 仍未连接成功",
    }
