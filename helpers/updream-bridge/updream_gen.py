#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UpDream 生图桥 CLI —— 让任意本地 Agent（Codex / WorkBuddy / 其他）调用 UpDream 出 4K 图。

凭证读取顺序（严守「只认本机本地」，绝不读包目录/公共区，防 token 泄露）：
  1. 环境变量 UPDREAM_TOKEN / UPDREAM_PROJECT_ID
  2. 工具箱独立运行目录中的 UpdreamBridge/credentials.json（不进入源码或公区）

首次使用请在 Codex 工具箱打开 UpdreamBridge 账号配置。
"""
import argparse, base64, json, os, ssl, sys, time, uuid, urllib.request, urllib.error
from pathlib import Path

BASE = "https://www.updream.cn/api"
_script_root = Path(__file__).resolve().parent
_data_root = Path(os.environ["CODEXTOOLS_DATA_ROOT"]) if os.environ.get("CODEXTOOLS_DATA_ROOT") else (
    _script_root.parent if _script_root.parent.name == "CompanyAIHelpers"
    else _script_root.parents[1] / ".runtime" / "CompanyAIHelpers")
CRED_PATH = _data_root / "UpdreamBridge" / "credentials.json"
_ctx = ssl.create_default_context()

# 标准尺寸表（服务端按 image_resolution+ratio 定尺寸，这里 width/height 作兜底）
SIZE_MAP = {
    "1:1":  {"1K": (960, 960),    "2K": (1920, 1920),  "4K": (2880, 2880)},
    "2:3":  {"1K": (800, 1184),   "2K": (1568, 2336),  "4K": (2368, 3552)},
    "3:2":  {"1K": (1184, 800),   "2K": (2336, 1568),  "4K": (3552, 2368)},
    "3:4":  {"1K": (832, 1120),   "2K": (1664, 2208),  "4K": (2496, 3328)},
    "4:3":  {"1K": (1120, 832),   "2K": (2208, 1664),  "4K": (3328, 2496)},
    "4:5":  {"1K": (864, 1088),   "2K": (1696, 2112),  "4K": (2560, 3200)},
    "5:4":  {"1K": (1088, 864),   "2K": (2112, 1696),  "4K": (3200, 2560)},
    "9:16": {"1K": (736, 1280),   "2K": (1440, 2560),  "4K": (2176, 3840)},
    "16:9": {"1K": (1280, 736),   "2K": (2560, 1440),  "4K": (3840, 2176)},
    "21:9": {"1K": (1472, 640),   "2K": (2912, 1248),  "4K": (4384, 1888)},
}

MODEL_ALIASES = {
    "midjourney": "midjourney", "mj": "midjourney", "悠船": "midjourney", "youchuan": "midjourney",
    "sunburst": "gpt-image-2-5-sunburst", "flare": "gpt-image-2-5-flare", "gpt2": "gpt-image-2",
}


def _resolve_model(name):
    return MODEL_ALIASES.get(str(name).lower(), name)


def _decode_exp(token):
    try:
        p = token.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p)).get("exp")
    except Exception:
        return None


def _refresh_tokens(c):
    """用 refresh_token 换新 access/refresh token 并落盘。成功返回新 access_token，失败返回 None。"""
    rt = c.get("refresh_token")
    at = c.get("access_token")
    if not rt:
        return None
    try:
        req = urllib.request.Request(
            BASE + "/auth/refresh",
            data=json.dumps({"refresh_token": rt}).encode(),
            headers={"Authorization": "Bearer " + (at or rt), "Content-Type": "application/json",
                     "Accept-Language": "zh", "Cache-Control": "no-cache",
                     "User-Agent": "Mozilla/5.0 Chrome/126.0", "Referer": "https://www.updream.cn/"},
            method="POST")
        r = urllib.request.urlopen(req, timeout=30, context=_ctx)
        d = json.loads(r.read().decode("utf-8", "ignore"))
        if d.get("access_token") and d.get("refresh_token"):
            c["access_token"] = d["access_token"]
            c["refresh_token"] = d["refresh_token"]
            ne = _decode_exp(d["access_token"])
            if ne:
                c["expires_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ne))
            temporary = CRED_PATH.with_name("credentials-" + uuid.uuid4().hex + ".tmp")
            try:
                temporary.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(temporary, CRED_PATH)
            finally:
                temporary.unlink(missing_ok=True)
            return d["access_token"]
    except Exception:
        return None
    return None


def _load_cred():
    token = os.environ.get("UPDREAM_TOKEN")
    project = os.environ.get("UPDREAM_PROJECT_ID")
    if token:
        return token, project
    if CRED_PATH.exists():
        try:
            c = json.loads(CRED_PATH.read_text(encoding="utf-8"))
        except Exception:
            c = {}
        token = c.get("access_token")
        project = project or c.get("project_id")
        if token:
            # 快过期（<24h）或已过期 → 自动用 refresh_token 续期
            exp = _decode_exp(token)
            if exp is None or exp - time.time() < 86400:
                new_tok = _refresh_tokens(c)
                if new_tok:
                    token = new_tok
                elif exp is not None and exp < time.time():
                    raise RuntimeError("登录已过期且自动刷新失败，请在 Codex 工具箱的 UpdreamBridge 中重新配置")
            return token, project
    raise RuntimeError("未找到本机凭证，请在 Codex 工具箱的 UpdreamBridge 中完成配置")


_CRED = None


def _cred():
    global _CRED
    if _CRED is None:
        _CRED = _load_cred()
    return _CRED


def _api(method, path, body=None, idempotency=False, timeout=120, raw_headers=None):
    headers = {
        "Authorization": "Bearer " + _cred()[0], "Accept-Language": "zh",
        "Content-Type": "application/json", "Cache-Control": "no-cache",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36",
        "Referer": "https://www.updream.cn/",
    }
    if raw_headers:
        headers.pop("Content-Type", None)
        headers.update(raw_headers)
    if idempotency:
        headers["Idempotency-Key"] = "image:" + str(uuid.uuid4())
    data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=timeout, context=_ctx)
        raw = r.read()
        try:
            return r.status, json.loads(raw.decode("utf-8", "ignore"))
        except Exception:
            return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            raw = json.loads(raw)
        except Exception:
            pass
        return e.code, raw


def _upload_image(path):
    fname = os.path.basename(path)
    ext = os.path.splitext(fname)[1].lower().lstrip(".")
    ctype = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
    data = open(path, "rb").read()
    boundary = "----updream" + uuid.uuid4().hex
    body = (b"--" + boundary.encode() + b"\r\n"
            b'Content-Disposition: form-data; name="file"; filename="' + fname.encode("utf-8", "ignore") + b'"\r\n'
            b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + data + b"\r\n"
            b"--" + boundary.encode() + b"--\r\n")
    s, r = _api("POST", "/upload/image", body=body,
                raw_headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    if s != 200:
        raise RuntimeError("上传失败 %s: %s" % (s, r))
    return r.get("url")


def _download(url, outpath):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Chrome/126.0", "Referer": "https://www.updream.cn/"})
    data = urllib.request.urlopen(req, timeout=180, context=_ctx).read()
    with open(outpath, "wb") as f:
        f.write(data)
    return outpath, len(data)


def generate(prompt, model="gpt-image-2-5-sunburst", ratio="16:9", resolution="4K",
             quality="high", num=1, project_id=None, refs=None, out=".", out_prefix="updream",
             mj=None, progress=print):
    model = _resolve_model(model)
    project_id = project_id or _cred()[1]
    refs = refs or []
    mj = mj or {}
    ref_urls = [_upload_image(p) for p in refs]
    is_mj = (model == "midjourney")
    if is_mj:
        res = str(resolution).lower()
        if res not in ("1k", "2k"):
            res = "1k"
        body_res = res
        w, h = SIZE_MAP.get(ratio, {}).get(res.upper(), (1024, 1024))
    else:
        body_res = resolution
        w, h = SIZE_MAP.get(ratio, {}).get(str(resolution).upper(), (1024, 1024))
    body = {
        "prompt": prompt, "model_name": model,
        "width": w, "height": h, "num_images": num, "ratio": ratio,
        "reference_images": ref_urls,
        "image_resolution": body_res,
    }
    if project_id:
        body["project_id"] = project_id
    if is_mj:
        for k, v in mj.items():
            if v is not None:
                body[k] = v
    else:
        body["image_quality"] = quality
        body["transparent_background"] = False
        body["output_compression"] = 100
    s, r = _api("POST", "/ai/generate-image/async", body, idempotency=True)
    if s != 200 or not isinstance(r, dict) or not r.get("task_id"):
        raise RuntimeError("提交失败 %s: %s" % (s, r))
    task_id = r["task_id"]
    cost = r.get("frozen_credits")
    progress("[updream] 已提交 task=%s 冻结积分=%s" % (task_id, cost))
    st = None
    for _ in range(200):
        time.sleep(3)
        s2, st = _api("GET", "/ai/task/" + task_id)
        status = st.get("status") if isinstance(st, dict) else None
        if status == "completed":
            break
        if status == "failed":
            raise RuntimeError("生成失败: " + json.dumps(st, ensure_ascii=False))
        if isinstance(st, dict) and st.get("progress") not in (None, 30):
            progress("[updream] 进度 %s%%" % st.get("progress"))
    else:
        raise RuntimeError("生成超时")
    urls = (st.get("result") or {}).get("images", []) if isinstance(st, dict) else []
    if not urls:
        raise RuntimeError("无结果: " + json.dumps(st, ensure_ascii=False))
    os.makedirs(out, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    saved = []
    for i, u in enumerate(urls):
        ext = os.path.splitext(u.split("?")[0])[1] or ".jpg"
        p = os.path.join(out, "%s_%s_%d%s" % (out_prefix, stamp, i, ext))
        path, size = _download(u, p)
        saved.append({"url": u, "path": os.path.abspath(path), "bytes": size})
    return {"task_id": task_id, "cost": cost, "images": saved}


def main():
    ap = argparse.ArgumentParser(description="UpDream 生图 CLI 桥")
    ap.add_argument("prompt")
    ap.add_argument("--model", default="gpt-image-2-5-sunburst")
    ap.add_argument("--ratio", default="16:9")
    ap.add_argument("--resolution", default="4K")
    ap.add_argument("--quality", default="high")
    ap.add_argument("--num", type=int, default=1)
    ap.add_argument("--ref", action="append", default=[], help="参考图路径，可多次")
    ap.add_argument("--out", default=".", help="输出目录")
    ap.add_argument("--prefix", default="updream", help="输出文件名前缀")
    ap.add_argument("--project-id", default=None)
    # ---- 悠船（Midjourney）结构化参数：提示词无需带 --ar --s --c 等 ----
    ap.add_argument("--mj-version", default="v8.2", help="悠船版本：v7 / v8.1 / v8.2（默认 v8.2）")
    ap.add_argument("--mj-speed", default=None, help="悠船速度：fast / turbo")
    ap.add_argument("--mj-stylize", type=int, default=None, help="风格化 0-1000（对应 --s）")
    ap.add_argument("--mj-chaos", type=int, default=None, help="多样性 0-100（对应 --c）")
    ap.add_argument("--mj-weird", type=int, default=None, help="怪诞 0-3000（对应 --w）")
    ap.add_argument("--mj-seed", type=int, default=None, help="随机种子（对应 --seed）")
    ap.add_argument("--mj-quality", default=None, help="渲染质量（对应 --q，如 1 / 0.5）")
    ap.add_argument("--mj-raw", action="store_true", help="Raw 模式（对应 --style raw）")
    ap.add_argument("--mj-tile", action="store_true", help="平铺无缝贴图（对应 --tile）")
    ap.add_argument("--mj-negative", default=None, help="负面提示（对应 --no）")
    ap.add_argument("--json", action="store_true", help="stdout 只输出一行 JSON 结果")
    a = ap.parse_args()

    # 仅悠船生效；None 字段在 generate() 内被跳过
    mj = {
        "mj_version": a.mj_version, "mj_speed": a.mj_speed, "mj_stylize": a.mj_stylize,
        "mj_chaos": a.mj_chaos, "mj_weird": a.mj_weird, "mj_seed": a.mj_seed,
        "mj_quality": a.mj_quality, "mj_raw": a.mj_raw or None, "mj_tile": a.mj_tile or None,
        "mj_negative_prompt": a.mj_negative,
    }

    def progress(msg):
        if not a.json:
            print(msg, flush=True)

    try:
        r = generate(a.prompt, model=a.model, ratio=a.ratio, resolution=a.resolution,
                     quality=a.quality, num=a.num, project_id=a.project_id, refs=a.ref,
                     out=a.out, out_prefix=a.prefix, mj=mj, progress=progress)
    except Exception as e:
        if a.json:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        else:
            print("ERROR:", e, file=sys.stderr)
        sys.exit(1)
    if a.json:
        print(json.dumps({"ok": True, **r}, ensure_ascii=False))
    else:
        for im in r["images"]:
            print(im["path"])


if __name__ == "__main__":
    main()
