"""Serialize cooperating config writers; preserve changes made by other editors."""
from __future__ import annotations

import os
import time
import uuid
import msvcrt
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def config_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + '.codextools.lock').open('a+b') as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b'0'); stream.flush()
        deadline = time.monotonic() + 15
        while True:
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('配置正在被另一项操作使用，请稍后重试')
                time.sleep(.05)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def replace_config(path: Path, original: str, updated: str) -> None:
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(updated, encoding='utf-8', newline='')
        current = path.read_text(encoding='utf-8') if path.exists() else ''
        if current != original:
            raise RuntimeError('其他程序修改了配置，已保留其修改；请重新执行此操作')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
