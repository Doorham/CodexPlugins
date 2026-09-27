from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


CREATE_NO_WINDOW = 0x08000000
RATIOS = {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}
MJ_OPTIONS = {
    "version": ("--mj-version", str),
    "speed": ("--mj-speed", str),
    "stylize": ("--mj-stylize", int),
    "chaos": ("--mj-chaos", int),
    "weird": ("--mj-weird", int),
    "seed": ("--mj-seed", int),
    "quality": ("--mj-quality", str),
    "negative": ("--mj-negative", str),
}


def generate_image(repo_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Run the bundled bridge locally without exposing credentials in Agent results."""
    if not isinstance(payload, dict):
        raise ValueError("生图参数必须是对象")
    extra = set(payload) - {"prompt", "model", "ratio", "resolution", "quality", "num", "refs", "out", "prefix", "mj"}
    if extra:
        raise ValueError(f"不支持的生图参数：{', '.join(sorted(extra))}")
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20000:
        raise ValueError("prompt 必须是 1–20000 字的非空文本")
    model = payload.get("model", "gpt-image-2-5-sunburst")
    if not isinstance(model, str) or not re.fullmatch(r"[\w-]{1,100}", model, re.UNICODE):
        raise ValueError("model 无效")
    ratio = payload.get("ratio", "16:9")
    resolution = payload.get("resolution", "4K")
    quality = payload.get("quality", "high")
    num = payload.get("num", 1)
    if ratio not in RATIOS or resolution not in {"1K", "2K", "4K"} or quality not in {"low", "medium", "high"}:
        raise ValueError("画幅、分辨率或质量参数无效")
    if type(num) is not int or not 1 <= num <= 4:
        raise ValueError("num 必须是 1–4")
    refs = payload.get("refs", [])
    if not isinstance(refs, list) or len(refs) > 4 or any(not isinstance(ref, str) for ref in refs):
        raise ValueError("refs 最多包含 4 个图片路径")
    for ref in refs:
        path = Path(ref)
        if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise ValueError(f"参考图不存在或格式不支持：{ref}")
    out = payload.get("out", str(Path.home() / "Pictures" / "UpdreamBridge"))
    if not isinstance(out, str) or not Path(out).is_absolute():
        raise ValueError("out 必须是绝对路径")
    prefix = payload.get("prefix", "updream")
    if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", prefix):
        raise ValueError("prefix 只能使用字母、数字、下划线和连字符")
    mj = payload.get("mj", {})
    if not isinstance(mj, dict) or set(mj) - (set(MJ_OPTIONS) | {"raw", "tile"}):
        raise ValueError("mj 参数无效")

    script = repo_root / "helpers" / "updream-bridge" / "updream_gen.py"
    if not script.is_file():
        raise FileNotFoundError("工具箱内置 UpdreamBridge 生图程序缺失")
    command = [sys.executable, str(script), prompt, "--model", model, "--ratio", ratio,
               "--resolution", resolution, "--quality", quality, "--num", str(num),
               "--out", out, "--prefix", prefix, "--json"]
    for ref in refs:
        command.extend(["--ref", ref])
    for key, (flag, expected_type) in MJ_OPTIONS.items():
        if key in mj and mj[key] is not None:
            value = mj[key]
            if type(value) is not expected_type or len(str(value)) > 500:
                raise ValueError(f"mj.{key} 无效")
            command.extend([flag, str(value)])
    for key in ("raw", "tile"):
        if key in mj:
            if type(mj[key]) is not bool:
                raise ValueError(f"mj.{key} 必须是布尔值")
            if mj[key]:
                command.append(f"--mj-{key}")
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=900, cwd=str(repo_root),
                                creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("生图超时；请先在 UpDream 查看任务状态，避免重复提交扣费") from exc
    try:
        response = json.loads(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError("工具箱生图程序未返回有效结果") from exc
    if result.returncode or not response.get("ok"):
        error = str(response.get("error", ""))
        if "凭证" in error or "登录" in error:
            raise RuntimeError(error)
        raise RuntimeError("生图失败；请检查 UpDream 任务状态后再决定是否重试")
    return {
        "taskId": response.get("task_id"),
        "cost": response.get("cost"),
        "images": [{"path": item["path"], "bytes": item["bytes"]} for item in response["images"]],
        "message": "图片已保存到本机",
    }
