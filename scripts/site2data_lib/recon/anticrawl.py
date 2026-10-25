"""site2data_lib.recon.anticrawl — 反爬策略探测与建议。

原则：默认只做被动分析（响应头、页面指纹、状态码分布）。
激进试探（短时连发观察 429）仅在 probe_rate=True 时执行，且样本极小（2 次）。
"""
from __future__ import annotations

import time
from typing import Any

from ..core.http_client import HttpClient, FetchError
from ..core.logging_utils import get_logger
from ..core.models import Finding, PageInfo

log = get_logger("site2data.anticrawl")

_WAF_MARKERS = {
    "cloudflare": ("cf-ray", "cloudflare", "__cfduid", "cf_chl"),
    "akamai": ("akamai", "akamai-bot", "ak_bmsc"),
    "sucuri": ("sucuri", "x-sucuri"),
    "incapsula": ("incap_ses", "incapsula", "visid_incap"),
    "aws_waf": ("awswaf", "awselb", "x-amzn-requestid"),
    "fastly": ("x-served-by", "fastly"),
}

_CHALLENGE_WORDS = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "cf-challenge",
    "verify you are human",
    "安全验证",
    "验证码",
    "访问过于频繁",
    "访问受限",
    "请完成验证",
    "robot check",
    "are you a robot",
)

_JS_SHELL_MARKERS = ("__next_data__", "data-reactroot", "ng-app", 'id="root"', 'id="app"', "window.__initial_state__")


def analyze(
    pages: list[PageInfo],
    client: HttpClient,
    seed_url: str,
    probe_rate: bool = False,
    robots_delay: float | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_passive_findings(pages, client, robots_delay))
    if probe_rate:
        findings.extend(_rate_probe(seed_url, client))
    else:
        findings.append(
            Finding(
                category="rate_limit",
                severity="low",
                evidence="未执行主动限速试探（默认关闭）",
                recommendation="如需实测限流阈值，用 --probe-rate 显式开启（仅 2 次短时连发）",
            )
        )
    return findings


def _passive_findings(pages: list[PageInfo], client: HttpClient, robots_delay: float | None) -> list[Finding]:
    findings: list[Finding] = []
    statuses = [p.status for p in pages]
    n_403 = sum(1 for s in statuses if s == 403)
    n_429 = sum(1 for s in statuses if s == 429)
    n_0 = sum(1 for s in statuses if s == 0)
    n_200 = sum(1 for s in statuses if s == 200)

    # 状态码画像
    if n_429:
        findings.append(
            Finding(
                category="rate_limit",
                severity="high",
                evidence=f"{n_429}/{len(pages)} 个页面返回 429",
                recommendation="降低并发与频率（建议 min_delay_seconds≥1），启用退避重试；避免同一 IP 高频请求",
            )
        )
    if n_403:
        findings.append(
            Finding(
                category="waf",
                severity="high",
                evidence=f"{n_403}/{len(pages)} 个页面返回 403",
                recommendation="疑似 WAF/UA 拦截：更换 UA、补齐浏览器常见请求头；必要时走 Playwright 渲染通道；不要尝试绕过验证码",
            )
        )
    if n_0 and not n_200:
        findings.append(
            Finding(
                category="perf",
                severity="high",
                evidence=f"{n_0}/{len(pages)} 个页面网络层失败，无成功响应",
                recommendation="先检查网络/DNS/代理配置（site2data.config.json 的 proxy 键），再重试",
            )
        )

    # 响应头 / WAF 指纹
    servers = {p.signals.get("server", "") for p in pages if p.signals.get("server")}
    joined = " ".join(f"{p.signals.get('server', '')} {p.signals.get('via', '')}" for p in pages).lower()
    hit_wafs = [name for name, toks in _WAF_MARKERS.items() if any(t in joined for t in toks)]
    if hit_wafs:
        findings.append(
            Finding(
                category="waf",
                severity="medium",
                evidence=f"检测到防护层指纹: {', '.join(hit_wafs)}",
                recommendation="保持低频与稳定 UA/会话；优先找官方 API 或 RSS；避免触发 JS Challenge",
            )
        )
    if servers:
        findings.append(
            Finding(
                category="perf",
                severity="low",
                evidence=f"Server 头: {', '.join(sorted(servers)[:5])}",
                recommendation="记录指纹便于异常对比（headers 变化常是风控升级信号）",
            )
        )

    # JS 渲染需求
    js_shells = [p for p in pages if p.page_kind == "js_shell"]
    empty_pages = [p for p in pages if p.page_kind == "empty"]
    if js_shells or (len(empty_pages) >= max(2, len(pages) // 4) and pages):
        findings.append(
            Finding(
                category="js_render",
                severity="high",
                evidence=f"{len(js_shells)} 个 JS 壳页面 / {len(empty_pages)} 个空内容页面",
                recommendation="站点疑似 SPA：改用 Playwright 渲染通道（render=always），或定位其 JSON 数据接口（浏览器 DevTools Network 面板）",
            )
        )

    # 登录墙
    login_pages = [p for p in pages if p.page_kind == "login"]
    if login_pages:
        findings.append(
            Finding(
                category="auth",
                severity="medium",
                evidence=f"{len(login_pages)} 个页面疑似登录墙",
                recommendation="需要账号数据时由用户提供 Cookie/登录态；不绕过登录与人机验证",
            )
        )

    # robots crawl-delay
    if robots_delay:
        findings.append(
            Finding(
                category="robots",
                severity="medium",
                evidence=f"robots.txt 声明 Crawl-delay: {robots_delay}",
                recommendation=f"把 min_delay_seconds 提高到 ≥ {robots_delay}",
            )
        )

    # 速率限制响应头（从 signals 中读取，由爬行器记录）
    retry_after_pages = [p for p in pages if p.signals.get("retry_after")]
    if retry_after_pages:
        findings.append(
            Finding(
                category="rate_limit",
                severity="medium",
                evidence="响应携带 Retry-After 头",
                recommendation="客户端必须遵守 Retry-After（site2data http_client 已内置）",
            )
        )
    return findings


def _rate_probe(seed_url: str, client: HttpClient) -> list[Finding]:
    """小样本限速试探：连续 2 次请求观察 429。仅显式开启时执行。"""
    findings: list[Finding] = []
    codes: list[int] = []
    for i in range(2):
        try:
            resp = client.get(seed_url)
            codes.append(resp.status_code)
        except FetchError as exc:
            codes.append(exc.status or 0)
        time.sleep(0.2)
    if any(c == 429 for c in codes):
        findings.append(
            Finding(
                category="rate_limit",
                severity="high",
                evidence=f"限速试探（2 连发）触发 429，状态序列 {codes}",
                recommendation="站点对短时并发敏感：串行抓取 + min_delay_seconds≥1.5，必要时退避到 2-3s",
            )
        )
    else:
        findings.append(
            Finding(
                category="rate_limit",
                severity="low",
                evidence=f"限速试探（2 连发）未触发限流，状态序列 {codes}",
                recommendation="可从 1 req/s 起步，按稳定性逐步微调；仍建议保守",
            )
        )
    return findings
