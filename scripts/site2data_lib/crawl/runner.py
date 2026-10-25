"""site2data_lib.crawl.runner — 规格解释器：按 spec 执行抓取（harvest 命令）。

流程：展开 URL 来源 →（list_detail 时）列表页发现详情链接 → 逐条抓详情 → 抽字段
→ 多格式导出 → run 摘要。全链路幂等：progress.json 记录已完成 URL，重跑即续跑。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..core.http_client import FetchError, HttpClient
from ..core.logging_utils import get_logger
from ..core.models import ScanResult  # noqa: F401  (保持与 recon 产物类型一致的引用习惯)
from ..core.robots import RobotsGuard
from ..export.summary import RunSummary
from ..export.writers import write_all
from . import spec as specmod

log = get_logger("site2data.harvest")


def extract_field(soup: BeautifulSoup, fs: dict[str, Any]) -> Any:
    """按字段规则提取单个值。selector 支持 CSS；kind: text|html|attr。"""
    el = soup.select_one(str(fs["selector"]))
    if el is None:
        return None
    kind = fs.get("kind", "text")
    if kind == "attr":
        raw = el.get(str(fs.get("attr", "")))
    elif kind == "html":
        raw = el.decode_contents()
    else:
        raw = el.get_text(" ", strip=True)
    return _transform(raw, fs.get("transform"))


def extract_fields(soup: BeautifulSoup, fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, fs in fields.items():
        try:
            out[name] = extract_field(soup, fs)
        except Exception as exc:  # 单字段失败不拖垮整条记录
            out[name] = None
            log.debug("字段 %s 提取失败: %s", name, exc)
    return out


def _transform(raw: Any, transform: str | None) -> Any:
    if raw is None or not transform:
        return raw
    t = str(transform)
    if t == "strip":
        return re.sub(r"\s+", " ", str(raw)).strip()
    if t == "lower":
        return str(raw).lower()
    if t == "upper":
        return str(raw).upper()
    if t == "number":
        m = re.search(r"-?\d+(?:\.\d+)?", str(raw))
        return float(m.group(0)) if m and "." in m.group(0) else (int(m.group(0)) if m else None)
    if t == "join":
        return re.sub(r"\s+", " ", str(raw)).strip()
    m = re.match(r"regex:(.+)", t)
    if m:
        match = re.search(m.group(1), str(raw))
        if not match:
            return None
        return match.group(1) if match.groups() else match.group(0)
    return raw


def discover_detail_urls(spec: dict[str, Any], client: HttpClient, parser: str) -> list[str]:
    """按模式产出待抓取的详情 URL 列表（列表页发现或直接展开）。"""
    mode = spec.get("mode", "list_detail")
    if mode in ("url_list", "detail_only"):
        return specmod.list_page_urls(spec)

    lst = spec.get("list") or {}
    link_sel = lst.get("link_selector")
    item_sel = lst.get("item_selector")
    link_attr = lst.get("link_attr", "href")
    urls: list[str] = []
    seen: set[str] = set()
    for list_url in specmod.list_page_urls(spec):
        try:
            resp = client.get(list_url)
        except FetchError as exc:
            log.warning("列表页失败: %s", exc)
            continue
        if resp.status_code != 200:
            log.warning("列表页 HTTP %s: %s", resp.status_code, list_url)
            continue
        soup = BeautifulSoup(resp.text, parser)
        scopes = soup.select(item_sel) if item_sel else [soup]
        for scope in scopes:
            anchor = scope.select_one(link_sel) if link_sel else (scope if scope.name == "a" else None)
            if anchor is None:
                continue
            href = anchor.get(link_attr)
            if not href:
                continue
            full = urljoin(list_url, str(href))
            if full not in seen:
                seen.add(full)
                urls.append(full)
    return urls


def run_harvest(spec: dict[str, Any], cfg: dict[str, Any], out_dir: str | Path) -> RunSummary:
    out = Path(out_dir)
    if not out.exists():
        out.mkdir(parents=True, exist_ok=True)
    parser = cfg.get("parser", "html.parser")
    client = HttpClient.from_config(cfg)
    if spec.get("headers"):
        client.session.headers.update(spec["headers"])
    if spec.get("cookies"):
        client.session.cookies.update(spec["cookies"])

    robots = RobotsGuard(cfg["user_agent"], bool(cfg.get("respect_robots", True)))
    limits = spec.get("limits") or {}
    max_items = int(limits.get("max_items", cfg.get("harvest_max_items", 100)))
    delay = float(limits.get("delay_seconds", cfg.get("harvest_delay_seconds", 1.0)))
    client.limiter.min_interval = max(client.limiter.min_interval, delay)

    summary = RunSummary(task=f"harvest:{spec.get('name', '')}")
    fields = (spec.get("detail") or {}).get("fields", {})

    # ---- 断点续跑 ----
    progress_path = out / "progress.json"
    progress: dict[str, Any] = {"done": [], "failed": {}}
    if progress_path.is_file():
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            progress.setdefault("done", [])
            progress.setdefault("failed", {})
            summary.notes.append(f"续跑：已完成 {len(progress['done'])} 条")
        except json.JSONDecodeError:
            summary.notes.append("progress.json 损坏，重新开始")

    def save_progress() -> None:
        progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 发现详情 URL ----
    detail_urls = discover_detail_urls(spec, client, parser)
    summary.total = min(len(detail_urls), max_items)
    if not detail_urls:
        summary.notes.append("未发现任何详情 URL（检查 list 配置与选择器）")
        summary.save(out / "run_summary.json")
        return summary

    done_set = set(progress["done"])
    records: list[dict[str, Any]] = []
    # 续跑时把已完成记录从既有 jsonl 读回，保证导出完整
    existing_jsonl = out / f"{spec.get('name', 'records')}.jsonl"
    if existing_jsonl.is_file() and done_set:
        for line in existing_jsonl.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    count = 0
    for url in detail_urls:
        if count >= max_items:
            break
        if url in done_set:
            continue
        count += 1
        try:
            resp = client.get(url)
            if resp.status_code != 200:
                raise FetchError(url, "非 200 响应", resp.status_code)
            soup = BeautifulSoup(resp.text, parser)
            values = extract_fields(soup, fields)
            record = {"_url": url, "_status": resp.status_code, **values}
            records.append(record)
            progress["done"].append(url)
            summary.success += 1
        except Exception as exc:  # noqa: BLE001 — 单条失败不中断批次
            log.warning("抓取失败 %s: %s", url, exc)
            summary.failed += 1
            summary.add_error(exc)
            progress["failed"][url] = str(exc)[:200]
        if count % 10 == 0:
            save_progress()

    save_progress()
    outputs = write_all(records, out, str(spec.get("name", "records")), list(cfg.get("formats", ["jsonl", "csv"])))
    summary.outputs = outputs
    summary.outputs["run_summary"] = summary.save(out / "run_summary.json")
    summary.outputs["progress"] = str(progress_path)
    return summary
