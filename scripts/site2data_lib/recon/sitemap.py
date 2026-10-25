"""site2data_lib.recon.sitemap — sitemap.xml 发现与 URL 枚举。"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

from ..core.http_client import HttpClient
from ..core.logging_utils import get_logger

log = get_logger("site2data.sitemap")

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_SITEMAP_RE = re.compile(r"<sitemap>\s*.*?<loc>\s*([^<\s]+)\s*</loc>.*?</sitemap>", re.IGNORECASE | re.DOTALL)


def discover_sitemaps(seed_url: str, client: HttpClient) -> list[str]:
    """从 /robots.txt 与 /sitemap.xml 发现 sitemap 地址（去重、限量）。"""
    p = urlparse(seed_url)
    origin = f"{p.scheme}://{p.netloc}"
    found: list[str] = []
    try:
        resp = client.get(origin + "/robots.txt")
        if resp.status_code == 200:
            for line in resp.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    sm = line.split(":", 1)[1].strip()
                    if sm and sm not in found:
                        found.append(sm)
    except Exception as exc:
        log.debug("robots.txt 解析 sitemap 失败: %s", exc)

    for fallback in (origin + "/sitemap.xml", origin + "/sitemap_index.xml"):
        if fallback not in found:
            found.append(fallback)
    return found[:5]


def collect_urls(sitemap_url: str, client: HttpClient, limit: int = 500) -> list[str]:
    """拉取 sitemap（含 sitemapindex 一层展开），返回 URL 列表。"""
    urls: list[str] = []
    try:
        resp = client.get(sitemap_url)
        if resp.status_code != 200:
            log.info("sitemap %s -> HTTP %s", sitemap_url, resp.status_code)
            return []
        text = resp.text
    except Exception as exc:
        log.info("sitemap 拉取失败 %s: %s", sitemap_url, exc)
        return []

    submaps = _SITEMAP_RE.findall(text)
    if submaps and len(urls) < limit:
        for sm in submaps[:10]:
            urls.extend(collect_urls(sm, client, limit=limit - len(urls)))
            if len(urls) >= limit:
                break
    urls.extend(_LOC_RE.findall(text))
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        u = u.strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out[:limit]


def parse_xml_urls(text: str) -> list[str]:
    """纯解析（不联网），供测试与离线使用。"""
    try:
        root = ET.fromstring(text)
        return [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]
    except ET.ParseError:
        return _LOC_RE.findall(text)
