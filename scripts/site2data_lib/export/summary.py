"""site2data_lib.export.summary — run 摘要（诚实汇报依据）。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class RunSummary:
    task: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str = ""
    total: int = 0
    success: int = 0
    skipped: int = 0
    failed: int = 0
    errors: dict[str, int] = field(default_factory=dict)  # 错误类型 -> 次数
    outputs: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def add_error(self, err: Exception | str) -> None:
        key = err.__class__.__name__ if isinstance(err, Exception) else str(err)[:60]
        self.errors[key] = self.errors.get(key, 0) + 1

    def finish(self) -> None:
        self.finished_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total": self.total,
            "success": self.success,
            "skipped": self.skipped,
            "failed": self.failed,
            "errors": self.errors,
            "outputs": self.outputs,
            "notes": self.notes,
        }

    def save(self, path: str | Path) -> str:
        self.finish()
        p = Path(path)
        if not p.parent.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return str(p)
