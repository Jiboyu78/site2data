"""site2data_lib.recon.datanodes — 关键数据节点识别。

识别：JSON-LD、Microdata、meta/OG、表格、表单、主内容块。
产出 DataNode 列表，为"抓哪些字段"提供候选。
"""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from ..core.models import DataNode

_SAMPLE_MAX = 120


def _sample(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:_SAMPLE_MAX]


def extract(soup: BeautifulSoup, url: str) -> list[DataNode]:
    nodes: list[DataNode] = []
    nodes.extend(_json_ld(soup))
    nodes.extend(_microdata(soup))
    nodes.extend(_meta_tags(soup))
    nodes.extend(_tables(soup))
    nodes.extend(_forms(soup))
    nodes.extend(_content_blocks(soup))
    return nodes


def _json_ld(soup: BeautifulSoup) -> list[DataNode]:
    out: list[DataNode] = []
    for script in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            out.append(DataNode(kind="json_ld", name="(解析失败)", note="JSON-LD 非法 JSON", sample=_sample(raw)))
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            t = item.get("@type", "Thing")
            types = t if isinstance(t, list) else [t]
            keys = [k for k in item.keys() if not k.startswith("@")]
            out.append(
                DataNode(
                    kind="json_ld",
                    name=",".join(str(x) for x in types),
                    selector='script[type="application/ld+json"]',
                    sample=_sample(", ".join(keys[:8])),
                    note=f"字段键: {', '.join(keys[:10])}",
                )
            )
    return out


def _microdata(soup: BeautifulSoup) -> list[DataNode]:
    out: list[DataNode] = []
    for el in soup.find_all(attrs={"itemscope": True})[:20]:
        t = el.get("itemtype") or el.get("itemprop") or "microdata"
        t = str(t).rsplit("/", 1)[-1]
        props = [str(p.get("itemprop", "")) for p in el.find_all(attrs={"itemprop": True})[:10]]
        out.append(DataNode(kind="microdata", name=t, selector="[itemscope]", sample=_sample(",".join(props))))
    return out


def _meta_tags(soup: BeautifulSoup) -> list[DataNode]:
    out: list[DataNode] = []
    for m in soup.find_all("meta"):
        key = m.get("name") or m.get("property") or m.get("itemprop")
        content = m.get("content")
        if not key or content is None:
            continue
        key_l = str(key).lower()
        kind = "og" if key_l.startswith(("og:", "twitter:")) else "meta"
        if kind == "og" or key_l in {"description", "keywords", "author", "title", "article:published_time", "price", "product-id"}:
            out.append(DataNode(kind=kind, name=str(key), selector=f'meta[name="{key}"], meta[property="{key}"]', sample=_sample(str(content))))
    return out[:30]


def _tables(soup: BeautifulSoup) -> list[DataNode]:
    out: list[DataNode] = []
    for i, table in enumerate(soup.find_all("table")[:5]):
        headers = [th.get_text(" ", strip=True) for th in table.find_all("th")[:12]]
        rows = len(table.find_all("tr"))
        out.append(
            DataNode(
                kind="table",
                name=f"table#{i}",
                selector=f"table:nth-of-type({i + 1})",
                sample=_sample(" | ".join(headers)),
                note=f"{rows} 行",
            )
        )
    return out


def _forms(soup: BeautifulSoup) -> list[DataNode]:
    out: list[DataNode] = []
    for i, form in enumerate(soup.find_all("form")[:5]):
        fields = [str(inp.get("name") or inp.get("id") or inp.get("type")) for inp in form.find_all(["input", "select", "textarea"])[:12]]
        action = form.get("action", "")
        out.append(
            DataNode(
                kind="form",
                name=f"form#{i}",
                selector=f"form:nth-of-type({i + 1})",
                sample=_sample(",".join(f for f in fields if f)),
                note=f"action={_sample(str(action))}",
            )
        )
    return out


def _content_blocks(soup: BeautifulSoup) -> list[DataNode]:
    out: list[DataNode] = []
    for sel in ("article", "main", "#content", ".content", ".article", ".post", "[role=main]"):
        els = soup.select(sel)
        if not els:
            continue
        el = els[0]
        text = el.get_text(" ", strip=True)
        if len(text) < 100:
            continue
        out.append(DataNode(kind="content_block", name=sel, selector=sel, sample=_sample(text), note=f"约 {len(text)} 字符"))
    return out
