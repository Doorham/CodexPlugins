from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path


APP_TITLE = "Codex工具箱网络版"
APP_VERSION = "0.11.5"
MUTEX_NAME = r"Local\CompanyAIHelpers.CodexPluginStation"
ROOT = Path(__file__).resolve().parent
INSTANCE_VERSION_MARKER = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "CompanyAIHelpers" / "CodexTools" / "plugin-station-version.txt"
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9
WM_CLOSE = 0x0010
FLASHW_ALL = 0x00000003
FLASHW_TIMERNOFG = 0x0000000C
APP_WINDOW = None
CREATE_NO_WINDOW = 0x08000000


class FlashWindowInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("hwnd", ctypes.c_void_p),
        ("dwFlags", ctypes.c_uint),
        ("uCount", ctypes.c_uint),
        ("dwTimeout", ctypes.c_uint),
    ]


def close_handle(handle) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    kernel32.CloseHandle(handle)


def marker_matches_current_version() -> bool:
    try:
        return INSTANCE_VERSION_MARKER.read_text(encoding="utf-8").strip() == APP_VERSION
    except OSError:
        return False


def write_instance_version_marker() -> None:
    try:
        INSTANCE_VERSION_MARKER.parent.mkdir(parents=True, exist_ok=True)
        temporary = INSTANCE_VERSION_MARKER.with_suffix(".tmp")
        temporary.write_text(APP_VERSION, encoding="utf-8")
        temporary.replace(INSTANCE_VERSION_MARKER)
    except OSError:
        pass


def acquire_single_instance():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        user32.FindWindowW.restype = ctypes.c_void_p
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        user32.SetForegroundWindow.restype = ctypes.c_bool
        user32.FlashWindowEx.argtypes = [ctypes.POINTER(FlashWindowInfo)]
        user32.FlashWindowEx.restype = ctypes.c_bool
        user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        user32.PostMessageW.restype = ctypes.c_bool
        hwnd = user32.FindWindowW(None, APP_TITLE)
        if hwnd and not marker_matches_current_version():
            user32.PostMessageW(hwnd, WM_CLOSE, None, None)
            close_handle(handle)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                time.sleep(0.1)
                handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
                if not handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
                    write_instance_version_marker()
                    return handle
                close_handle(handle)
            return None
        if hwnd:
            user32.ShowWindow(hwnd, SW_RESTORE)
            if not user32.SetForegroundWindow(hwnd):
                flash = FlashWindowInfo(
                    ctypes.sizeof(FlashWindowInfo),
                    hwnd,
                    FLASHW_ALL | FLASHW_TIMERNOFG,
                    3,
                    0,
                )
                user32.FlashWindowEx(ctypes.byref(flash))
        close_handle(handle)
        return None
    write_instance_version_marker()
    return handle


def synchronize_codex_system_proxy() -> None:
    script = ROOT.parents[1] / "scripts" / "ensure-codex-system-proxy.py"
    if not script.is_file():
        return
    try:
        subprocess.run(
            [sys.executable, str(script)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        # The public card keeps the explicit repair action available.
        pass


def synchronize_proxy_bypass() -> None:
    script = ROOT.parents[1] / "scripts" / "ensure-proxy-bypass.py"
    if not script.is_file():
        return
    try:
        subprocess.run(
            [sys.executable, str(script)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def main() -> int:
    global APP_WINDOW

    mutex = acquire_single_instance()
    if mutex is None:
        return 0
    synchronize_proxy_bypass()
    synchronize_codex_system_proxy()

    # Importing pywebview/pythonnet is the expensive cold-start step. It is
    # deliberately delayed until after the fast single-instance check.
    import webview
    from core.control import ControlService

    class DesktopApi:
        def __init__(self) -> None:
            # Keep implementation objects private. pywebview recursively
            # inspects public API attributes; exposing the native Window here
            # makes it walk WinForms/CoreWebView2 objects off the UI thread.
            self._service = ControlService(ROOT)
            self._maximized = False

        def get_dashboard(self):
            return self._service.dashboard()

        def perform_action(self, plugin_id: str, action: str, payload=None):
            return self._service.perform_action(plugin_id, action, payload or {}, origin="ui")

        def choose_sound_file(self):
            paths = APP_WINDOW.create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=False,
                file_types=("Audio files (*.wav;*.mp3;*.wma)", "All files (*.*)"),
            )
            if not paths:
                return {"ok": False, "cancelled": True, "message": "未选择声音文件"}
            return self._service.perform_action(
                "codex-answer-chime",
                "set_sound",
                {"path": paths[0]},
                origin="ui",
            )

        def window_action(self, action: str):
            if action == "minimize":
                APP_WINDOW.minimize()
            elif action == "maximize":
                if self._maximized:
                    APP_WINDOW.restore()
                else:
                    APP_WINDOW.maximize()
                self._maximized = not self._maximized
            elif action == "hide":
                # Keep the warm WebView process alive. Reopening the launcher
                # finds this instance and raises it almost instantly.
                APP_WINDOW.hide()
            elif action == "quit":
                APP_WINDOW.destroy()
            return {"ok": True}

        def get_agent_manifest(self):
            return self._service.agent_manifest()

        def open_private_plugins_folder(self):
            return self._service.open_private_plugins_folder()

        def update_toolbox(self):
            return self._service.update_from_origin()

        def restart_after_update(self):
            result = self._service.schedule_toolbox_restart()
            if result.get("ok"):
                APP_WINDOW.destroy()
            return result

    api = DesktopApi()
    APP_WINDOW = webview.create_window(
        APP_TITLE,
        (ROOT / "web" / "index.html").as_uri(),
        js_api=api,
        width=1120,
        height=720,
        min_size=(860, 560),
        frameless=True,
        easy_drag=False,
        shadow=True,
        background_color="#0b0d12",
    )
    try:
        webview.start(gui="edgechromium", debug=False, private_mode=False)
    finally:
        close_handle(mutex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
