"""Restore an approved prepared Run entry using the toolbox's Windows API."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import re
import sys
import winreg

ROOT = Path(__file__).resolve().parents[1]
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
APPROVED_PROGRAMS = (
    Path('UpdreamClipboardCleaner/UpdreamClipboardCleaner.exe'),
    Path('CodexAnswerChime/CodexAnswerChime.exe'),
    Path('ArctisNova5BatteryMonitor/ArctisNova5BatteryMonitor.exe'),
    Path('ArctisNova5BatteryMonitor/ArctisNova5StartupGate.exe'),
)


def desktop_local_appdata() -> Path:
    local = ctypes.create_unicode_buffer(32768)
    shell = ctypes.WinDLL('shell32')
    shell.SHGetFolderPathW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p]
    if shell.SHGetFolderPathW(None, 28, None, 0, local) != 0:
        raise ValueError('Desktop local folder unavailable')
    return Path(local.value)


def restore_value(subkey: str, name: str, original: str, desired: str) -> bool:
    rights = winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, rights) as key:
        try:
            current, kind = winreg.QueryValueEx(key, name)
            present = True
        except FileNotFoundError:
            present = False
            current, kind = None, None
        if present and current not in (original, desired):
            raise ValueError('Startup changed; no value overwritten')
        if present and current == desired and kind == winreg.REG_SZ:
            return False
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, desired)
        if winreg.QueryValueEx(key, name) != (desired, winreg.REG_SZ):
            raise RuntimeError('Startup readback mismatch')
        return True


def regular(path: Path) -> None:
    for item in (path, *path.parents):
        if item.exists() and (item.is_symlink() or getattr(item.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Redirected recovery path')


def restore_prepared(recovery_id: str, expected_session: int, restore_to: str, entry_index: int) -> bool:
    if not re.fullmatch('[a-f0-9]{32}', recovery_id) or expected_session < 1 or restore_to not in ('legacy', 'current'):
        raise ValueError('Invalid recovery identity/session')
    sys.path.insert(0, str(ROOT / 'apps/plugin-station'))
    from core.tool_paths import current_user_sid

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    session = ctypes.c_uint32()
    if not kernel.ProcessIdToSessionId(kernel.GetCurrentProcessId(), ctypes.byref(session)):
        raise ctypes.WinError(ctypes.get_last_error())
    length = ctypes.c_uint32()
    if kernel.GetCurrentPackageFullName(ctypes.byref(length), None) != 15700:
        raise ValueError('A normal desktop worker is required')
    folder = ROOT / '.runtime/runtime-recovery' / recovery_id
    state_path = folder / 'state.json'
    active = ROOT / '.runtime/runtime-upgrade/active.json'
    for path in (folder, state_path, active):
        regular(path)
    state = json.loads(state_path.read_text(encoding='utf-8-sig'))
    if state['recoveryId'] != recovery_id or state['status'] != 'prepared' or state['ownerSid'] != current_user_sid() or session.value != expected_session:
        raise ValueError('Recovery ownership/session/state mismatch')
    if hashlib.sha256(active.read_bytes()).hexdigest().upper() != state['originalActiveSha256']:
        raise ValueError('Original failure control changed')
    entries = state['runEntries']
    if not 1 <= len(entries) <= len(APPROVED_PROGRAMS) or not 0 <= entry_index < len(entries):
        raise ValueError('Unexpected Run entry count/index')
    if len({entry['name'].casefold() for entry in entries}) != len(entries):
        raise ValueError('Duplicate prepared Run names')
    entry = entries[entry_index]
    match = re.match(r'^\s*(?:"([^"]+)"|([^\s"]+))', entry['command'])
    original_target = (match.group(1) or match.group(2)) if match else ''
    legacy_root = desktop_local_appdata() / 'CompanyAIHelpers'
    relative = next((part for part in APPROVED_PROGRAMS if original_target.casefold() == str(legacy_root / part).casefold()), None)
    if not entry['name'] or relative is None:
        raise ValueError('Unapproved original Run value')
    legacy = legacy_root / relative
    current = ROOT / '.runtime/CompanyAIHelpers' / relative
    target = legacy if restore_to == 'legacy' else current
    regular(target)
    if not target.is_file():
        raise ValueError('Approved public program absent')
    if restore_to == 'current':
        artifact = ROOT / 'artifacts/helpers' / relative.name
        regular(artifact)
        if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(artifact.read_bytes()).digest():
            raise ValueError('Installed public program differs')
    desired = entry['command'].replace(original_target, str(target), 1)
    return restore_value(RUN_KEY, entry['name'], entry['command'], desired)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--recovery-id', required=True)
    p.add_argument('--session', required=True, type=int)
    p.add_argument('--restore-to', choices=('legacy', 'current'), required=True)
    p.add_argument('--entry-index', required=True, type=int)
    args = p.parse_args()
    try:
        changed = restore_prepared(args.recovery_id, args.session, args.restore_to, args.entry_index)
        result = {'ok': True, 'changed': changed}
    except Exception as error:
        result = {'ok': False, 'failureCategory': 'access_denied' if isinstance(error, PermissionError) else 'operation_failed'}
    print(json.dumps(result, separators=(',', ':')))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
