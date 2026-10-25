"""site2data_lib.crawl.codegen — 由 spec 生成独立可运行的 Python 爬虫。

生成物特点：
- 零内部依赖（只用 requests + bs4），用户拿走即可运行；
- dataclass 记录、类型标注、logging、argparse CLI；
- 指数退避重试、逐条异常隔离、progress.json 断点续跑、run 摘要；
- 内嵌 SPEC dict，改字段只需改 SPEC（或回 skills 重新 codegen）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TEMPLATE = Path(__file__).resolve().parents[3] / "assets" / "templates" / "crawler_template.py.tpl"


class CodegenError(RuntimeError):
    pass


def generate_crawler(spec: dict[str, Any], out_path: str | Path, template_path: str | Path | None = None) -> str:
    tpl_path = Path(template_path) if template_path else _TEMPLATE
    if not tpl_path.is_file():
        raise CodegenError(f"模板缺失: {tpl_path}")
    template = tpl_path.read_text(encoding="utf-8")

    field_names = list((spec.get("detail") or {}).get("fields", {}).keys())
    record_fields = "\n".join(f"    {name}: Any = None" for name in field_names)
    # 以 Python 字符串字面量注入 JSON（避免 true/false/null 与 Python 字面量不兼容）
    spec_literal = json.dumps(json.dumps(spec, ensure_ascii=False, indent=2))
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = Path(out_path)

    code = (
        template.replace("{{GENERATED_AT}}", generated_at)
        .replace("{{NAME}}", str(spec.get("name", "crawler")))
        .replace("{{FILENAME}}", out.name)
        .replace("{{SPEC_JSON_STR}}", spec_literal)
        .replace("{{RECORD_FIELDS}}", record_fields)
    )
    if "{{" in code:
        raise CodegenError("模板存在未替换占位符")

    if not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(code, encoding="utf-8")
    return str(out)


def default_out_path(spec: dict[str, Any], out_dir: str | Path) -> Path:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", str(spec.get("name", "crawler")))
    return Path(out_dir) / f"{name}_crawler.py"
