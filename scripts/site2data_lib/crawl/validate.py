"""site2data_lib.crawl.validate — 抓取结果质量校验。

产出校验报告：必填字段填充率、重复 URL、空记录、类型粗检。
原则：如实报告，不静默过滤（对齐生态"诚实汇报"最佳实践）。
"""
from __future__ import annotations

from typing import Any


def validate_records(records: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = (spec.get("detail") or {}).get("fields", {})
    total = len(records)
    report: dict[str, Any] = {
        "total": total,
        "field_fill_rate": {},
        "duplicate_urls": [],
        "empty_records": 0,
        "required_missing": {},
        "pass": True,
    }
    if total == 0:
        report["pass"] = False
        report["notes"] = ["无任何记录"]
        return report

    url_counts: dict[str, int] = {}
    for r in records:
        u = str(r.get("_url", ""))
        url_counts[u] = url_counts.get(u, 0) + 1
        if all(v in (None, "") for k, v in r.items() if not k.startswith("_")):
            report["empty_records"] += 1

    report["duplicate_urls"] = [u for u, c in url_counts.items() if c > 1 and u]

    for name, fs in fields.items():
        filled = sum(1 for r in records if r.get(name) not in (None, ""))
        rate = round(filled / total, 4)
        report["field_fill_rate"][name] = rate
        if not fs.get("optional", False) and rate < 0.5:
            report["required_missing"][name] = rate
            report["pass"] = False

    if report["empty_records"] > total * 0.2:
        report["pass"] = False
    return report
