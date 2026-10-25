"""site2data_lib.core.config — 三层配置加载。

优先级（低 → 高）：
1. 代码内置 DEFAULTS
2. 技能根目录 site2data.config.json
3. 当前工作目录 site2data.config.json
4. 环境变量 SITE2DATA_*（少量高频键）
5. CLI 显式参数（由调用方用 override() 合并）
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    # 网络
    "user_agent": "site2data/1.0 (+https://example.invalid/site2data; polite crawler)",
    "timeout": 15.0,
    "max_retries": 3,
    "backoff_factor": 1.5,
    "min_delay_seconds": 1.0,  # 全局请求最小间隔（礼貌默认）
    "headers": {},
    "proxy": "",
    # recon
    "max_pages": 40,
    "max_depth": 3,
    "respect_robots": True,
    "parser": "html.parser",  # html.parser 零依赖；装有 lxml 时可改 "lxml"
    "probe_rate": False,  # 激进限速试探，默认关闭
    # harvest
    "harvest_max_items": 100,
    "harvest_delay_seconds": 1.0,
    # 输出
    "output_dir": "site2data_out",
    "formats": ["jsonl", "csv"],
}

_CONFIG_NAME = "site2data.config.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def load_config(skill_root: str | os.PathLike[str] | None = None, cwd: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """按层级合并配置，返回最终生效 dict。"""
    cfg = deepcopy(DEFAULTS)
    if skill_root is not None:
        cfg.update(_load_json(Path(skill_root) / _CONFIG_NAME))
    base = Path(cwd) if cwd is not None else Path.cwd()
    cfg.update(_load_json(base / _CONFIG_NAME))

    env_map = {
        "SITE2DATA_USER_AGENT": "user_agent",
        "SITE2DATA_TIMEOUT": "timeout",
        "SITE2DATA_MIN_DELAY": "min_delay_seconds",
        "SITE2DATA_PROXY": "proxy",
        "SITE2DATA_OUTPUT_DIR": "output_dir",
    }
    for env_key, cfg_key in env_map.items():
        val = os.environ.get(env_key)
        if val:
            cfg[cfg_key] = val

    cfg["timeout"] = float(cfg["timeout"])
    cfg["min_delay_seconds"] = float(cfg["min_delay_seconds"])
    cfg["max_retries"] = int(cfg["max_retries"])
    return cfg


def override(cfg: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """用 CLI 参数覆盖配置（忽略 None 值）。"""
    out = dict(cfg)
    for k, v in kwargs.items():
        if v is not None:
            out[k] = v
    return out
