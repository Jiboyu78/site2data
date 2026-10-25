"""site2data_lib.core.models — 全链路共享数据模型。

所有模型均为 dataclass，支持 to_dict / from_dict 以便 JSON 持久化。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class DataNode:
    """页面中识别出的一个关键数据节点。"""

    kind: str  # json_ld | microdata | meta | og | table | form | content_block
    name: str  # 节点名，如 JSON-LD @type、meta 属性名、表头、表单字段
    selector: str = ""  # 建议提取选择器
    sample: str = ""  # 样例值（截断）
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PageInfo:
    """单个已抓取页面的画像。"""

    url: str
    status: int
    depth: int
    content_type: str = ""
    title: str = ""
    text_len: int = 0
    n_internal_links: int = 0
    n_external_links: int = 0
    page_kind: str = "unknown"  # list | detail | static | login | empty | js_shell | unknown
    pattern: str = ""  # URL 模式（聚类键）
    data_nodes: list[DataNode] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["data_nodes"] = [n.to_dict() for n in self.data_nodes]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PageInfo":
        nodes = [DataNode(**n) for n in d.get("data_nodes", [])]
        return cls(
            url=d["url"],
            status=d["status"],
            depth=d["depth"],
            content_type=d.get("content_type", ""),
            title=d.get("title", ""),
            text_len=d.get("text_len", 0),
            n_internal_links=d.get("n_internal_links", 0),
            n_external_links=d.get("n_external_links", 0),
            page_kind=d.get("page_kind", "unknown"),
            pattern=d.get("pattern", ""),
            data_nodes=nodes,
            signals=d.get("signals", {}),
        )


@dataclass
class Cluster:
    """按 URL 模式聚类得到的页面组。"""

    pattern: str
    count: int = 0
    sample_urls: list[str] = field(default_factory=list)
    page_kinds: dict[str, int] = field(default_factory=dict)
    avg_text_len: float = 0.0
    data_nodes: list[DataNode] = field(default_factory=list)
    fields_guess: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["data_nodes"] = [n.to_dict() for n in self.data_nodes]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Cluster":
        nodes = [DataNode(**n) for n in d.get("data_nodes", [])]
        return cls(
            pattern=d["pattern"],
            count=d.get("count", 0),
            sample_urls=d.get("sample_urls", []),
            page_kinds=d.get("page_kinds", {}),
            avg_text_len=d.get("avg_text_len", 0.0),
            data_nodes=nodes,
            fields_guess=d.get("fields_guess", []),
        )


@dataclass
class Finding:
    """反爬 / 合规 / 工程方面的单条发现。"""

    category: str  # waf | rate_limit | js_render | auth | robots | tls_fingerprint | challenge | perf
    severity: str  # low | medium | high
    evidence: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanResult:
    """recon 阶段的完整产物（可持久化为 scan_result.json）。"""

    seed: str
    scanned_at: str
    pages: list[PageInfo] = field(default_factory=list)
    clusters: list[Cluster] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)  # {source, target, count}
    findings: list[Finding] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)
    robots_summary: str = ""
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "scanned_at": self.scanned_at,
            "pages": [p.to_dict() for p in self.pages],
            "clusters": [c.to_dict() for c in self.clusters],
            "edges": self.edges,
            "findings": [f.to_dict() for f in self.findings],
            "sitemaps": self.sitemaps,
            "robots_summary": self.robots_summary,
            "stats": self.stats,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ScanResult":
        return cls(
            seed=d["seed"],
            scanned_at=d["scanned_at"],
            pages=[PageInfo.from_dict(p) for p in d.get("pages", [])],
            clusters=[Cluster.from_dict(c) for c in d.get("clusters", [])],
            edges=d.get("edges", []),
            findings=[Finding(**f) for f in d.get("findings", [])],
            sitemaps=d.get("sitemaps", []),
            robots_summary=d.get("robots_summary", ""),
            stats=d.get("stats", {}),
        )
