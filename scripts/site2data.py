#!/usr/bin/env python3
"""site2data 统一命令入口。

用法（在技能根目录执行）:
  python scripts/site2data.py recon <站点URL> [--max-pages N] [--max-depth N] [--out DIR] [--probe-rate]
  python scripts/site2data.py harvest <spec.json|spec.yaml> [--out DIR]
  python scripts/site2data.py codegen <spec.json|spec.yaml> [-o crawler.py]
  python scripts/site2data.py validate <records.jsonl> <spec.json> [--out DIR]
  python scripts/site2data.py config

命令 → 模块路由表见下方 COMMANDS；agent 只需按命令调用，无需了解内部结构。
所有命令结束时向 stdout 打印一行 JSON 摘要，供 agent 读取与如实汇报。
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

SKILL_ROOT = Path(_SCRIPTS).parent

COMMANDS = ("recon", "harvest", "codegen", "validate", "config")

ALIASES = {
    "scan": "recon",
    "analyze": "recon",
    "crawl": "harvest",
    "gen": "codegen",
    "check": "validate",
}


def _print_help() -> None:
    print(__doc__)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        _print_help()
        return 0
    if argv[0] in ("-V", "--version", "version"):
        print(json.dumps({"skill": "site2data", "version": "1.0.0"}, ensure_ascii=False))
        return 0

    name = ALIASES.get(argv[0], argv[0])
    if name not in COMMANDS:
        print(f"未知命令: {argv[0]}\n", file=sys.stderr)
        _print_help()
        return 2

    module = importlib.import_module("site2data_lib.cli")
    handler = getattr(module, f"cmd_{name}")
    return int(handler(argv[1:], skill_root=SKILL_ROOT))


if __name__ == "__main__":
    sys.exit(main())
