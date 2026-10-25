"""site2data_lib.recon.structure — BFS 爬行、URL 模式聚类与页面画像。"""
from __future__ import annotations

import re
from collections import Counter, deque
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse, urldefrag

from bs4 import BeautifulSoup

from ..core.http_client import HttpClient, FetchError
from ..core.logging_utils import get_logger
from ..core.models import PageInfo
from ..core.robots import RobotsGuard
from . import datanodes

log = get_logger("site2data.structure")

# URL 中的动态段：数字 ID、UUID、长 hex、slug 后缀
_ID_SEG_RE = re.compile(r"^(?:\d+|[0-9a-f]{8,}|[0-9a-f-]{20,}|.*[_-]\d+)$", re.IGNORECASE)


def canonicalize(url: str) -> str:
    """去 fragment、去默认端口，保留 query（query 影响内容时是有意义的维度）。"""
    full, _frag = urldefrag(url)
    p = urlparse(full)
    netloc = p.netloc
    if netloc.endswith(":80") and p.scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and p.scheme == "https":
        netloc = netloc[:-4]
    return p._replace(netloc=netloc).geturl()


def url_pattern(url: str) -> str:
    """把具体 URL 归纳为模式：/book/12345 → /book/{id}，保留结构维度。"""
    p = urlparse(url)
    segs = [s for s in p.path.split("/") if s]
    out_segs = []
    for s in segs:
        if _ID_SEG_RE.match(s):
            out_segs.append("{id}")
        else:
            out_segs.append(s.lower())
    pattern = "/" + "/".join(out_segs)
    if p.query:
        keys = sorted(k for k in re.split(r"[&;]", p.query) if k)
        qkeys = [k.split("=")[0] for k in keys]
        pattern += "?" + "&".join(qkeys)
    return pattern or "/"


def _classify_page(soup: BeautifulSoup, internal_links: int, text_len: int) -> str:
    """页面类型启发式判定。"""
    body_text = soup.get_text(" ", strip=True) if soup.body is not None else ""
    if _looks_like_login(body_text):
        return "login"
    if text_len < 80 and internal_links <= 2:
        # SPA / JS 壳：空壳 + 前端框架标记
        html_str = str(soup)[:20000].lower()
        if any(tok in html_str for tok in ("__next_data__", "ng-app", "data-reactroot", "id=\"root\"", "id=\"app\"")):
            return "js_shell"
        return "empty"
    if internal_links >= 15 and text_len < 5000:
        return "list"
    if internal_links <= 8 and text_len >= 500:
        return "detail"
    return "static"


def _looks_like_login(text: str) -> bool:
    low = text.lower()
    markers = ("登录后", "请登录", "sign in", "log in", "password", "注册账号", "忘记密码")
    hit = sum(1 for m in markers if m.lower() in low)
    return hit >= 2 and len(text) < 1500


def extract_links(soup: BeautifulSoup, base_url: str, seed_netloc: str) -> tuple[list[str], list[str]]:
    """返回 (内部链接, 外部链接)，均已 canonicalize。"""
    internal: list[str] = []
    external: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        full = canonicalize(urljoin(base_url, href))
        if full in seen:
            continue
        seen.add(full)
        if urlparse(full).netloc == seed_netloc:
            internal.append(full)
        else:
            external.append(full)
    return internal, external


def crawl(
    seed: str,
    client: HttpClient,
    robots: RobotsGuard,
    max_pages: int = 40,
    max_depth: int = 3,
    parser: str = "html.parser",
    extra_urls: list[str] | None = None,
) -> tuple[list[PageInfo], list[dict[str, Any]]]:
    """BFS 爬行。返回 (页面画像列表, 边列表)。

    边：source_pattern -> target_pattern，count 为链接条数（含未展开的目标）。
    """
    seed = canonicalize(seed)
    seed_netloc = urlparse(seed).netloc
    queue: deque[tuple[str, int]] = deque([(seed, 0)])
    for u in extra_urls or []:
        queue.append((canonicalize(u), 1))
    visited: set[str] = set()
    pages: list[PageInfo] = []
    edge_counter: Counter[tuple[str, str]] = Counter()

    while queue and len(pages) < max_pages:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        if not robots.allowed(url, session=client.session):
            log.info("robots 禁止，跳过 %s", url)
            continue

        try:
            resp = client.get(url)
        except FetchError as exc:
            log.warning("抓取失败 %s", exc)
            pages.append(PageInfo(url=url, status=0, depth=depth, pattern=url_pattern(url), signals={"error": str(exc)}))
            continue

        ctype = resp.headers.get("Content-Type", "")
        if "html" not in ctype and ctype:
            pages.append(PageInfo(url=url, status=resp.status_code, depth=depth, content_type=ctype, pattern=url_pattern(url)))
            continue

        soup = BeautifulSoup(resp.text, parser)
        internal, external = extract_links(soup, url, seed_netloc)
        text = unescape(soup.get_text(" ", strip=True))
        title = soup.title.get_text(strip=True) if soup.title else ""
        src_pat = url_pattern(url)
        for link in internal:
            edge_counter[(src_pat, url_pattern(link))] += 1

        info = PageInfo(
            url=url,
            status=resp.status_code,
            depth=depth,
            content_type=ctype,
            title=title[:200],
            text_len=len(text),
            n_internal_links=len(internal),
            n_external_links=len(external),
            pattern=src_pat,
        )
        # 记录反爬分析所需响应头指纹
        info.signals.update(
            {
                "server": resp.headers.get("Server", ""),
                "via": resp.headers.get("Via", ""),
                "retry_after": resp.headers.get("Retry-After", ""),
                "x_cache": resp.headers.get("X-Cache", ""),
            }
        )
        info.data_nodes = datanodes.extract(soup, url)
        info.page_kind = _classify_page(soup, len(internal), len(text))
        info.signals["has_json_ld"] = any(n.kind == "json_ld" for n in info.data_nodes)
        pages.append(info)

        if depth < max_depth:
            for link in internal:
                if link not in visited:
                    queue.append((link, depth + 1))

    edges = [{"source": s, "target": t, "count": c} for (s, t), c in edge_counter.most_common(200)]
    return pages, edges


def cluster_pages(pages: list[PageInfo]) -> list[dict[str, Any]]:
    """按 URL 模式聚类，聚合数据节点与字段猜测。"""
    buckets: dict[str, list[PageInfo]] = {}
    for p in pages:
        buckets.setdefault(p.pattern, []).append(p)

    clusters: list[dict[str, Any]] = []
    for pattern, group in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        kinds = Counter(p.page_kind for p in group)
        node_names: Counter[str] = Counter()
        for p in group:
            for n in p.data_nodes:
                node_names[f"{n.kind}:{n.name}"] += 1
        clusters.append(
            {
                "pattern": pattern,
                "count": len(group),
                "sample_urls": [p.url for p in group[:5]],
                "page_kinds": dict(kinds),
                "avg_text_len": round(sum(p.text_len for p in group) / len(group), 1),
                "data_nodes": [
                    {"kind": name.split(":", 1)[0], "name": name.split(":", 1)[1], "count": cnt}
                    for name, cnt in node_names.most_common(15)
                ],
                "fields_guess": [name.split(":", 1)[1] for name, _ in node_names.most_common(10)],
            }
        )
    return clusters
