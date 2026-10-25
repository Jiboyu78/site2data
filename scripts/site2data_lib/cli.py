"""site2data_lib.cli — 各命令实现（recon / harvest / codegen / validate / config）。

每个模块暴露 run(argv, skill_root) -> int，由 scripts/site2data.py 路由调用。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .core.config import load_config, override
from .core.logging_utils import get_logger
from .core.models import ScanResult
from .core.robots import RobotsGuard
from .core.http_client import HttpClient

log = get_logger("site2data.cli")


def _out_dir(cfg: dict[str, Any], explicit: str | None, host: str) -> Path:
    if explicit:
        out = Path(explicit)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = Path(cfg["output_dir"]) / f"{host}_{stamp}"
    if not out.exists():
        out.mkdir(parents=True, exist_ok=True)
    return out


def _host(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).netloc.replace(":", "_") or "site"


# ---------------------------------------------------------------- recon

def cmd_recon(argv: list[str], skill_root: Path) -> int:
    from .recon import anticrawl, report, sitemap, structure

    p = argparse.ArgumentParser(prog="site2data recon", description="站点结构侦察与可视化报告")
    p.add_argument("url", help="种子 URL")
    p.add_argument("--max-pages", type=int, default=None)
    p.add_argument("--max-depth", type=int, default=None)
    p.add_argument("--out", default=None, help="输出目录（默认 site2data_out/<host>_<时间戳>/）")
    p.add_argument("--probe-rate", action="store_true", help="执行小样本限速试探（显式开启）")
    p.add_argument("--no-robots", action="store_true", help="不遵守 robots.txt（仅在有权抓取时使用）")
    args = p.parse_args(argv)

    cfg = load_config(skill_root)
    cfg = override(
        cfg,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        probe_rate=args.probe_rate or None,
        respect_robots=False if args.no_robots else None,
    )
    client = HttpClient.from_config(cfg)
    robots = RobotsGuard(cfg["user_agent"], bool(cfg.get("respect_robots", True)))
    out = _out_dir(cfg, args.out, _host(args.url))

    log.info("侦察开始: %s", args.url)
    sitemaps = sitemap.discover_sitemaps(args.url, client)
    extra: list[str] = []
    for sm in sitemaps:
        extra.extend(sitemap.collect_urls(sm, client, limit=int(cfg["max_pages"])))

    pages, edges = structure.crawl(
        args.url,
        client,
        robots,
        max_pages=int(cfg["max_pages"]),
        max_depth=int(cfg["max_depth"]),
        parser=cfg.get("parser", "html.parser"),
        extra_urls=extra,
    )
    clusters_raw = structure.cluster_pages(pages)
    from .core.models import Cluster, DataNode

    def _to_nodes(items: list[Any]) -> list[DataNode]:
        out: list[DataNode] = []
        for n in items:
            if isinstance(n, DataNode):
                out.append(n)
            else:
                out.append(
                    DataNode(
                        kind=str(n.get("kind", "")),
                        name=str(n.get("name", "")),
                        note=f"出现 {n.get('count', 1)} 次",
                    )
                )
        return out

    clusters = []
    for c in clusters_raw:
        c = dict(c)
        c["data_nodes"] = _to_nodes(c.get("data_nodes", []))
        clusters.append(Cluster(**c))
    findings = anticrawl.analyze(
        pages,
        client,
        args.url,
        probe_rate=bool(cfg.get("probe_rate")),
        robots_delay=robots.crawl_delay(args.url),
    )

    robots_summary = "；".join(f"{k}: {v}" for k, v in robots.summaries().items())
    stats = {
        "页面样本": len(pages),
        "URL 模式数": len(clusters),
        "HTTP 200": sum(1 for x in pages if x.status == 200),
        "HTTP 4xx/5xx": sum(1 for x in pages if x.status >= 400),
        "网络失败": sum(1 for x in pages if x.status == 0),
        "页面类型分布": {k: sum(1 for x in pages if x.page_kind == k) for k in sorted({x.page_kind for x in pages})},
    }
    scan = ScanResult(
        seed=args.url,
        scanned_at=datetime.now().isoformat(timespec="seconds"),
        pages=pages,
        clusters=clusters,
        edges=edges,
        findings=findings,
        sitemaps=sitemaps,
        robots_summary=robots_summary,
        stats=stats,
    )
    outputs = report.generate_report(scan, out)

    print(json.dumps({"command": "recon", "out_dir": str(out), "outputs": outputs, "stats": stats,
                      "findings": [f.to_dict() for f in findings]}, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- harvest

def cmd_harvest(argv: list[str], skill_root: Path) -> int:
    from .crawl.runner import run_harvest
    from .crawl.spec import load_spec

    p = argparse.ArgumentParser(prog="site2data harvest", description="按数据规格执行抓取")
    p.add_argument("spec", help="spec 文件路径（.json 或 .yaml）")
    p.add_argument("--out", default=None, help="输出目录（默认 site2data_out/<spec名>_<时间戳>/）")
    args = p.parse_args(argv)

    cfg = load_config(skill_root)
    spec = load_spec(args.spec)
    out = _out_dir(cfg, args.out, str(spec.get("name", "harvest")))
    summary = run_harvest(spec, cfg, out)

    print(json.dumps({"command": "harvest", "out_dir": str(out), "summary": summary.to_dict()}, ensure_ascii=False))
    return 0 if summary.failed == 0 else 1


# ---------------------------------------------------------------- codegen

def cmd_codegen(argv: list[str], skill_root: Path) -> int:
    from .crawl.codegen import default_out_path, generate_crawler
    from .crawl.spec import load_spec

    p = argparse.ArgumentParser(prog="site2data codegen", description="由 spec 生成独立 Python 爬虫")
    p.add_argument("spec", help="spec 文件路径")
    p.add_argument("-o", "--out", default=None, help="生成的爬虫文件路径")
    args = p.parse_args(argv)

    spec = load_spec(args.spec)
    out_path = Path(args.out) if args.out else default_out_path(spec, Path.cwd() / "crawlers")
    path = generate_crawler(spec, out_path)

    print(json.dumps({
        "command": "codegen",
        "crawler": path,
        "usage": f"python {path} --limit 20 --out ./out",
        "deps": ["requests", "beautifulsoup4"],
    }, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- validate

def cmd_validate(argv: list[str], skill_root: Path) -> int:
    import json as _json

    from .crawl.spec import load_spec
    from .crawl.validate import validate_records

    p = argparse.ArgumentParser(prog="site2data validate", description="校验抓取结果质量")
    p.add_argument("records", help="records.jsonl 路径")
    p.add_argument("spec", help="spec 文件路径")
    args = p.parse_args(argv)

    spec = load_spec(args.spec)
    records = []
    for line in Path(args.records).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(_json.loads(line))
    report = validate_records(records, spec)
    print(_json.dumps({"command": "validate", "report": report}, ensure_ascii=False))
    return 0 if report.get("pass") else 1


# ---------------------------------------------------------------- config

def cmd_config(argv: list[str], skill_root: Path) -> int:
    cfg = load_config(skill_root)
    print(json.dumps({"command": "config", "config": cfg}, ensure_ascii=False, indent=2))
    return 0
