"""Hand an old installation to a desktop-context upgrader before opening data."""
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path


class UpgradeError(RuntimeError):
    pass


def request_runtime_upgrade(repo: Path, *, caller_pid: int | None = None) -> dict:
    folder = repo / '.runtime' / 'runtime-upgrade'
    for parent in (repo / '.runtime', folder):
        attributes = getattr(parent.lstat(), 'st_file_attributes', 0) if parent.exists() else 0
        if parent.is_symlink() or attributes & 0x400:
            raise UpgradeError('升级目录不是普通目录，请联系维护人员。')
    folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / 'active.json'
    lock_path = folder / 'dispatch.lock'
    try:
        lock = lock_path.open('x', encoding='utf-8')
    except FileExistsError as exc:
        raise UpgradeError('另一个升级入口正在运行，请稍后重新打开工具箱。') from exc
    try:
        if state_path.exists():
            if state_path.is_symlink() or getattr(state_path.lstat(), 'st_file_attributes', 0) & 0x400:
                raise UpgradeError('升级记录不是普通文件，请联系维护人员。')
            try:
                state = json.loads(state_path.read_text(encoding='utf-8-sig'))
            except (ValueError, OSError) as exc:
                raise UpgradeError('升级记录无法验证，请联系维护人员；不要删除旧数据。') from exc
            if state.get('state') in ('pending', 'running'):
                limit = 180 if state['state'] == 'pending' else 3600
                if time.time() - float(state.get('updatedAt', 0)) < limit:
                    return state
                raise UpgradeError('上次升级未正常完成，请联系维护人员；原数据和备份仍保留。')
            if state.get('state') == 'failed':
                raise UpgradeError('自动升级未完成，请联系维护人员；原数据和备份仍保留。')
        script = repo / 'scripts' / 'auto-migrate-runtime.ps1'
        if not script.is_file():
            raise UpgradeError('升级程序缺失，请联系维护人员。')
        request_id = uuid.uuid4().hex
        state = {'schemaVersion': 1, 'requestId': request_id, 'state': 'pending',
                 'callerPid': caller_pid or os.getpid(), 'updatedAt': time.time(),
                 'backupName': 'runtime-move-' + time.strftime('%Y%m%d-%H%M%S-') + str(time.time_ns())}
        temporary = folder / (request_id + '.tmp')
        temporary.write_text(json.dumps(state), encoding='utf-8')
        temporary.replace(state_path)
        environment = dict(os.environ)
        # Let Windows PowerShell locate its own built-in modules. Never change
        # the parent app environment or launch/stop Codex.
        environment.pop('PSModulePath', None)
        powershell = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        try:
            subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive',
                              '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
                              '-File', str(script), '-Dispatch', '-RequestId', request_id],
                             cwd=repo, env=environment, close_fds=True,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) |
                                           getattr(subprocess, 'DETACHED_PROCESS', 0))
        except OSError as exc:
            state.update(state='failed', updatedAt=time.time())
            temporary.write_text(json.dumps(state), encoding='utf-8')
            temporary.replace(state_path)
            raise UpgradeError('无法启动自动升级，请联系维护人员。') from exc
        return state
    finally:
        lock.close()
        lock_path.unlink()
