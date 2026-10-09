"""Build the bundled voice module on first use; no manifest commands are executed."""
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path


def build_voice_bridge(repo_root: Path, output: Path) -> None:
    root = repo_root.resolve()
    expected = (root / "artifacts/helpers/WeTypeAweSunBridge.exe").resolve()
    if output.resolve() != expected:
        raise ValueError("语音模块构建目标不匹配")
    source = (root / "helpers/wetype-awesun-bridge/src/Program.cs").resolve()
    icon = (root / "helpers/wetype-awesun-bridge/assets/voice.ico").resolve()
    for path in (source, icon):
        if not path.is_relative_to(root):
            raise ValueError("语音模块源码路径越界")
        if not path.is_file():
            raise FileNotFoundError("语音模块安装源码不完整，请检查工具箱更新。")
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidates = [windows / "Microsoft.NET" / framework / "v4.0.30319/csc.exe"
                  for framework in ("Framework64", "Framework")]
    compiler = next((path for path in candidates if path.is_file()), None)
    if compiler is None:
        raise RuntimeError("找不到 Windows .NET Framework 编译器，无法安装语音模块。")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}-{uuid.uuid4().hex}.building.exe")
    try:
        result = subprocess.run(
            [str(compiler), "/nologo", "/optimize+", "/target:winexe", "/platform:anycpu",
             f"/out:{temporary}", f"/win32icon:{icon}", "/reference:System.dll",
             "/reference:System.Core.dll", "/reference:System.Windows.Forms.dll",
             "/reference:System.Drawing.dll", str(source)],
            cwd=root, stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        if result.returncode or not temporary.is_file():
            raise RuntimeError("语音模块自动构建失败，未修改启动项或安装文件。")
        with temporary.open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise RuntimeError("语音模块构建产物无效，未安装。")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


# Program-only provenance. A stale local artifact must never reopen flat account state.
def ensure_helper_artifact_current(repo: Path, plugin_id: str, artifact: Path) -> None:
    import hashlib, json
    from .atomic_files import atomic_json
    kinds = {
        'updream-bridge': ('updream-bridge', 'build-updream-bridge.ps1'),
        'codex-answer-chime': ('codex-answer-chime', 'build-helpers.ps1'),
        'software-environment-checker': ('environment-detector', 'build-helpers.ps1'),
        'codex-environment-helper': ('environment-detector', 'build-helpers.ps1'),
        'logitech-g435-battery': ('logitech-g435-battery-monitor', 'build-helpers.ps1'),
    }
    if plugin_id not in kinds: return
    component, script = kinds[plugin_id]
    files = [repo / f'helpers/{component}/src/Program.cs', repo / 'helpers/common/RuntimePaths.cs', repo / 'scripts' / script]
    if component != 'updream-bridge': files.append(repo / 'helpers/common/RuntimeControl.cs')
    def digest():
        return hashlib.sha256(b''.join(path.read_bytes() for path in files)).hexdigest()
    wanted = digest()
    record_file = artifact.with_name(artifact.name + '.public-source.json')
    try: record = json.loads(record_file.read_text(encoding='utf-8'))
    except (OSError, ValueError): record = {}
    if artifact.is_file() and record.get('source') == wanted and record.get('program') == hashlib.sha256(artifact.read_bytes()).hexdigest(): return
    result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(repo/'scripts'/script)],
        cwd=repo, capture_output=True, timeout=240, creationflags=0x08000000)
    if result.returncode or not artifact.is_file(): raise RuntimeError('当前程序源码尚未构建成功；保留原程序，未打开旧版个人状态')
    if digest() != wanted: raise RuntimeError('构建期间公共源码变化，请重试')
    atomic_json(record_file, {'source':wanted,'program':hashlib.sha256(artifact.read_bytes()).hexdigest()})
