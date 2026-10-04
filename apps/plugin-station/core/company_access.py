"""Import an explicitly supplied private data file; never fetch company configuration."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

COMPANY_ID = "wanling-media"
MODULE_IDS = ["company-nas-remote-connect", "company-network-drive-access"]


def protect(data: bytes, decrypt=False) -> bytes:
    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.c_void_p)]
    memory = ctypes.create_string_buffer(data)
    source, target = Blob(len(data), ctypes.cast(memory, ctypes.c_void_p)), Blob()
    crypto = ctypes.WinDLL("crypt32", use_last_error=True)
    func = crypto.CryptUnprotectData if decrypt else crypto.CryptProtectData
    func.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(Blob)]
    func.restype = ctypes.c_bool
    if not func(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError("本机模块记录校验失败，请重新导入公司文件")
    kernel = ctypes.WinDLL("kernel32")
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def read_guide(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("公司引导文件超过大小限制")
    guide = json.loads(raw.decode("utf-8-sig"))
    if (not isinstance(guide, dict) or set(guide) != {"format", "companyId", "modules", "config", "instructions"}
            or guide["format"] != "codextools-company-guide/v1" or guide["companyId"] != COMPANY_ID
            or guide["modules"] != MODULE_IDS or not isinstance(guide["instructions"], str)
            or len(guide["instructions"]) > 8000):
        raise ValueError("公司引导文件格式不受支持")
    config = guide["config"]
    if not isinstance(config, dict) or set(config) != {"drives", "defaultUser"}:
        raise ValueError("仅允许网络盘和默认用户名配置")
    if not isinstance(config["defaultUser"], str) or not re.fullmatch(r"[\w.@-]{1,128}", config["defaultUser"]):
        raise ValueError("默认用户名格式无效")
    if (not isinstance(config["drives"], list) or len(config["drives"]) != 4
            or any(not isinstance(d, dict) or set(d) != {"letter", "remote"} for d in config["drives"])):
        raise ValueError("网络盘配置格式无效")
    from .company_drives import expected_drives
    expected_drives(config)
    if [d["letter"] for d in config["drives"]] != list("WXYZ"):
        raise ValueError("盘符必须为 W、X、Y、Z")
    return config  # Instructions are descriptive text, never executable commands.


def build_connector(folder):
    """Compile only reviewed bundled source, with fixed compiler arguments."""
    repo = Path(__file__).resolve().parents[3]
    source = repo / "helpers" / "nas-remote-connect" / "src" / "Program.cs"
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    if not source.is_file() or not compiler.is_file():
        raise ValueError("工具箱缺少连接程序源码或 Windows .NET 编译器，请更新完整工具箱")
    subprocess.run([str(compiler), "/nologo", "/optimize+", "/target:winexe",
                    "/out:" + str(folder / "NasRemoteConnect.exe"),
                    *["/reference:" + name + ".dll" for name in
                      ("System", "System.Core", "System.Security", "System.Windows.Forms", "System.Drawing", "System.Web.Extensions")],
                    str(source)], check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)


class CompanyAccess:
    def __init__(self, root=None):
        self.root = Path(root) if root else Path(os.environ["LOCALAPPDATA"]) / "CompanyAIHelpers" / "CodexTools" / "CompanyAccess"
        self.record_file = self.root / "activation.dpapi"

    def record(self):
        try:
            record = json.loads(protect(self.record_file.read_bytes(), decrypt=True))
            if (record["companyId"] != COMPANY_ID or record["format"] != "local-guide/v1"
                    or not re.fullmatch(r"[a-f0-9]{32}", record["payloadId"])
                    or set(record["files"]) != {"NasRemoteConnect.exe", "nas-drives.json"}):
                return None
            folder = self.root / "payloads" / record["payloadId"]
            if folder.is_symlink():
                return None
            for name, digest in record["files"].items():
                path = folder / name
                if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    return None
            return record
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def active(self, company=COMPANY_ID):
        return company == COMPANY_ID and self.record() is not None

    def status(self):
        return {"active": self.active(), "name": "万灵传媒"}

    def payload_root(self):
        record = self.record()
        return self.root / "payloads" / record["payloadId"] if record else None

    def import_guide(self, path):
        config = read_guide(path)  # Fully validate before creating state or building anything.
        payload_id = uuid.uuid4().hex
        folder = self.root / "payloads" / payload_id
        folder.mkdir(parents=True)
        temporary = self.record_file.with_name("activation." + uuid.uuid4().hex + ".tmp")
        try:
            build_connector(folder)
            (folder / "nas-drives.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            files = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                     for name in ("NasRemoteConnect.exe", "nas-drives.json")}
            record = {"companyId": COMPANY_ID, "format": "local-guide/v1", "payloadId": payload_id, "files": files}
            temporary.write_bytes(protect(json.dumps(record).encode()))
            temporary.replace(self.record_file)
        except Exception:
            temporary.unlink(missing_ok=True)
            shutil.rmtree(folder)
            raise
        return {"ok": True, "message": "公司文件已导入，两个公司模块已启用；连接时再完成 Tailscale 和 NAS 登录"}

    def deactivate(self):
        self.record_file.unlink(missing_ok=True)
        return {"ok": True, "message": "公司模块已停用；现有网络盘映射保留"}
