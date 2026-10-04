from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.control import ControlService


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Agent bridge for Codex插件站")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("manifest")
    importer = sub.add_parser("import-company-guide", help="导入用户提供的公司引导文件，仅启用两个公司模块")
    importer.add_argument("file")
    action = sub.add_parser("action")
    action.add_argument("plugin_id")
    action.add_argument("action")
    action.add_argument("--payload", default="{}")
    action.add_argument("--payload-stdin", action="store_true", help="从标准输入读取 JSON 参数，避免提示词出现在命令行")
    args = parser.parse_args()

    service = ControlService(Path(__file__).resolve().parent)
    if args.command == "status":
        result = service.dashboard()
    elif args.command == "manifest":
        result = service.agent_manifest()
    elif args.command == "import-company-guide":
        result = service.import_company_guide(args.file)
    else:
        result = service.perform_action(
            args.plugin_id,
            args.action,
            json.loads(sys.stdin.read() if args.payload_stdin else args.payload),
            origin="agent",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
