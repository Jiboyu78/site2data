"""site2data_lib.recon.report — 可视化报告生成（Markdown/Mermaid + 自包含 HTML/SVG）。

产物：
- report.md   人读 + Mermaid 站点架构图
- report.html 自包含、内联 SVG 架构图（浅色主题，离线可看）
- scan_result.json 机器可读（由调用方写入）
"""
from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..core.models import ScanResult

_SEV_ORDER = {"high": 0, "medium": 1, "low": 2}


def generate_report(scan: ScanResult, out_dir: str | Path) -> dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True) if not out.exists() else None
    md_path = out / "report.md"
    html_path = out / "report.html"
    json_path = out / "scan_result.json"

    json_path.write_text(json.dumps(scan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(scan), encoding="utf-8")
    html_path.write_text(render_html(scan), encoding="utf-8")
    return {"markdown": str(md_path), "html": str(html_path), "json": str(json_path)}


# ---------------------------------------------------------------- Markdown

def render_markdown(scan: ScanResult) -> str:
    lines: list[str] = []
    a = lines.append
    a(f"# 站点结构侦察报告：{scan.seed}")
    a("")
    a(f"> 扫描时间：{scan.scanned_at} ｜ 页面样本：{len(scan.pages)} ｜ URL 模式：{len(scan.clusters)}")
    a("")
    a("## 1. 概览")
    a("")
    stats = scan.stats or {}
    a("| 指标 | 值 |")
    a("|---|---|")
    for k, v in stats.items():
        a(f"| {k} | {v} |")
    if scan.robots_summary:
        a(f"| robots.txt | {scan.robots_summary} |")
    if scan.sitemaps:
        a(f"| sitemaps | {'；'.join(scan.sitemaps[:5])} |")
    a("")

    a("## 2. 站点架构图")
    a("")
    a("```mermaid")
    a("graph TD")
    ids = {c.pattern: f"P{i}" for i, c in enumerate(scan.clusters)}
    for c in scan.clusters:
        label = f"{c.pattern}<br/>{c.count} 页 · {max(c.page_kinds, key=c.page_kinds.get, default='?')}"
        a(f'    {ids[c.pattern]}["{label}"]')
    drawn = 0
    for e in scan.edges:
        s, t = e.get("source"), e.get("target")
        if s in ids and t in ids and s != t and drawn < 60:
            a(f"    {ids[s]} -->|{e.get('count', 1)}| {ids[t]}")
            drawn += 1
    a("```")
    a("")
    a("## 3. URL 模式聚类（页面层级与内容分布）")
    a("")
    a("| URL 模式 | 页面数 | 主要类型 | 平均文本长度 | 数据节点（Top） |")
    a("|---|---|---|---|---|")
    for c in scan.clusters:
        kind = max(c.page_kinds, key=c.page_kinds.get, default="?")
        nodes = "、".join(f"{n.kind}:{n.name}" for n in c.data_nodes[:4])
        a(f"| `{c.pattern}` | {c.count} | {kind} | {c.avg_text_len} | {nodes} |")
    a("")

    a("## 4. 关键数据节点")
    a("")
    a("（按聚类列出可用于抽取的结构化节点；`fields_guess` 是字段候选）")
    a("")
    for c in scan.clusters:
        if not c.data_nodes:
            continue
        a(f"### `{c.pattern}`")
        a("")
        a("| 节点类型 | 名称 | 建议选择器 / 样例 | 备注 |")
        a("|---|---|---|---|")
        for n in c.data_nodes[:10]:
            sel = n.selector or n.sample or "-"
            a(f"| {n.kind} | {html.escape(str(n.name))} | {html.escape(str(sel))} | {html.escape(str(n.note))} |")
        if c.fields_guess:
            a("")
            a(f"字段候选：{', '.join(c.fields_guess)}")
        a("")

    a("## 5. 反爬策略分析")
    a("")
    if not scan.findings:
        a("未发现明显反爬信号（仅基于被动观察）。")
    else:
        a("| 严重度 | 类别 | 证据 | 建议 |")
        a("|---|---|---|---|")
        for f in sorted(scan.findings, key=lambda x: _SEV_ORDER.get(x.severity, 9)):
            a(f"| {f.severity} | {f.category} | {html.escape(f.evidence)} | {html.escape(f.recommendation)} |")
    a("")

    a("## 6. 抓取策略建议")
    a("")
    a(_strategy_suggestions(scan))
    a("")
    a("---")
    a("*由 site2data 生成。合规提醒：遵守 robots.txt 与站点条款，不绕过验证码/付费墙，控制抓取频率。*")
    return "\n".join(lines)


def _strategy_suggestions(scan: ScanResult) -> str:
    tips = []
    sev_high = [f for f in scan.findings if f.severity == "high"]
    if any(f.category == "js_render" for f in sev_high):
        tips.append("- **渲染**：SPA/JS 壳页面居多，抓取阶段直接用 Playwright 通道（或优先定位 JSON 接口）。")
    else:
        tips.append("- **渲染**：静态 HTML 可解析，requests + BeautifulSoup 通道即可。")
    if any(f.category == "rate_limit" for f in scan.findings):
        tips.append("- **频率**：串行抓取，`min_delay_seconds` ≥ 1.5，重试带指数退避（site2data 默认已内置）。")
    else:
        tips.append("- **频率**：建议保持 1 req/s 礼貌速率起步。")
    if any(f.category == "auth" for f in scan.findings):
        tips.append("- **登录**：部分内容需登录态，由用户提供 Cookie；不要尝试绕过。")
    detail_clusters = [c for c in scan.clusters if max(c.page_kinds, key=c.page_kinds.get, default="") == "detail"]
    list_clusters = [c for c in scan.clusters if max(c.page_kinds, key=c.page_kinds.get, default="") == "list"]
    if list_clusters and detail_clusters:
        tips.append(
            f"- **结构**：检测到列表页×{len(list_clusters)} + 详情页×{len(detail_clusters)} 的层级，"
            f"建议 `list_detail` 模式抓取（列表发现链接 → 详情抽字段）。"
        )
    elif detail_clusters:
        tips.append("- **结构**：以详情页为主，可先从 sitemap/导航收集详情 URL，再用 `url_list`/`detail_only` 模式。")
    return "\n".join(tips)


# ---------------------------------------------------------------- HTML

def render_html(scan: ScanResult) -> str:
    esc = html.escape
    rows_cluster = "".join(
        f"<tr><td><code>{esc(c.pattern)}</code></td><td>{c.count}</td>"
        f"<td>{esc(max(c.page_kinds, key=c.page_kinds.get, default='?'))}</td>"
        f"<td>{c.avg_text_len}</td><td>{esc(', '.join(c.fields_guess[:6]))}</td></tr>"
        for c in scan.clusters
    )
    findings_sorted = sorted(scan.findings, key=lambda x: _SEV_ORDER.get(x.severity, 9))
    rows_findings = "".join(
        f'<tr><td><span class="sev sev-{esc(f.severity)}">{esc(f.severity)}</span></td><td>{esc(f.category)}</td>'
        f"<td>{esc(f.evidence)}</td><td>{esc(f.recommendation)}</td></tr>"
        for f in findings_sorted
    )
    node_html = ""
    for c in scan.clusters:
        if not c.data_nodes:
            continue
        items = "".join(
            f"<li><b>{esc(str(n.name))}</b> <span class='muted'>({esc(n.kind)})</span> "
            f"{esc(n.selector or n.sample or '')}</li>"
            for n in c.data_nodes[:8]
        )
        node_html += f"<h3><code>{esc(c.pattern)}</code></h3><ul class='nodes'>{items}</ul>"

    svg = _arch_svg(scan)
    stats_rows = "".join(f"<tr><td>{esc(str(k))}</td><td>{esc(str(v))}</td></tr>" for k, v in (scan.stats or {}).items())

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>站点结构侦察报告 · {esc(scan.seed)}</title>
<style>
  :root {{ --bg:#ffffff; --fg:#1f2328; --muted:#656d76; --line:#d0d7de; --accent:#0969da; --card:#f6f8fa; --high:#cf222e; --medium:#9a6700; --low:#1a7f37; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; color:var(--fg); background:var(--bg); line-height:1.6; }}
  header {{ padding:28px 32px; border-bottom:1px solid var(--line); background:var(--card); }}
  h1 {{ margin:0 0 6px; font-size:22px; }}
  h2 {{ font-size:18px; margin:32px 0 12px; padding-bottom:6px; border-bottom:1px solid var(--line); }}
  h3 {{ font-size:15px; margin:18px 0 8px; }}
  main {{ padding:8px 32px 48px; max-width:1100px; margin:0 auto; }}
  .muted {{ color:var(--muted); font-size:12px; }}
  table {{ border-collapse:collapse; width:100%; margin:10px 0 18px; font-size:13px; background:#fff; }}
  th,td {{ border:1px solid var(--line); padding:7px 10px; text-align:left; vertical-align:top; }}
  th {{ background:var(--card); }}
  code {{ background:var(--card); padding:1px 5px; border-radius:4px; font-size:12px; }}
  .sev {{ padding:1px 8px; border-radius:10px; font-size:11px; color:#fff; }}
  .sev-high {{ background:var(--high); }} .sev-medium {{ background:var(--medium); }} .sev-low {{ background:var(--low); }}
  .arch {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; overflow-x:auto; }}
  ul.nodes {{ margin:6px 0 14px; padding-left:20px; }}
  ul.nodes li {{ margin:3px 0; }}
  .footer {{ margin-top:40px; padding-top:12px; border-top:1px solid var(--line); color:var(--muted); font-size:12px; }}
</style>
</head>
<body>
<header>
  <h1>站点结构侦察报告</h1>
  <div class="muted">种子 URL：{esc(scan.seed)} ｜ 扫描时间：{esc(scan.scanned_at)} ｜
  页面样本：{len(scan.pages)} ｜ URL 模式：{len(scan.clusters)}</div>
</header>
<main>
  <h2>1. 概览</h2>
  <table><tr><th>指标</th><th>值</th></tr>{stats_rows}</table>

  <h2>2. 站点架构图</h2>
  <div class="arch">{svg}</div>

  <h2>3. URL 模式聚类（页面层级与内容分布）</h2>
  <table>
    <tr><th>URL 模式</th><th>页面数</th><th>主要类型</th><th>平均文本长度</th><th>字段候选</th></tr>
    {rows_cluster}
  </table>

  <h2>4. 关键数据节点</h2>
  {node_html}

  <h2>5. 反爬策略分析</h2>
  <table>
    <tr><th>严重度</th><th>类别</th><th>证据</th><th>建议</th></tr>
    {rows_findings}
  </table>

  <h2>6. 抓取策略建议</h2>
  <pre class="arch" style="white-space:pre-wrap">{esc(_strategy_suggestions(scan))}</pre>

  <div class="footer">由 site2data 生成 ｜ 合规提醒：遵守 robots.txt 与站点条款，不绕过验证码/付费墙，控制抓取频率。</div>
</main>
</body>
</html>"""


def _arch_svg(scan: ScanResult) -> str:
    """按路径深度分层的简单分层布局架构图（自包含 SVG）。"""
    clusters = scan.clusters[:24]
    if not clusters:
        return '<p class="muted">（无聚类数据）</p>'

    depth_of: dict[str, int] = {}
    for c in clusters:
        depth_of[c.pattern] = min(c.pattern.strip("/").count("/"), 6)
    cols: dict[int, list[Any]] = defaultdict(list)
    for c in clusters:
        cols[depth_of[c.pattern]].append(c)

    col_w, box_w, box_h, pad_y = 300, 240, 52, 24
    height = max(220, max(len(v) for v in cols.values()) * (box_h + pad_y) + 40)
    width = max(680, len(cols) * col_w + 60)

    pos: dict[str, tuple[float, float]] = {}
    for ci, (depth, group) in enumerate(sorted(cols.items())):
        x = 30 + ci * col_w
        for ri, c in enumerate(group):
            pos[c.pattern] = (x, 20 + ri * (box_h + pad_y))

    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">']
    parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="#f6f8fa"/>')
    for e in scan.edges:
        s, t = e.get("source"), e.get("target")
        if s in pos and t in pos and s != t:
            x1, y1 = pos[s]
            x2, y2 = pos[t]
            mx = (x1 + box_w + x2) / 2
            parts.append(
                f'<path d="M {x1 + box_w} {y1 + box_h / 2} C {mx} {y1 + box_h / 2}, {mx} {y2 + box_h / 2}, {x2} {y2 + box_h / 2}" '
                f'fill="none" stroke="#8c959f" stroke-width="1.2" opacity="0.7"/>'
            )
    for c in clusters:
        x, y = pos[c.pattern]
        kind = max(c.page_kinds, key=c.page_kinds.get, default="?")
        color = {"list": "#0969da", "detail": "#1a7f37", "js_shell": "#cf222e", "login": "#9a6700", "static": "#656d76", "empty": "#656d76"}.get(kind, "#656d76")
        parts.append(f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" rx="8" fill="#ffffff" stroke="{color}" stroke-width="1.6"/>')
        parts.append(f'<rect x="{x}" y="{y}" width="6" height="{box_h}" rx="3" fill="{color}"/>')
        label = c.pattern if len(c.pattern) <= 30 else c.pattern[:29] + "…"
        parts.append(f'<text x="{x + 14}" y="{y + 20}" font-size="12" fill="#1f2328">{html.escape(label)}</text>')
        parts.append(f'<text x="{x + 14}" y="{y + 38}" font-size="11" fill="#656d76">{html.escape(kind)} · {c.count} 页</text>')
    parts.append("</svg>")
    return "".join(parts)
