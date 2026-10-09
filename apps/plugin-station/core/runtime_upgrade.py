"""Compatibility entry point: whole-directory private-state migration is retired."""
from pathlib import Path

class UpgradeError(RuntimeError):
    pass

class PendingUpgradeError(UpgradeError):
    pass

def request_runtime_upgrade(repo: Path, *, caller_pid=None, resume_pending=False) -> dict:
    raise UpgradeError("整目录迁移已停用；个人原件和备份保留本机，工具箱可直接启动。")
