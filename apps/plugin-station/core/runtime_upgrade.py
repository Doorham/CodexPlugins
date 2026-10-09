"""Hand an old installation to a desktop-context upgrader before opening data."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path


class UpgradeError(RuntimeError):
    pass


class PendingUpgradeError(UpgradeError):
    """A stalled handoff may be resumed only after an explicit desktop choice."""


def request_runtime_upgrade(repo: Path, *, caller_pid: int | None = None,
                            resume_pending: bool = False) -> dict:
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
        resume = False
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
                if state['state'] == 'pending' and not state.get('resumeAttemptedAt'):
                    if not resume_pending:
                        raise PendingUpgradeError('上次升级交接中断。是否继续自动备份和迁移？原数据和备份会保留。')
                    resume = True
                else:
                    raise UpgradeError('上次升级未正常完成，请联系维护人员；原数据和备份仍保留。')
            if state.get('state') == 'failed':
                raise UpgradeError('自动升级未完成，请联系维护人员；原数据和备份仍保留。')
        script = repo / 'scripts' / 'auto-migrate-runtime.ps1'
        if not script.is_file():
            raise UpgradeError('升级程序缺失，请联系维护人员。')
        if resume:
            request_id = state.get('requestId', '')
            if not re.fullmatch(r'[a-f0-9]{32}', request_id) or not re.fullmatch(
                    r'runtime-move-[0-9-]+', state.get('backupName', '')):
                raise UpgradeError('升级记录无法验证，请联系维护人员；不要删除旧数据。')
            state.update(resumeAttemptedAt=time.time(), updatedAt=time.time())
        else:
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
        args = [str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                '-WindowStyle', 'Hidden', '-File', str(script), '-Dispatch', '-RequestId', request_id]
        if resume:
            args.append('-ResumePending')
        try:
            # A pythonw caller has no usable standard handles. Supply them and
            # keep the caller alive until the desktop scheduler accepts the job.
            process = subprocess.Popen(args, cwd=repo, env=environment, close_fds=True,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            result = process.wait(timeout=30)
        except OSError as exc:
            state.update(state='failed', updatedAt=time.time())
            temporary.write_text(json.dumps(state), encoding='utf-8')
            temporary.replace(state_path)
            raise UpgradeError('无法启动自动升级，请联系维护人员。') from exc
        except subprocess.TimeoutExpired as exc:
            # Do not terminate a dispatcher that may already own a worker, and
            # do not overwrite a state concurrently written by that worker.
            raise UpgradeError('升级交接仍未确认，请稍后重开；原数据和备份已保留。') from exc
        if result != 0:
            raise UpgradeError('自动升级交接失败，请联系维护人员；原数据和备份已保留。')
        acknowledgment = folder / (request_id + '.dispatch.json')
        try:
            if acknowledgment.is_symlink() or getattr(acknowledgment.lstat(), 'st_file_attributes', 0) & 0x400:
                raise ValueError('Invalid acknowledgment')
            accepted = json.loads(acknowledgment.read_text(encoding='utf-8-sig'))
            if accepted.get('requestId') != request_id or accepted.get('state') != 'dispatched':
                raise ValueError('Invalid acknowledgment')
            for attempt in range(10):
                try:
                    return json.loads(state_path.read_text(encoding='utf-8-sig'))
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.02)
        except (ValueError, OSError) as exc:
            raise UpgradeError('升级任务未确认接手，请联系维护人员；不要删除旧数据。') from exc
    finally:
        lock.close()
        lock_path.unlink()
