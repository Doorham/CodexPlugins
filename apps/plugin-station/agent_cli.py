from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.control import ControlService


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Agent bridge for Codex插件站")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    action = sub.add_parser("action")
    action.add_argument("plugin_id")
    action.add_argument("action")
    action.add_argument("--payload", default="{}")
    args = parser.parse_args()

    service = ControlService(Path(__file__).resolve().parent)
    if args.command == "status":
        result = service.dashboard()
    else:
        result = service.perform_action(
            args.plugin_id,
            args.action,
            json.loads(args.payload),
            origin="agent",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
