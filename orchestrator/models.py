from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class StageResult:
    stage: str
    payload: dict[str, Any]
    status: str = "ok"
    needs_human_review: bool = False
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class WorkflowRun:
    run_id: str
    work_order_id: str
    status: str
    current_stage: str
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
