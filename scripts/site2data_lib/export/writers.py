"""site2data_lib.export.writers — 多格式导出。"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def write_jsonl(records: list[dict[str, Any]], path: str | Path) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True) if not p.parent.exists() else None
    with p.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return str(p)


def write_json(records: list[dict[str, Any]], path: str | Path) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True) if not p.parent.exists() else None
    p.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)


def write_csv(records: list[dict[str, Any]], path: str | Path) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True) if not p.parent.exists() else None
    if not records:
        p.write_text("", encoding="utf-8")
        return str(p)
    fieldnames: list[str] = []
    for r in records:
        for k in r:
            if k not in fieldnames:
                fieldnames.append(k)
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in records:
            writer.writerow({k: _cell(r.get(k)) for k in fieldnames})
    return str(p)


def write_markdown_table(records: list[dict[str, Any]], path: str | Path, columns: list[str] | None = None) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True) if not p.parent.exists() else None
    if not records:
        p.write_text("（无记录）\n", encoding="utf-8")
        return str(p)
    cols = columns or list(records[0].keys())
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in records[:500]:
        lines.append("| " + " | ".join(_cell(r.get(c)) for c in cols) + " |")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


def _cell(v: Any) -> str:
    if v is None:
        return ""
    s = str(v)
    return s.replace("|", "\\|").replace("\n", " ")


def write_all(records: list[dict[str, Any]], out_dir: str | Path, name: str, formats: list[str]) -> dict[str, str]:
    out = Path(out_dir)
    outputs: dict[str, str] = {}
    if "jsonl" in formats:
        outputs["jsonl"] = write_jsonl(records, out / f"{name}.jsonl")
    if "json" in formats:
        outputs["json"] = write_json(records, out / f"{name}.json")
    if "csv" in formats:
        outputs["csv"] = write_csv(records, out / f"{name}.csv")
    if "md" in formats:
        outputs["md"] = write_markdown_table(records, out / f"{name}.md")
    return outputs
