from __future__ import annotations

import base64
import ctypes
import csv
import json
import os
import re
import shutil
import subprocess
import threading
import time
import winreg
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .arctis_battery import is_hid_path_present, read_arctis_battery
from .clash_verge_bypass import (
    clash_bypass_status,
    required_bypass_entries,
    sync_clash_verge_bypass as sync_clash_config,
)
from .codex_system_proxy import (
    config_status as codex_proxy_config_status,
    diagnose_websocket,
    ensure_system_proxy_feature,
    windows_system_proxy_status,
)
from .workbuddy_chime import (
    ensure_workbuddy_hook,
    remove_workbuddy_hook,
    workbuddy_hook_status,
)
CREATE_NO_WINDOW = 0x08000000
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
INTERNET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
KEEP_ALIVE_WINDOW_SECONDS = 10 * 60
KEEP_ALIVE_MAX_ATTEMPTS = 3
KEEP_ALIVE_START_GRACE_SECONDS = 0.8


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def hidden_run(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )


def process_pids(image_name: str) -> list[int]:
    result = hidden_run(["tasklist.exe", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"])
    pids: list[int] = []
    for row in csv.reader(result.stdout.splitlines()):
        if len(row) >= 2 and row[0].lower() == image_name.lower():
            try:
                pids.append(int(row[1]))
            except ValueError:
                pass
    return pids


def read_run_value(name: str) -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return str(winreg.QueryValueEx(key, name)[0])
    except FileNotFoundError:
        return None


class ControlService:
    HANDLERS = {"process_app", "proxy_override", "codex_system_proxy"}
    HANDLER_ACTIONS = {
        "process_app": {"toggle_enabled", "start", "stop", "restart", "test_sound", "set_sound", "open_folder", "toggle_startup", "sync_workbuddy"},
        "proxy_override": {"refresh", "add_domain", "list_domains", "delete_domain"},
        "codex_system_proxy": {"refresh", "repair"},
    }

    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo_root = root.parents[1]
        self.private_root = expand_path(r"%LOCALAPPDATA%\CompanyAIHelpers\CodexTools\PrivatePlugins")
        self.private_errors: list[str] = []
        self._lock = threading.RLock()
        self._arctis_battery_cache: tuple[float, dict[str, Any]] | None = None
        self._hardware_presence_cache: dict[str, tuple[float, bool]] = {}
        self._keep_alive_attempts: dict[str, list[float]] = {}
        self._keep_alive_errors: dict[str, str] = {}
        self._codex_proxy_diagnostic: dict[str, Any] | None = None
        self._ensure_private_layer()
        self.plugins = self._load_plugins()

    def _ensure_private_layer(self) -> None:
        self.private_root.mkdir(parents=True, exist_ok=True)
        layer_record = self.private_root / "private-layer.json"
        if not layer_record.exists():
            layer_record.write_text(json.dumps({
                "schemaVersion": 1,
                "scope": "private",
                "sync": False,
                "upload": False,
                "note": "This folder is local to the current computer and is not part of the CodexTools Git repository.",
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _validate_plugin(self, data: dict[str, Any], manifest_path: Path, scope: str) -> None:
        handler = data.get("handler")
        if handler not in self.HANDLERS:
            raise ValueError(f"Unsupported handler in {manifest_path}")
        if not re.fullmatch(r"\d+\.\d+\.\d+", str(data.get("moduleVersion", ""))):
            raise ValueError(f"Invalid or missing moduleVersion in {manifest_path}")
        developers = data.get("developers")
        if not isinstance(developers, list) or not developers or not all(
            isinstance(name, str) and name.strip() for name in developers
        ):
            raise ValueError(f"Invalid or missing developers in {manifest_path}")
        data["developers"] = list(dict.fromkeys(name.strip() for name in developers))
        actions = data.get("actions")
        if not isinstance(actions, list) or not set(actions).issubset(self.HANDLER_ACTIONS[handler]):
            raise ValueError(f"Invalid actions for {handler} in {manifest_path}")
        ui_actions = {str(item.get("id", "")) for item in data.get("uiActions", []) if isinstance(item, dict)}
        agent_actions = set(data.get("agentAccess", {}).get("actions", []))
        if not ui_actions.issubset(set(actions)) or not agent_actions.issubset(set(actions)):
            raise ValueError(f"UI or Agent action exceeds the manifest action list in {manifest_path}")
        hardware_gate = data.get("hardwareGate")
        if hardware_gate is not None:
            if not isinstance(hardware_gate, dict) or hardware_gate.get("type") != "hid_path":
                raise ValueError(f"Unsupported hardwareGate in {manifest_path}")
            fragment = str(hardware_gate.get("pathContains", "")).lower()
            if not re.fullmatch(r"vid_[0-9a-f]{4}&pid_[0-9a-f]{4}(?:&mi_[0-9a-f]{2})?", fragment):
                raise ValueError(f"Invalid hardwareGate pathContains in {manifest_path}")
        if data.get("statusFile"):
            executable = expand_path(str(data.get("executable", ""))).resolve()
            status_file = expand_path(str(data["statusFile"])).resolve()
            if os.path.commonpath([str(status_file), str(executable.parent)]) != str(executable.parent):
                raise ValueError(f"Plugin statusFile must stay beside its executable in {manifest_path}")
        start_arguments = data.get("startArguments", [])
        if not isinstance(start_arguments, list) or not all(
            isinstance(value, str) and value and len(value) <= 256 and "\n" not in value and "\r" not in value
            for value in start_arguments
        ):
            raise ValueError(f"Invalid startArguments in {manifest_path}")
        if "keepAlive" in data:
            if not isinstance(data["keepAlive"], bool):
                raise ValueError(f"keepAlive must be a boolean in {manifest_path}")
            if data["keepAlive"] and (handler != "process_app" or not data.get("startup") or hardware_gate):
                raise ValueError(f"keepAlive requires a non-hardware process_app with startup in {manifest_path}")
        if data.get("bundle"):
            raise ValueError(f"External binary bundles are not supported in the online edition: {manifest_path}")
        if scope == "private":
            if not str(data.get("id", "")).startswith("private-"):
                raise ValueError(f"Private plugin id must start with private- in {manifest_path}")
            if handler != "process_app":
                raise ValueError(f"Private plugins currently support process_app only in {manifest_path}")
            if data.get("supportFiles") or data.get("installSource"):
                raise ValueError(f"Private plugins cannot install repository bundles or support files in {manifest_path}")
            executable = expand_path(str(data.get("executable", ""))).resolve()
            helpers_root = expand_path(r"%LOCALAPPDATA%\CompanyAIHelpers").resolve()
            if os.path.commonpath([str(executable), str(helpers_root)]) != str(helpers_root):
                raise ValueError(f"Private plugin executable must stay under {helpers_root}")
            if executable.name.lower() != str(data.get("processName", "")).lower():
                raise ValueError(f"Private plugin processName must match its executable filename in {manifest_path}")

    def _load_plugins(self) -> dict[str, dict[str, Any]]:
        plugins: dict[str, dict[str, Any]] = {}
        self.private_errors = []
        sources = ((self.root / "plugins", "shared", True), (self.private_root, "private", False))
        for source_root, scope, strict in sources:
            for manifest_path in sorted(source_root.glob("*/plugin.json")):
                try:
                    data = json.loads(manifest_path.read_text(encoding="utf-8"))
                    plugin_id = data["id"]
                    self._validate_plugin(data, manifest_path, scope)
                    if plugin_id in plugins:
                        raise ValueError(f"Duplicate plugin id: {plugin_id}")
                    data["_manifest"] = str(manifest_path)
                    data["_scope"] = scope
                    plugins[plugin_id] = data
                except Exception as exc:
                    if strict:
                        raise
                    self.private_errors.append(f"{manifest_path.name}: {exc}")
        return plugins

    def dashboard(self) -> dict[str, Any]:
        with self._lock:
            cards = []
            for plugin in self.plugins.values():
                if plugin.get("hardwareGate"):
                    available = self._hardware_available(plugin)
                    self._sync_hardware_lifecycle(plugin, available)
                    if not available:
                        continue
                elif plugin.get("keepAlive"):
                    self._sync_keep_alive_lifecycle(plugin)
                cards.append(self._plugin_status(plugin))
        return {
            "ok": True,
            "app": {
                "name": "Codex工具箱网络版",
                "version": "0.11.7",
                "developers": ["Doorham", "XY", "Althy"],
                "pluginCount": len(cards),
            },
            "plugins": cards,
            "privateLayer": {
                "root": str(self.private_root),
                "sync": False,
                "upload": False,
                "errors": self.private_errors,
            },
            "timestamp": int(time.time() * 1000),
        }

    def agent_manifest(self) -> dict[str, Any]:
        entries = []
        for plugin in self.plugins.values():
            if plugin.get("hardwareGate") and not self._hardware_available(plugin):
                continue
            access = plugin.get("agentAccess", {})
            if access.get("enabled"):
                entries.append({
                    "id": plugin["id"],
                    "name": plugin["name"],
                    "moduleVersion": plugin["moduleVersion"],
                    "developers": plugin["developers"],
                    "scope": plugin["_scope"],
                    "actions": access.get("actions", []),
                })
        return {"ok": True, "plugins": entries}

    def perform_action(
        self,
        plugin_id: str,
        action: str,
        payload: dict[str, Any],
        *,
        origin: str,
    ) -> dict[str, Any]:
        with self._lock:
            plugin = self.plugins.get(plugin_id)
            if not plugin:
                return {"ok": False, "message": "插件不存在"}
            if plugin.get("hardwareGate") and not self._hardware_available(plugin):
                message = plugin["hardwareGate"].get("notFoundMessage", "未检测到对应硬件")
                return {"ok": False, "message": message}
            allowed = set(plugin.get("actions", []))
            if origin == "agent":
                allowed &= set(plugin.get("agentAccess", {}).get("actions", []))
            if action not in allowed:
                return {"ok": False, "message": f"动作未授权：{action}"}
            try:
                if plugin["handler"] == "process_app":
                    result = self._process_action(plugin, action, payload)
                elif plugin["handler"] == "proxy_override":
                    result = self._proxy_action(plugin, action, payload)
                else:
                    result = self._codex_proxy_action(plugin, action)
                response = {"ok": True, "plugin": self._plugin_status(plugin)}
                if isinstance(result, dict):
                    response.update(result)
                    response.setdefault("message", "操作成功")
                else:
                    response["message"] = result
                return response
            except Exception as exc:
                return {"ok": False, "message": str(exc), "plugin": self._plugin_status(plugin)}

    def _plugin_status(self, plugin: dict[str, Any]) -> dict[str, Any]:
        if plugin["handler"] == "process_app":
            detail = self._process_status(plugin)
        elif plugin["handler"] == "proxy_override":
            detail = self._proxy_status(plugin)
        else:
            detail = self._codex_proxy_status(plugin)
        actions = [dict(item) for item in plugin.get("uiActions", [])]
        if detail.get("recoveryAvailable"):
            for action in actions:
                if action.get("id") == "toggle_enabled":
                    action["label"] = "恢复运行"
            if "toggle_startup" in plugin.get("actions", []) and not any(
                action.get("id") == "toggle_startup" for action in actions
            ):
                actions.append({"id": "toggle_startup", "label": "关闭自启", "kind": "secondary"})
        return {
            "id": plugin["id"],
            "name": plugin["name"],
            "moduleVersion": plugin["moduleVersion"],
            "developers": plugin["developers"],
            "scope": plugin["_scope"],
            "description": plugin["description"],
            "category": plugin["category"],
            "icon": plugin.get("icon", "◇"),
            "accent": plugin.get("accent", "#8b5cf6"),
            "mode": plugin.get("mode", "background"),
            "actions": actions,
            "agentEnabled": plugin.get("agentAccess", {}).get("enabled", False),
            **detail,
        }

    def open_private_plugins_folder(self) -> dict[str, Any]:
        self._ensure_private_layer()
        subprocess.Popen(["explorer.exe", str(self.private_root)])
        return {"ok": True, "message": "已打开私人插件目录", "path": str(self.private_root)}

    def update_from_origin(self) -> dict[str, Any]:
        script = self.repo_root / "scripts" / "update-from-origin.ps1"
        if not script.is_file():
            return {"ok": False, "updated": False, "message": f"更新程序不存在：{script}"}
        result = hidden_run([
            "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden", "-File", str(script), "-Mode", "Apply",
        ], timeout=300)
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        try:
            payload = json.loads(lines[-1]) if lines else {}
        except (ValueError, TypeError):
            payload = {}
        if not isinstance(payload, dict) or "ok" not in payload:
            message = result.stderr.strip() or result.stdout.strip() or f"更新程序退出码 {result.returncode}"
            return {"ok": False, "updated": False, "message": message}
        return payload

    def schedule_toolbox_restart(self) -> dict[str, Any]:
        launcher = self.repo_root / "start-plugin-station.vbs"
        if not launcher.is_file():
            return {"ok": False, "message": f"启动器不存在：{launcher}"}
        pid = os.getpid()
        quoted = str(launcher).replace("'", "''")
        script = (
            f"while (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ Start-Sleep -Milliseconds 200 }};"
            f"Start-Process -FilePath 'wscript.exe' -ArgumentList '\"{quoted}\"' -WindowStyle Hidden"
        )
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        subprocess.Popen([
            "powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand", encoded,
        ], creationflags=CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS, close_fds=True)
        return {"ok": True, "message": "正在重启工具箱"}

    def _process_status(self, plugin: dict[str, Any]) -> dict[str, Any]:
        exe = expand_path(plugin["executable"])
        pids = process_pids(plugin["processName"])
        startup_enabled = self._startup_enabled(plugin, exe)
        workbuddy = None
        if plugin["id"] == "codex-answer-chime":
            workbuddy = workbuddy_hook_status(exe)
        enabled = bool(pids or startup_enabled or (workbuddy and workbuddy.get("enabled")))
        recovery_available = bool(plugin.get("keepAlive") and startup_enabled and not pids)
        keep_alive_error = getattr(self, "_keep_alive_errors", {}).get(str(plugin["id"]))
        if pids and startup_enabled:
            status_text = "已开启"
        elif recovery_available and keep_alive_error:
            status_text = "自动恢复已暂停"
        elif enabled:
            status_text = "状态待同步"
        else:
            status_text = "已停用"
        sound_name = None
        if plugin["id"] == "codex-answer-chime":
            settings = exe.parent / "settings.json"
            try:
                relative = json.loads(settings.read_text(encoding="utf-8")).get("SoundFile")
                sound_name = Path(relative).name if relative else None
            except (OSError, ValueError, TypeError):
                pass
        details = [
            f"当前进程：{', '.join(str(pid) for pid in pids) if pids else '无'}",
            f"开机自启动：{'已开启' if startup_enabled else '已关闭'}",
        ]
        if keep_alive_error:
            details.append(f"常驻保护：{keep_alive_error}")
        elif plugin.get("keepAlive") and startup_enabled:
            details.append("常驻保护：已开启")
        if plugin["id"] == "codex-answer-chime":
            details.append(f"提示音：{sound_name}" if sound_name else "提示音：Windows 错误音（默认）")
            if not workbuddy or not workbuddy.get("detected"):
                details.append("WorkBuddy：未检测到，Codex 提示音仍可独立使用")
            elif not workbuddy.get("valid"):
                details.append(f"WorkBuddy：{workbuddy.get('error')}")
            elif workbuddy.get("enabled"):
                details.append("WorkBuddy：已接入同一任务完成提示音")
            else:
                details.append("WorkBuddy：待接入，可使用本卡片配置")
        metric = None
        if plugin["id"] == "arctis-nova-5-battery":
            reading = self._arctis_battery_reading() if pids else {"online": False}
            if reading.get("online"):
                metric = {
                    "value": f"{reading['percent']}%",
                    "label": "充电中" if reading.get("charging") else "耳机电量",
                    "state": "online",
                }
            else:
                metric = {"value": "离线", "label": "耳机未开机", "state": "offline"}
        elif plugin.get("statusFile"):
            metric, status_details = self._local_status_metric(plugin, bool(pids))
            details.extend(status_details)
        return {
            "installed": exe.exists(),
            "running": bool(pids),
            "pids": pids,
            "startupEnabled": startup_enabled,
            "enabled": enabled,
            "recoveryAvailable": recovery_available,
            "statusText": status_text,
            "detailLines": details,
            "metric": metric,
            "workbuddyDetected": bool(workbuddy and workbuddy.get("detected")),
            "workbuddyHookEnabled": bool(workbuddy and workbuddy.get("enabled")),
        }

    def _local_status_metric(self, plugin: dict[str, Any], monitor_running: bool) -> tuple[dict[str, str], list[str]]:
        if not monitor_running:
            return {"value": "已停用", "label": "本机监控未运行", "state": "offline"}, []
        status_file = expand_path(str(plugin["statusFile"]))
        try:
            payload = json.loads(status_file.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("status is not an object")
            age = time.time() - status_file.stat().st_mtime
        except (OSError, ValueError, TypeError):
            return {"value": "等待数据", "label": "监控正在初始化", "state": "offline"}, []
        if age > 180:
            return {"value": "数据过期", "label": "等待下次读取", "state": "offline"}, []
        if payload.get("online") is not True:
            return {"value": "离线", "label": "耳机未开机或未连接", "state": "offline"}, []
        voltage = payload.get("voltageMv")
        percent = payload.get("percent")
        estimated = payload.get("estimated") is True
        if isinstance(percent, int) and 0 <= percent <= 100:
            value = f"≈{percent}%" if estimated else f"{percent}%"
            label = f"{voltage} mV · 电压估算" if isinstance(voltage, int) else "估算电量"
        elif isinstance(voltage, int) and 2000 <= voltage <= 5000:
            value = f"{voltage} mV"
            label = "电池电压"
        else:
            return {"value": "读取异常", "label": "未获得有效电量", "state": "offline"}, []
        details = ["电量算法：电压曲线估算"] if estimated else []
        return {"value": value, "label": label, "state": "online"}, details

    def _arctis_battery_reading(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._arctis_battery_cache and now - self._arctis_battery_cache[0] < 8:
            return self._arctis_battery_cache[1]
        reading = read_arctis_battery()
        self._arctis_battery_cache = (now, reading)
        return reading

    def _hardware_available(self, plugin: dict[str, Any]) -> bool:
        gate = plugin.get("hardwareGate")
        if not gate:
            return True
        plugin_id = str(plugin["id"])
        now = time.monotonic()
        cached = self._hardware_presence_cache.get(plugin_id)
        if cached and now - cached[0] < 5:
            return cached[1]
        available = is_hid_path_present(str(gate["pathContains"]))
        self._hardware_presence_cache[plugin_id] = (now, available)
        return available

    def _sync_hardware_lifecycle(self, plugin: dict[str, Any], available: bool) -> None:
        exe = expand_path(plugin["executable"])
        pids = process_pids(plugin["processName"])
        if not available:
            if pids:
                hidden_run(["taskkill.exe", "/IM", plugin["processName"], "/F"])
            return
        if pids or not self._startup_enabled(plugin, exe):
            return
        self._ensure_installed(plugin, exe)
        subprocess.Popen(
            [str(exe)],
            cwd=str(exe.parent),
            creationflags=CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
        time.sleep(0.35)

    def _recent_keep_alive_attempts(self, plugin_id: str, now: float) -> list[float]:
        attempts = [
            value for value in self._keep_alive_attempts.get(plugin_id, [])
            if now - value < KEEP_ALIVE_WINDOW_SECONDS
        ]
        self._keep_alive_attempts[plugin_id] = attempts
        return attempts

    def _start_plugin_process(self, plugin: dict[str, Any], exe: Path) -> None:
        subprocess.Popen(
            [str(exe), *plugin.get("startArguments", [])],
            cwd=str(exe.parent),
            creationflags=CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )

    def _recover_keep_alive(self, plugin: dict[str, Any], *, user_initiated: bool = False) -> bool:
        plugin_id = str(plugin["id"])
        exe = expand_path(plugin["executable"])
        if process_pids(plugin["processName"]):
            self._keep_alive_errors.pop(plugin_id, None)
            return True
        if not self._startup_enabled(plugin, exe):
            self._keep_alive_errors.pop(plugin_id, None)
            return False

        now = time.monotonic()
        attempts = self._recent_keep_alive_attempts(plugin_id, now)
        if len(attempts) >= KEEP_ALIVE_MAX_ATTEMPTS and not user_initiated:
            self._keep_alive_errors[plugin_id] = "十分钟内恢复三次仍未稳定，已停止自动重试"
            return False
        attempts.append(now)
        if len(attempts) > KEEP_ALIVE_MAX_ATTEMPTS:
            del attempts[:-KEEP_ALIVE_MAX_ATTEMPTS]

        try:
            self._ensure_installed(plugin, exe)
            self._start_plugin_process(plugin, exe)
            time.sleep(KEEP_ALIVE_START_GRACE_SECONDS)
            if not process_pids(plugin["processName"]):
                raise RuntimeError("程序启动后未能保持运行")
        except Exception as exc:
            self._keep_alive_errors[plugin_id] = str(exc)
            if user_initiated:
                raise RuntimeError(f"恢复运行失败：{exc}") from exc
            return False

        self._keep_alive_errors.pop(plugin_id, None)
        return True

    def _sync_keep_alive_lifecycle(self, plugin: dict[str, Any]) -> None:
        if plugin.get("keepAlive"):
            self._recover_keep_alive(plugin)

    def _process_action(self, plugin: dict[str, Any], action: str, payload: dict[str, Any]) -> str:
        exe = expand_path(plugin["executable"])
        if action == "toggle_enabled":
            return self._toggle_enabled(plugin, exe)
        if action == "set_sound":
            return self._set_sound(exe, str(payload.get("path", "")))
        if action == "sync_workbuddy":
            if plugin["id"] != "codex-answer-chime":
                raise ValueError("只有任务完成提示音支持 WorkBuddy 接入")
            self._ensure_installed(plugin, exe)
            result = ensure_workbuddy_hook(exe, exe.parent / "Backups")
            if result["changed"]:
                return "WorkBuddy 已接入同一提示音；请重启 WorkBuddy 并检查 Hooks 后生效"
            return "WorkBuddy 已正确接入同一提示音，无需重复配置"
        if action in {"start", "restart", "test_sound"}:
            self._ensure_installed(plugin, exe)
        if action in {"stop", "restart"}:
            hidden_run(["taskkill.exe", "/IM", plugin["processName"], "/F"])
            time.sleep(0.35)
        if action in {"start", "restart"}:
            self._start_plugin_process(plugin, exe)
            time.sleep(0.6)
            return "已启动" if action == "start" else "已重启"
        if action == "stop":
            return "已停止"
        if action == "test_sound":
            subprocess.Popen(
                [str(exe), "--test-sound"],
                cwd=str(exe.parent),
                creationflags=CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                close_fds=True,
            )
            return "测试提示音已触发"
        if action == "open_folder":
            subprocess.Popen(["explorer.exe", str(exe.parent)])
            return "已打开安装目录"
        if action == "toggle_startup":
            return self._toggle_startup(plugin, exe)
        raise ValueError(f"不支持的动作：{action}")

    def _toggle_enabled(self, plugin: dict[str, Any], exe: Path) -> str:
        pids = process_pids(plugin["processName"])
        startup_enabled = self._startup_enabled(plugin, exe)
        workbuddy = workbuddy_hook_status(exe) if plugin["id"] == "codex-answer-chime" else None
        if plugin.get("keepAlive") and startup_enabled and not pids:
            if self._recover_keep_alive(plugin, user_initiated=True):
                return "已恢复运行；开机自启动保持开启"
        if pids or startup_enabled or (workbuddy and workbuddy.get("enabled")):
            if pids:
                hidden_run(["taskkill.exe", "/IM", plugin["processName"], "/F"])
                time.sleep(0.35)
            self._set_startup(plugin, exe, False)
            workbuddy_note = ""
            if workbuddy and workbuddy.get("detected"):
                try:
                    result = remove_workbuddy_hook(exe.parent / "Backups")
                    if result["changed"]:
                        workbuddy_note = "；WorkBuddy 完成事件已解除"
                except Exception as exc:
                    workbuddy_note = f"；但 WorkBuddy 接入未能解除：{exc}"
            return f"已停用；Codex 监听已停止，开机自启动已关闭{workbuddy_note}"

        self._ensure_installed(plugin, exe)
        self._set_startup(plugin, exe, True)
        try:
            subprocess.Popen(
                [str(exe)],
                cwd=str(exe.parent),
                creationflags=CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                close_fds=True,
            )
        except Exception:
            self._set_startup(plugin, exe, False)
            raise
        time.sleep(0.8)
        if not process_pids(plugin["processName"]):
            self._set_startup(plugin, exe, False)
            raise RuntimeError("程序未能保持运行，已回滚开机自启动")
        if workbuddy and workbuddy.get("detected"):
            try:
                result = ensure_workbuddy_hook(exe, exe.parent / "Backups")
                note = "；WorkBuddy 已接入，请重启 WorkBuddy 并检查 Hooks" if result["changed"] else "；WorkBuddy 已接入"
            except Exception as exc:
                note = f"；Codex 已开启，但 WorkBuddy 接入失败：{exc}"
        else:
            note = "；未检测到 WorkBuddy"
        return f"已开启；Codex 监听正在运行，并已加入开机自启动{note}"

    def _ensure_installed(self, plugin: dict[str, Any], exe: Path) -> None:
        if not exe.exists():
            install_source = plugin.get("installSource")
            if install_source:
                relative = Path(str(install_source))
                expected_root = (self.repo_root / "artifacts" / "helpers").resolve()
                source = (self.repo_root / relative).resolve()
                if relative.is_absolute() or os.path.commonpath([str(source), str(expected_root)]) != str(expected_root):
                    raise ValueError("插件安装源必须位于 artifacts/helpers")
                if source.name.lower() != exe.name.lower():
                    raise ValueError("插件安装源文件名与目标程序不一致")
                if not source.is_file():
                    raise FileNotFoundError(f"构建产物不存在，请先运行 scripts\\build-helpers.ps1：{source}")
                exe.parent.mkdir(parents=True, exist_ok=True)
                temporary = exe.with_suffix(".installing")
                shutil.copy2(source, temporary)
                temporary.replace(exe)
            else:
                raise FileNotFoundError(f"程序不存在：{exe}")
        for support in plugin.get("supportFiles", []):
            source = self.repo_root / support["source"]
            target = expand_path(support["target"])
            if not source.is_file():
                raise FileNotFoundError(f"插件支持文件不存在：{source}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def _startup_enabled(self, plugin: dict[str, Any], exe: Path) -> bool:
        startup = plugin.get("startup", {})
        enabled = False
        if startup.get("type") == "run":
            value = read_run_value(startup["name"])
            enabled = bool(value and str(exe).lower() in value.lower())
        elif startup.get("type") == "shortcut":
            enabled = expand_path(startup["path"]).exists()
        legacy_paths = startup.get("legacyPaths", [])
        legacy_runs = startup.get("legacyRunNames", [])
        return enabled or any(expand_path(path).exists() for path in legacy_paths) or any(
            bool(value := read_run_value(name)) and str(exe).lower() in value.lower()
            for name in legacy_runs
        )

    def _remove_legacy_startup(self, startup: dict[str, Any]) -> None:
        for path in startup.get("legacyPaths", []):
            try:
                expand_path(path).unlink()
            except FileNotFoundError:
                pass
        if startup.get("legacyRunNames"):
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                for name in startup["legacyRunNames"]:
                    try:
                        winreg.DeleteValue(key, name)
                    except FileNotFoundError:
                        pass

    def _set_startup(self, plugin: dict[str, Any], exe: Path, enabled: bool) -> None:
        startup = plugin.get("startup", {})
        if startup.get("type") == "run":
            name = startup["name"]
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                if enabled:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, f'"{exe}"')
                else:
                    try:
                        winreg.DeleteValue(key, name)
                    except FileNotFoundError:
                        pass
            self._remove_legacy_startup(startup)
            return
        if startup.get("type") == "shortcut":
            shortcut = expand_path(startup["path"])
            if not enabled:
                try:
                    shortcut.unlink()
                except FileNotFoundError:
                    pass
                self._remove_legacy_startup(startup)
                return
            shortcut.parent.mkdir(parents=True, exist_ok=True)
            target = expand_path(startup.get("target", str(exe)))
            if not target.is_file():
                raise FileNotFoundError(f"启动程序不存在：{target}")
            def ps_quote(value: str) -> str:
                return value.replace("'", "''")
            script = (
                "$w=New-Object -ComObject WScript.Shell;"
                f"$s=$w.CreateShortcut('{ps_quote(str(shortcut))}');"
                f"$s.TargetPath='{ps_quote(str(target))}';"
                f"$s.WorkingDirectory='{ps_quote(str(target.parent))}';"
                f"$s.Description='{ps_quote(plugin['name'])}';$s.Save()"
            )
            encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
            result = hidden_run([
                "powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                "-EncodedCommand", encoded,
            ])
            if result.returncode != 0 or not shortcut.exists():
                raise RuntimeError("创建 Startup 快捷方式失败")
            self._remove_legacy_startup(startup)
            return
        raise ValueError("插件没有可控制的启动项")

    def _set_sound(self, exe: Path, source_value: str) -> str:
        source = Path(source_value)
        if not source.is_file():
            raise FileNotFoundError("没有找到所选声音文件")
        extension = source.suffix.lower()
        if extension not in {".wav", ".mp3", ".wma"}:
            raise ValueError("支持 WAV、MP3 和 WMA 格式")
        sounds = exe.parent / "Sounds"
        sounds.mkdir(parents=True, exist_ok=True)
        destination = sounds / f"completion{extension}"
        for existing in sounds.glob("completion.*"):
            if existing.resolve() != destination.resolve():
                existing.unlink()
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        settings = {"SoundFile": str(Path("Sounds") / destination.name)}
        (exe.parent / "settings.json").write_text(
            json.dumps(settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return f"提示音已复制并设为：{destination.name}"

    def _toggle_startup(self, plugin: dict[str, Any], exe: Path) -> str:
        startup = plugin.get("startup", {})
        if startup.get("type") == "run":
            name = startup["name"]
            current = read_run_value(name)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                if current:
                    winreg.DeleteValue(key, name)
                    return "已关闭开机自启"
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, f'"{exe}"')
                return "已开启开机自启"
        if startup.get("type") == "shortcut":
            shortcut = expand_path(startup["path"])
            if shortcut.exists():
                shortcut.unlink()
                return "已关闭开机自启"
            shortcut.parent.mkdir(parents=True, exist_ok=True)
            def ps_quote(value: str) -> str:
                return value.replace("'", "''")
            script = (
                "$w=New-Object -ComObject WScript.Shell;"
                f"$s=$w.CreateShortcut('{ps_quote(str(shortcut))}');"
                f"$s.TargetPath='{ps_quote(str(exe))}';"
                f"$s.WorkingDirectory='{ps_quote(str(exe.parent))}';"
                f"$s.Description='{ps_quote(plugin['name'])}';$s.Save()"
            )
            encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
            result = hidden_run([
                "powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                "-EncodedCommand", encoded,
            ])
            if result.returncode != 0 or not shortcut.exists():
                raise RuntimeError("创建 Startup 快捷方式失败")
            return "已开启开机自启"
        raise ValueError("插件没有可控制的启动项")

    def _codex_proxy_status(self, plugin: dict[str, Any]) -> dict[str, Any]:
        config = codex_proxy_config_status()
        system_proxy = windows_system_proxy_status()
        diagnostic = self._codex_proxy_diagnostic
        configured = bool(config.get("configured"))
        conflict = bool(config.get("conflict"))
        system_proxy_enabled = bool(system_proxy.get("enabled"))
        detail_lines = [
            f"Codex：{config['message']}",
            f"Windows：{system_proxy['message']}",
        ]
        if diagnostic:
            if diagnostic.get("ok"):
                duration = diagnostic.get("durationMs")
                suffix = f" · {duration / 1000:.2f} 秒" if isinstance(duration, (int, float)) else ""
                detail_lines.append(f"WebSocket：HTTP 101 连接成功{suffix}")
            else:
                detail_lines.append(f"WebSocket：{diagnostic.get('message', '检测失败')}")
        else:
            detail_lines.append(
                "WebSocket：点击“检测连接”进行实时验证"
                if configured else "WebSocket：配置系统代理后才能检测"
            )
        verified = diagnostic is None or bool(diagnostic.get("ok"))
        if conflict:
            status_text = "配置异常"
            actions = [{"id": "repair", "label": "配置异常", "kind": "primary", "disabled": True}]
        elif not configured:
            status_text = "待配置"
            actions = [{"id": "repair", "label": "配置系统代理", "kind": "primary"}]
        else:
            actions = [
                {"id": "repair", "label": "已配置", "kind": "primary", "disabled": True},
                {"id": "refresh", "label": "检测连接", "kind": "secondary"},
            ]
            if not system_proxy_enabled:
                status_text = "已配置 · 系统代理未开启"
            elif diagnostic is None:
                status_text = "已配置"
            elif diagnostic.get("ok"):
                status_text = "连接正常"
            else:
                status_text = "连接检测失败"
        return {
            "installed": configured,
            "running": configured and system_proxy_enabled and verified,
            "pids": [],
            "startupEnabled": None,
            "enabled": configured,
            "statusText": status_text,
            "detailLines": detail_lines,
            "actions": actions,
        }

    def _codex_proxy_action(self, plugin: dict[str, Any], action: str) -> Any:
        if action == "repair":
            record_folder = expand_path(plugin["recordFolder"])
            result = ensure_system_proxy_feature(backup_root=record_folder / "Backups")
        elif action == "refresh":
            status = codex_proxy_config_status()
            if not status.get("configured"):
                self._codex_proxy_diagnostic = None
                raise RuntimeError("Codex 尚未遵循系统代理，请先点击“配置系统代理”")
            result = {"changed": False, "backup": None}
        else:
            raise ValueError(f"不支持的动作：{action}")

        self._codex_proxy_diagnostic = diagnose_websocket()
        if not self._codex_proxy_diagnostic.get("ok"):
            message = self._codex_proxy_diagnostic.get("message", "WebSocket 检测失败")
            if action == "repair":
                raise RuntimeError(f"系统代理功能已配置，但 {message}；重复配置不能修复代理线路")
            raise RuntimeError(message)
        return {
            "message": (
                "系统代理功能已配置，WebSocket 检测通过（HTTP 101）"
                if action == "repair"
                else "WebSocket 检测通过（HTTP 101）"
            ),
            "configBackup": result.get("backup"),
            "restartRequired": False,
            "diagnostic": self._codex_proxy_diagnostic,
        }

    def _proxy_status(self, plugin: dict[str, Any]) -> dict[str, Any]:
        required = []
        for domain in plugin["domains"]:
            required.extend([domain, f"*.{domain}"])
        override = str(self._read_internet_value("ProxyOverride", "") or "")
        try:
            proxy_enable = int(self._read_internet_value("ProxyEnable", 0) or 0)
        except (TypeError, ValueError):
            proxy_enable = 0
        proxy_server = str(self._read_internet_value("ProxyServer", "") or "").strip() or "未设置"
        current = {item.strip().lower() for item in override.split(";") if item.strip()}
        installed_count = sum(1 for item in required if item.lower() in current)
        custom_domains = self._load_custom_domain_records(plugin)
        clash = clash_bypass_status(self._proxy_required_entries(plugin, custom_domains))
        clash_complete = not clash["available"] or bool(clash["complete"])
        complete = installed_count == len(required) and clash_complete
        detail_lines = ["自定义白名单仅存本机 · 更新不会覆盖", "主站和 *.主站 会同时加入", f"系统代理保持：{proxy_server}"]
        if clash["available"]:
            detail_lines.append(f"Clash Verge 持久白名单：{clash['installed']}/{clash['required']}")
        return {
            "installed": complete,
            "running": proxy_enable == 1,
            "pids": [],
            "startupEnabled": None,
            "enabled": complete,
            "statusText": f"内置 {installed_count}/{len(required)} · 自定义 {len(custom_domains)}",
            "detailLines": detail_lines,
        }

    def _proxy_action(self, plugin: dict[str, Any], action: str, payload: dict[str, Any]) -> Any:
        if action == "refresh":
            self._ensure_proxy_override_entries(plugin)
            self._sync_clash_verge_bypass(plugin)
            self._refresh_wininet()
            return "Windows 与 Clash Verge 直连白名单已同步"
        if action == "list_domains":
            return {
                "message": "白名单已读取",
                "domains": self._proxy_domain_inventory(plugin),
            }
        if action == "add_domain":
            domain = self._normalize_domain(str(payload.get("domain", "")))
            entries = [domain, f"*.{domain}"]
            builtin = {item.lower() for item in plugin["domains"]}
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                INTERNET_SETTINGS,
                0,
                winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
            ) as key:
                override = str(self._query_value_or_default(key, "ProxyOverride", "") or "")
                current = [item.strip() for item in override.split(";") if item.strip()]
                seen = {item.lower() for item in current}
                covering_domain = self._covering_wildcard(domain, seen)
                if covering_domain:
                    self._sync_clash_verge_bypass(plugin)
                    return f"已被 {covering_domain} 的子域通配规则覆盖，无需重复添加"
                missing = [entry for entry in entries if entry.lower() not in seen]
                if domain in builtin:
                    for entry in missing:
                        current.append(entry)
                    if missing:
                        winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, ";".join(current))
                    self._sync_clash_verge_bypass(plugin)
                    self._refresh_wininet()
                    return "该主站属于内置白名单，已补齐缺失规则" if missing else "该主站已在内置白名单，无需重复添加"
                records = self._load_custom_domain_records(plugin)
                owned = records.get(domain, set())
                if not missing:
                    self._sync_clash_verge_bypass(plugin)
                    return "该主站已在白名单，无需重复添加"
                for entry in missing:
                    current.append(entry)
                    owned.add(entry.lower())
                winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, ";".join(current))
            records[domain] = owned
            self._save_custom_domain_records(plugin, records)
            self._sync_clash_verge_bypass(plugin)
            self._refresh_wininet()
            if len(missing) == 2:
                return f"添加成功：{domain} 和 *.{domain}"
            return f"已补齐缺失规则：{missing[0]}；已有规则未重复写入"
        if action == "delete_domain":
            domain = self._normalize_domain(str(payload.get("domain", "")))
            records = self._load_custom_domain_records(plugin)
            owned = records.get(domain)
            if not owned:
                return "该主站不是插件站添加的自定义规则，未执行删除"
            required = {
                entry.lower()
                for builtin_domain in plugin["domains"]
                for entry in (builtin_domain, f"*.{builtin_domain}")
            }
            removable = {entry for entry in owned if entry not in required}
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    INTERNET_SETTINGS,
                    0,
                    winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
                ) as key:
                    override = str(self._query_value_or_default(key, "ProxyOverride", "") or "")
                    current = [item.strip() for item in override.split(";") if item.strip()]
                    kept = [item for item in current if item.lower() not in removable]
                    if kept != current:
                        winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, ";".join(kept))
            except FileNotFoundError:
                pass
            records.pop(domain, None)
            self._save_custom_domain_records(plugin, records)
            self._sync_clash_verge_bypass(plugin, remove=removable)
            self._refresh_wininet()
            return f"已删除自定义主站：{domain}"
        if action == "open_folder":
            folder = expand_path(plugin["recordFolder"])
            subprocess.Popen(["explorer.exe", str(folder)])
            return "已打开备份目录"
        raise ValueError(f"不支持的动作：{action}")

    def _custom_domains_file(self, plugin: dict[str, Any]) -> Path:
        return expand_path(plugin["recordFolder"]) / "custom-domains.json"

    def _proxy_required_entries(
        self,
        plugin: dict[str, Any],
        records: dict[str, set[str]] | None = None,
    ) -> list[str]:
        custom = records if records is not None else self._load_custom_domain_records(plugin)
        return required_bypass_entries([*plugin["domains"], *custom])

    def _ensure_proxy_override_entries(self, plugin: dict[str, Any]) -> int:
        required = self._proxy_required_entries(plugin)
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            INTERNET_SETTINGS,
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            override = str(self._query_value_or_default(key, "ProxyOverride", "") or "")
            current = [item.strip() for item in override.split(";") if item.strip()]
            seen = {item.casefold() for item in current}
            missing = [item for item in required if item.casefold() not in seen]
            if missing:
                winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, ";".join([*current, *missing]))
        return len(missing)

    def _sync_clash_verge_bypass(
        self,
        plugin: dict[str, Any],
        *,
        remove: set[str] | None = None,
    ) -> dict[str, object]:
        registry = str(self._read_internet_value("ProxyOverride", "") or "")
        required = [*self._proxy_required_entries(plugin), *[item.strip() for item in registry.split(";") if item.strip()]]
        return sync_clash_config(
            required,
            backup_root=expand_path(plugin["recordFolder"]) / "Backups",
            remove=remove or (),
        )

    def _load_custom_domain_records(self, plugin: dict[str, Any]) -> dict[str, set[str]]:
        custom_file = self._custom_domains_file(plugin)
        try:
            raw = json.loads(custom_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        records: dict[str, set[str]] = {}
        for item in raw.get("items", []):
            if not isinstance(item, dict):
                continue
            domain = str(item.get("domain", "")).lower()
            entries = {str(entry).lower() for entry in item.get("entries", [])}
            if domain and entries:
                records[domain] = entries
        for domain_value in raw.get("domains", []):
            domain = str(domain_value).lower()
            if domain:
                records.setdefault(domain, {domain, f"*.{domain}"})
        return records

    def _save_custom_domain_records(self, plugin: dict[str, Any], records: dict[str, set[str]]) -> None:
        custom_file = self._custom_domains_file(plugin)
        custom_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 2,
            "items": [
                {"domain": domain, "entries": sorted(entries)}
                for domain, entries in sorted(records.items())
            ],
        }
        custom_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _proxy_domain_inventory(self, plugin: dict[str, Any]) -> list[dict[str, Any]]:
        override = str(self._read_internet_value("ProxyOverride", "") or "")
        current = {item.strip().lower() for item in override.split(";") if item.strip()}
        builtin = sorted({str(domain).lower() for domain in plugin["domains"]})
        custom = self._load_custom_domain_records(plugin)
        inventory = []
        for domain in sorted(set(custom) - set(builtin)):
            entries = {domain, f"*.{domain}"}
            inventory.append({
                "domain": domain,
                "source": "自定义",
                "deletable": True,
                "activeCount": len(entries & current),
            })
        for domain in builtin:
            entries = {domain, f"*.{domain}"}
            inventory.append({
                "domain": domain,
                "source": "内置",
                "deletable": False,
                "activeCount": len(entries & current),
            })
        return inventory

    @staticmethod
    def _query_value_or_default(key: Any, name: str, default: Any) -> Any:
        try:
            return winreg.QueryValueEx(key, name)[0]
        except FileNotFoundError:
            return default

    def _read_internet_value(self, name: str, default: Any) -> Any:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS) as key:
                return self._query_value_or_default(key, name, default)
        except FileNotFoundError:
            return default

    @staticmethod
    def _covering_wildcard(domain: str, current: set[str]) -> str | None:
        labels = domain.split(".")
        for index in range(1, len(labels) - 1):
            parent = ".".join(labels[index:])
            if f"*.{parent}" in current:
                return parent
        return None

    @staticmethod
    def _normalize_domain(value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("请输入主站域名，例如 example.com")
        parsed = urlparse(value if "://" in value else "//" + value)
        host = (parsed.hostname or "").strip(".").lower()
        if host.startswith("www."):
            host = host[4:]
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            raise ValueError("域名格式不正确")
        if len(host) > 253 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host):
            raise ValueError("域名格式不正确")
        if "." not in host:
            raise ValueError("请输入完整主站域名，例如 example.com")
        return host

    @staticmethod
    def _refresh_wininet() -> None:
        wininet = ctypes.WinDLL("wininet", use_last_error=True)
        changed = wininet.InternetSetOptionW(None, 39, None, 0)
        refreshed = wininet.InternetSetOptionW(None, 37, None, 0)
        if not (changed and refreshed):
            raise ctypes.WinError(ctypes.get_last_error())
