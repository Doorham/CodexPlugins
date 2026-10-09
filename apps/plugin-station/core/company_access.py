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
from .tool_paths import USER_DATA_ROOT

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
            or any(not isinstance(d, dict) or not {"letter", "remote"} <= set(d)
                   or set(d) - {"letter", "remote", "lanRemote"} for d in config["drives"])):
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
                    str(source), str(repo / "helpers/common/RuntimePaths.cs")], check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)


def connector_source_hash():
    source = Path(__file__).resolve().parents[3] / "helpers" / "nas-remote-connect" / "src" / "Program.cs"
    return hashlib.sha256(source.read_bytes() + (source.parents[2] / "common/RuntimePaths.cs").read_bytes()).hexdigest()


class CompanyAccess:
    def __init__(self, root=None):
        self.root = Path(root) if root else USER_DATA_ROOT / "CodexTools" / "CompanyAccess"
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
        self._install_config(config)
        return {"ok": True, "message": "公司文件已导入，两个公司模块已启用；连接时再完成 Tailscale 和 NAS 登录"}

    def refresh_connector(self):
        record = self.record()
        if not record or record.get("sourceSha256") == connector_source_hash():
            return False
        folder = self.root / "payloads" / record["payloadId"]
        executable = folder / "NasRemoteConnect.exe"
        from .control import process_pids
        if process_pids("NasRemoteConnect.exe", executable):
            raise ValueError("连接程序尚未正常退出；原程序、个人状态和自启保留，请退出后再打开")
        staging = self.root / ("program-build-" + uuid.uuid4().hex)
        staging.mkdir(parents=True)
        try:
            source_hash = connector_source_hash()
            build_connector(staging)
            if connector_source_hash() != source_hash: raise ValueError("构建期间公共源码变化")
            code = staging / "NasRemoteConnect.exe"
            record["files"]["NasRemoteConnect.exe"] = hashlib.sha256(code.read_bytes()).hexdigest()
            record["sourceSha256"] = source_hash
            # Stable payload/executable path keeps existing startup references valid.
            backup = staging / "previous.exe"
            shutil.copy2(executable, backup)
            os.replace(code, executable)
            try:
                temporary = self.record_file.with_suffix('.updating')
                temporary.write_bytes(protect(json.dumps(record).encode()))
                os.replace(temporary, self.record_file)
            except Exception:
                os.replace(backup, executable)
                raise
        finally:
            shutil.rmtree(staging)
        return True

    def confirm_lan_mappings(self, mappings, *, confirmed=False):
        """Save endpoints only after the human confirms they are the same NAS."""
        if not confirmed or set(mappings) != set("WXYZ"):
            raise ValueError("必须明确确认现有四个盘对应同两台 NAS")
        folder = self.payload_root()
        if folder is None:
            raise ValueError("公司模块尚未启用")
        config = json.loads((folder / "nas-drives.json").read_text(encoding="utf-8-sig"))
        for drive in config["drives"]:
            drive["lanRemote"] = mappings[drive["letter"]]
        from .company_drives import expected_drives
        expected_drives(config)  # Reject malformed endpoints and different shares.
        self._install_config(config)
        return {"ok": True, "message": "已保存明确确认的局域网备用地址；现有映射保持不变"}

    def _install_config(self, config):
        source_hash = connector_source_hash()
        payload_id = uuid.uuid4().hex
        folder = self.root / "payloads" / payload_id
        folder.mkdir(parents=True)
        temporary = self.record_file.with_name("activation." + uuid.uuid4().hex + ".tmp")
        try:
            build_connector(folder)
            (folder / "nas-drives.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            files = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                     for name in ("NasRemoteConnect.exe", "nas-drives.json")}
            if source_hash != connector_source_hash():
                raise ValueError("编译期间连接程序源码发生变化，请重试")
            record = {"companyId": COMPANY_ID, "format": "local-guide/v1", "payloadId": payload_id,
                      "files": files, "sourceSha256": source_hash}
            temporary.write_bytes(protect(json.dumps(record).encode()))
            temporary.replace(self.record_file)
        except Exception:
            temporary.unlink(missing_ok=True)
            shutil.rmtree(folder)
            raise

    def deactivate(self):
        self.record_file.unlink(missing_ok=True)
        return {"ok": True, "message": "公司模块已停用；现有网络盘映射保留"}
