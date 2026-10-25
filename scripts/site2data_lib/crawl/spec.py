"""site2data_lib.crawl.spec — 数据规格（spec）加载与校验。

spec 描述"抓什么"：模式、URL 来源、字段选择器、限额、输出。
支持 JSON（零依赖）与 YAML（需 PyYAML，可选）。

schema 详见 references/spec-schema.md。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

VALID_MODES = ("list_detail", "url_list", "detail_only")
VALID_KINDS = ("text", "html", "attr")
VALID_TRANSFORMS = ("strip", "lower", "upper", "number", "join")


class SpecError(ValueError):
    """spec 不合法。"""


def load_spec(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise SpecError(f"spec 文件不存在: {p}")
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # 可选依赖
        except ImportError as exc:
            raise SpecError("YAML spec 需要 PyYAML（pip install PyYAML），或改用 .json") from exc
        data = yaml.safe_load(text)
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SpecError(f"spec JSON 解析失败: {exc}") from exc
    return validate_spec(data)


def validate_spec(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise SpecError("spec 顶层必须是对象")
    mode = data.get("mode", "list_detail")
    if mode not in VALID_MODES:
        raise SpecError(f"mode 必须是 {VALID_MODES} 之一，收到 {mode!r}")
    if not data.get("name"):
        raise SpecError("spec 缺少 name")

    detail = data.get("detail") or {}
    fields = detail.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise SpecError("spec.detail.fields 必须是非空对象（字段名 -> 提取规则）")
    for key, fs in fields.items():
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            raise SpecError(f"字段名须为合法标识符: {key!r}")
        if not isinstance(fs, dict) or not fs.get("selector"):
            raise SpecError(f"字段 {key} 缺少 selector")
        kind = fs.get("kind", "text")
        if kind not in VALID_KINDS:
            raise SpecError(f"字段 {kind} 的 kind 必须是 {VALID_KINDS} 之一")
        if kind == "attr" and not fs.get("attr"):
            raise SpecError(f"字段 {key} kind=attr 时必须提供 attr")

    if mode in ("url_list", "detail_only"):
        lst = data.get("list") or {}
        has_source = bool(lst.get("url") or lst.get("pages") or lst.get("template"))
        if not has_source:
            raise SpecError(f"mode={mode} 需要 list.url / list.pages / list.template 之一作为 URL 来源")
    else:  # list_detail
        lst = data.get("list") or {}
        has_source = bool(lst.get("url") or lst.get("pages") or lst.get("template"))
        if not has_source:
            raise SpecError("mode=list_detail 需要 list.url / list.pages / list.template 之一")
        if not (lst.get("link_selector") or lst.get("item_selector")):
            raise SpecError("mode=list_detail 需要 list.link_selector 或 list.item_selector")

    limits = data.get("limits") or {}
    if "max_items" in limits and int(limits["max_items"]) <= 0:
        raise SpecError("limits.max_items 必须 > 0")
    return data


def list_page_urls(spec: dict[str, Any]) -> list[str]:
    """展开列表页 URL（pages / url / template+pagination）。"""
    lst = spec.get("list") or {}
    if lst.get("pages"):
        return [str(u) for u in lst["pages"]]
    if lst.get("url"):
        return [str(lst["url"])]
    template = str(lst.get("template", ""))
    pagination = lst.get("pagination") or {}
    if pagination.get("pages"):
        return [template.replace("{page}", str(n)) for n in pagination["pages"]]
    start = int(pagination.get("start", 1))
    end = int(pagination.get("end", start))
    step = int(pagination.get("step", 1))
    return [template.replace("{page}", str(n)) for n in range(start, end + 1, step)]


def field_names(spec: dict[str, Any]) -> list[str]:
    return list((spec.get("detail") or {}).get("fields", {}).keys())
