"""site2data_lib.core.robots — robots.txt 合规门禁。

硬约定：respect_robots=True 时，任何被 robots.txt 禁止的 URL 不发起请求。
"""
from __future__ import annotations

import urllib.robotparser
from urllib.parse import urlparse

import requests


class RobotsGuard:
    def __init__(self, user_agent: str, respect: bool = True) -> None:
        self.user_agent = user_agent
        self.respect = respect
        self._parsers: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._summaries: dict[str, str] = {}

    def _host_key(self, url: str) -> str:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"

    def _ensure(self, url: str, session: requests.Session | None = None) -> urllib.robotparser.RobotFileParser | None:
        host = self._host_key(url)
        if host in self._parsers:
            return self._parsers[host]
        rp = urllib.robotparser.RobotFileParser()
        robots_url = host + "/robots.txt"
        try:
            if session is not None:
                resp = session.get(robots_url, timeout=10)
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                    self._summaries[host] = _summarize(resp.text)
                else:
                    rp.parse([])
                    self._summaries[host] = f"robots.txt HTTP {resp.status_code}，视为无限制"
            else:
                rp.set_url(robots_url)
                rp.read()
                self._summaries[host] = "(已读取)"
        except Exception as exc:  # 网络失败时按无限制处理，但在摘要中如实记录
            rp.parse([])
            self._summaries[host] = f"robots.txt 获取失败（{exc.__class__.__name__}），按无限制处理"
        self._parsers[host] = rp
        return rp

    def allowed(self, url: str, session: requests.Session | None = None) -> bool:
        if not self.respect:
            return True
        rp = self._ensure(url, session)
        if rp is None:
            return True
        return rp.can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        if not self.respect:
            return None
        rp = self._ensure(url)
        if rp is None:
            return None
        try:
            delay = rp.crawl_delay(self.user_agent)
            return float(delay) if delay is not None else None
        except Exception:
            return None

    def summaries(self) -> dict[str, str]:
        return dict(self._summaries)


def _summarize(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    disallow = [ln for ln in lines if ln.lower().startswith("disallow")]
    delays = [ln for ln in lines if ln.lower().startswith("crawl-delay")]
    parts = [f"规则行 {len(lines)} 条，disallow {len(disallow)} 条"]
    if delays:
        parts.append("含 " + ", ".join(delays[:3]))
    return "；".join(parts)
