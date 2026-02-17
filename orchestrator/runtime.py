from __future__ import annotations

from typing import Any

from .stages import Stage, StageContext
from .store import RunStore


class DurableOrchestrator:
    """Queue-friendly orchestrator with explicit stage event logging."""

    def __init__(self, store: RunStore, stages: list[Stage]) -> None:
        self.store = store
        self.stages = stages

    def run_work_order(self, work_order: dict[str, Any]) -> dict[str, Any]:
        work_order_id = str(work_order.get("id", "")).strip()
        if not work_order_id:
            raise ValueError("work_order.id is required")

        run = self.store.start_run(work_order_id=work_order_id)
        ctx = StageContext(work_order=work_order)
        final_status = "completed"
        final_stage = "start"
        needs_human_review = False

        for stage in self.stages:
            result = stage.run(ctx)
            final_stage = stage.name
            self.store.append_event(run.run_id, result)
            self.store.persist_artifact(run.run_id, work_order_id, result)
            if result.needs_human_review and stage.name in {"qa", "policy"}:
                needs_human_review = True

        if needs_human_review:
            final_status = "needs_human_review"

        self.store.finish_run(run.run_id, status=final_status, current_stage=final_stage)
        return {
            "run_id": run.run_id,
            "work_order_id": work_order_id,
            "status": final_status,
            "current_stage": final_stage,
            "publish": ctx.state.get("publish"),
        }
