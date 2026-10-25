#!/usr/bin/env python3
"""{{NAME}} — 由 site2data codegen 生成的独立爬虫（{{GENERATED_AT}}）。

用法：
    python {{FILENAME}} --limit 20 --out ./out        # 试爬 20 条
    python {{FILENAME}} --limit 0 --out ./out          # 全量（仍受 SPEC.limits.max_items 约束）
    python {{FILENAME}} --out ./out --resume           # 断点续跑（默认开启，--no-resume 关闭）

设计说明：
- 唯一外部依赖 requests + beautifulsoup4；
- 逐条异常隔离：单条失败只记录、不中断批次；
- 指数退避重试（429/5xx/网络错误），尊重 Retry-After；
- progress.json 断点续跑，run_summary.json 诚实汇报成败。

SPEC 由 site2data 从数据规格生成，字段含义见 references/spec-schema.md。
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("crawler")

# ---------------------------------------------------------------------------
# 数据规格（由 site2data 注入；修改抓取行为优先改这里或回 skill 重新 codegen）
# ---------------------------------------------------------------------------
SPEC: dict[str, Any] = json.loads({{SPEC_JSON_STR}})

# ---------------------------------------------------------------------------
# 错误类型（细分便于排障与摘要统计）
# ---------------------------------------------------------------------------


class CrawlError(RuntimeError):
    """爬虫基础异常。"""


class FetchError(CrawlError):
    """网络/HTTP 层失败。"""


class ParseError(CrawlError):
    """解析/抽取失败。"""


# ---------------------------------------------------------------------------
# 记录模型
# ---------------------------------------------------------------------------


@dataclass
class Record:
{{RECORD_FIELDS}}
    _url: str = ""
    _status: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 网络层：会话、限速、退避重试
# ---------------------------------------------------------------------------


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": SPEC.get("user_agent")
            or "site2data-crawler/1.0 (+polite; respects robots.txt)",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )
    session.headers.update(SPEC.get("headers") or {})
    if SPEC.get("cookies"):
        session.cookies.update(SPEC["cookies"])
    return session


def fetch(session: requests.Session, url: str, *, timeout: float = 15.0, max_retries: int = 3) -> requests.Response:
    """GET + 指数退避重试；仅 429/5xx/网络错误重试，4xx 直接抛出。"""
    delay = float((SPEC.get("limits") or {}).get("delay_seconds", 1.0))
    backoff = 1.5
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        if delay > 0:
            time.sleep(delay)
        try:
            resp = session.get(url, timeout=timeout)
        except requests.RequestException as exc:
            last_exc = exc
        else:
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                last_exc = FetchError(f"HTTP {resp.status_code}")
                retry_after = resp.headers.get("Retry-After")
                pause = backoff * (2**attempt)
                if retry_after and retry_after.isdigit():
                    pause = max(pause, float(retry_after))
                log.warning("第 %d 次失败 (%s)，%.1fs 后重试", attempt + 1, url, pause)
                time.sleep(pause)
                continue
            if resp.status_code != 200:
                raise FetchError(f"HTTP {resp.status_code}: {url}")
            return resp
        time.sleep(backoff * (2**attempt))
    raise FetchError(f"重试 {max_retries} 次后仍失败: {url} ({last_exc})")


def get_soup(session: requests.Session, url: str) -> BeautifulSoup:
    resp = fetch(session, url)
    parser = SPEC.get("parser") or "html.parser"
    try:
        return BeautifulSoup(resp.text, parser)
    except Exception as exc:  # bs4 对损坏 HTML 通常容错，此处兜底
        raise ParseError(f"解析失败 {url}: {exc}") from exc


# ---------------------------------------------------------------------------
# 字段抽取（与 site2data_lib.crawl.runner 语义一致）
# ---------------------------------------------------------------------------


def _transform(raw: Any, transform: str | None) -> Any:
    if raw is None or not transform:
        return raw
    t = str(transform)
    if t in ("strip", "join"):
        return re.sub(r"\s+", " ", str(raw)).strip()
    if t == "lower":
        return str(raw).lower()
    if t == "upper":
        return str(raw).upper()
    if t == "number":
        m = re.search(r"-?\d+(?:\.\d+)?", str(raw))
        return float(m.group(0)) if m and "." in m.group(0) else (int(m.group(0)) if m else None)
    m = re.match(r"regex:(.+)", t)
    if m:
        match = re.search(m.group(1), str(raw))
        if not match:
            return None
        return match.group(1) if match.groups() else match.group(0)
    return raw


def extract_field(soup: BeautifulSoup, fs: dict[str, Any]) -> Any:
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


def parse_detail(soup: BeautifulSoup, url: str, status: int = 200) -> Record:
    fields = (SPEC.get("detail") or {}).get("fields", {})
    values: dict[str, Any] = {}
    for name, fs in fields.items():
        try:
            values[name] = extract_field(soup, fs)
        except Exception as exc:
            log.debug("字段 %s 抽取异常 (%s): %s", name, url, exc)
            values[name] = None
    return Record(_url=url, _status=status, **values)


# ---------------------------------------------------------------------------
# URL 发现（list_detail / url_list / detail_only 三模式）
# ---------------------------------------------------------------------------


def list_page_urls() -> list[str]:
    lst = SPEC.get("list") or {}
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


def iter_detail_urls(session: requests.Session) -> Iterator[str]:
    mode = SPEC.get("mode", "list_detail")
    if mode in ("url_list", "detail_only"):
        yield from list_page_urls()
        return

    lst = SPEC.get("list") or {}
    link_sel = lst.get("link_selector")
    item_sel = lst.get("item_selector")
    link_attr = lst.get("link_attr", "href")
    seen: set[str] = set()
    for list_url in list_page_urls():
        try:
            soup = get_soup(session, list_url)
        except CrawlError as exc:
            log.warning("列表页失败: %s", exc)
            continue
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
                yield full


# ---------------------------------------------------------------------------
# 检查点与导出
# ---------------------------------------------------------------------------


def load_progress(path: Path) -> dict[str, Any]:
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.setdefault("done", [])
            data.setdefault("failed", {})
            return data
        except json.JSONDecodeError:
            log.warning("progress.json 损坏，重新开始")
    return {"done": [], "failed": {}}


def save_progress(path: Path, progress: dict[str, Any]) -> None:
    path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")


def write_outputs(records: list[dict[str, Any]], out_dir: Path, name: str) -> dict[str, str]:
    outputs: dict[str, str] = {}
    jsonl_path = out_dir / f"{name}.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    outputs["jsonl"] = str(jsonl_path)

    csv_path = out_dir / f"{name}.csv"
    if records:
        import csv as _csv

        fieldnames: list[str] = []
        for r in records:
            for k in r:
                if k not in fieldnames:
                    fieldnames.append(k)
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        outputs["csv"] = str(csv_path)
    return outputs


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = str(SPEC.get("name", "records"))
    session = build_session()

    progress = load_progress(out_dir / "progress.json") if args.resume else {"done": [], "failed": {}}
    done_set = set(progress["done"])

    limits = SPEC.get("limits") or {}
    cap = int(limits.get("max_items", 0)) or None
    if args.limit and args.limit > 0:
        cap = args.limit if cap is None else min(cap, args.limit)

    summary = {"task": f"crawl:{name}", "started_at": datetime.now(timezone.utc).isoformat(), "success": 0, "failed": 0, "skipped": 0, "errors": {}}
    records: list[dict[str, Any]] = []

    for i, url in enumerate(iter_detail_urls(session), start=1):
        if cap is not None and summary["success"] >= cap:
            break
        if url in done_set:
            summary["skipped"] += 1
            continue
        try:
            soup = get_soup(session, url)
            record = parse_detail(soup, url)
            records.append(record.to_dict())
            progress["done"].append(url)
            summary["success"] += 1
        except Exception as exc:  # noqa: BLE001 — 逐条隔离
            log.warning("失败 %s: %s", url, exc)
            summary["failed"] += 1
            key = exc.__class__.__name__
            summary["errors"][key] = summary["errors"].get(key, 0) + 1
            progress["failed"][url] = str(exc)[:200]
        if i % 10 == 0:
            save_progress(out_dir / "progress.json", progress)

    save_progress(out_dir / "progress.json", progress)
    summary["outputs"] = write_outputs(records, out_dir, name)
    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    (out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed"] == 0 else 1


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description="site2data 生成的爬虫")
    p.add_argument("--limit", type=int, default=0, help="最多抓取条数（0=按 SPEC 上限）")
    p.add_argument("--out", default="out", help="输出目录")
    p.add_argument("--resume", dest="resume", action="store_true", default=True, help="断点续跑（默认开启）")
    p.add_argument("--no-resume", dest="resume", action="store_false", help="忽略进度重新抓取")
    args = p.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
