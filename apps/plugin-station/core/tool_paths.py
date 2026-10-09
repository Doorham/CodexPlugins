"""Workspace-owned runtime storage, independent of the launching application."""
from __future__ import annotations

import os
import ctypes
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_DATA_ROOT = REPO_ROOT / ".runtime" / "CompanyAIHelpers"
LEGACY_COMPONENTS = frozenset(('CodexTools', 'CodexSystemProxy', 'CodexNetworkDriveAccess',
    'ProxyOverrideBypass', 'EnvironmentDetector', 'UpdreamClipboardCleaner', 'WeTypeAweSunBridge',
    'CodexAnswerChime', 'ArctisNova5BatteryMonitor', 'G435BatteryMonitor', 'UpdreamBridge', 'FFmpeg'))
def current_user_sid(process_handle=None) -> str:
    # Windows token identity, never a caller-supplied environment variable.
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    token = ctypes.c_void_p()
    advapi.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    advapi.GetTokenInformation.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess() if process_handle is None else process_handle, 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        length = ctypes.c_uint32()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(length))
        buffer = ctypes.create_string_buffer(length.value)
        if not advapi.GetTokenInformation(token, 1, buffer, length, ctypes.byref(length)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        text = ctypes.c_wchar_p()
        advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value
        finally:
            kernel.LocalFree.argtypes = [ctypes.c_void_p]
            kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    finally:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(token)


USER_SID = current_user_sid()
USER_DATA_ROOT = TOOL_DATA_ROOT / 'Users' / USER_SID
os.environ['CODEXTOOLS_USER_DATA_ROOT'] = str(USER_DATA_ROOT)


def ensure_user_data_root() -> Path:
    # Reject redirected ancestors before creating or opening any personal state.
    for parent in [USER_DATA_ROOT, *USER_DATA_ROOT.parents]:
        if parent.exists() and (parent.is_symlink() or getattr(parent.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('个人状态目录不能经过链接')
    USER_DATA_ROOT.mkdir(parents=True, exist_ok=True)
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    descriptor = ctypes.c_void_p()
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    sddl = f'D:P(A;OICI;FA;;;{USER_SID})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)'
    if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        present, defaulted, dacl = ctypes.c_int(), ctypes.c_int(), ctypes.c_void_p()
        security.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_int)]
        if not security.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
            raise ctypes.WinError(ctypes.get_last_error())
        security.SetNamedSecurityInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        code = security.SetNamedSecurityInfoW(str(USER_DATA_ROOT), 1, 4 | 0x80000000, None, None, dacl, None)
        if code: raise ctypes.WinError(code)
    finally:
        kernel = ctypes.WinDLL('kernel32')
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(descriptor)
    return USER_DATA_ROOT


# Child helpers use this specific variable; never repurpose Windows AppData.
os.environ["CODEXTOOLS_DATA_ROOT"] = str(TOOL_DATA_ROOT)


def expand_tool_path(value: str) -> Path:
    # Keep existing private manifests usable without editing private payloads.
    value = value.replace(r"%LOCALAPPDATA%\CompanyAIHelpers", str(TOOL_DATA_ROOT))
    value = value.replace("%CODEXTOOLS_DATA_ROOT%", str(TOOL_DATA_ROOT))
    value = value.replace("%CODEXTOOLS_USER_DATA_ROOT%", str(USER_DATA_ROOT))
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
