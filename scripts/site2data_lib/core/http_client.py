"""site2data_lib.core.http_client — 带限速、重试与礼貌间隔的 HTTP 客户端。

设计要点（对齐 ecosystem 最佳实践）：
- 全局最小请求间隔（RateLimiter），默认 1s，可配置；
- 指数退避 + 抖动重试，尊重 Retry-After；
- 429/5xx/网络错误可重试，4xx（非 429）不重试；
- 所有请求经 RobotsGuard 门禁（由调用方决定是否启用）。
"""
from __future__ import annotations

import random
import time
from typing import Any

import requests

from .logging_utils import get_logger

log = get_logger("site2data.http")


class FetchError(RuntimeError):
    def __init__(self, url: str, message: str, status: int | None = None) -> None:
        super().__init__(f"[{status}] {url}: {message}")
        self.url = url
        self.status = status


class RateLimiter:
    """进程内全局最小间隔限速。"""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self._last = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        now = time.monotonic()
        delta = now - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()


class HttpClient:
    def __init__(
        self,
        user_agent: str,
        timeout: float = 15.0,
        max_retries: int = 3,
        backoff_factor: float = 1.5,
        min_delay_seconds: float = 1.0,
        headers: dict[str, str] | None = None,
        proxy: str = "",
    ) -> None:
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.backoff_factor = backoff_factor
        self.limiter = RateLimiter(min_delay_seconds)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
        if headers:
            self.session.headers.update(headers)
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "HttpClient":
        return cls(
            user_agent=cfg["user_agent"],
            timeout=float(cfg["timeout"]),
            max_retries=int(cfg["max_retries"]),
            backoff_factor=float(cfg["backoff_factor"]),
            min_delay_seconds=float(cfg["min_delay_seconds"]),
            headers=cfg.get("headers") or {},
            proxy=cfg.get("proxy") or "",
        )

    def get(self, url: str, allow_status: tuple[int, ...] = (), **kwargs: Any) -> requests.Response:
        """GET 请求；返回 Response（含错误状态），仅在网络错误/429/5xx 时重试后抛 FetchError。"""
        kwargs.setdefault("timeout", self.timeout)
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self.limiter.wait()
            try:
                resp = self.session.get(url, **kwargs)
            except requests.RequestException as exc:
                last_exc = exc
                self._sleep_backoff(attempt, url, f"网络错误 {exc.__class__.__name__}")
                continue

            if resp.status_code in allow_status:
                return resp
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                last_exc = FetchError(url, "服务端限流/错误", resp.status_code)
                retry_after = resp.headers.get("Retry-After")
                self._sleep_backoff(attempt, url, f"HTTP {resp.status_code}", retry_after=retry_after)
                continue
            return resp

        raise FetchError(url, f"重试 {self.max_retries} 次后仍失败：{last_exc}")

    def _sleep_backoff(self, attempt: int, url: str, reason: str, retry_after: str | None = None) -> None:
        if attempt >= self.max_retries:
            return
        delay = self.backoff_factor * (2**attempt) + random.uniform(0, 0.5)
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass
        log.warning("第 %d 次失败（%s, %s），%.1fs 后重试", attempt + 1, reason, url, delay)
        time.sleep(delay)
