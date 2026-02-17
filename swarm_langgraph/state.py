from __future__ import annotations

from typing import Any, TypedDict

from orchestrator.models import StageResult
from orchestrator.stages import StageContext


class SwarmState(TypedDict):
    ctx: StageContext
    last_result: StageResult | None
    halt: bool
    run_status: str
    error: str | None
    output: dict[str, Any]
