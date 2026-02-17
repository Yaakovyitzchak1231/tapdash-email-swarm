from __future__ import annotations

from typing import Any

from orchestrator.models import StageResult
from orchestrator.stages import StageContext
from orchestrator.store import RunStore

from .graph import build_swarm_graph
from .nodes import SwarmNodes
from .state import SwarmState


class SwarmSupervisor:
    """Supervisor that coordinates specialist swarm agents via graph execution."""

    def __init__(self, store: RunStore, nodes: SwarmNodes | None = None) -> None:
        self.store = store
        self.nodes = nodes or SwarmNodes()
        self.graph = build_swarm_graph(self.nodes)

    def run_work_order(self, work_order: dict[str, Any]) -> dict[str, Any]:
        work_order_id = str(work_order.get("id", "")).strip()
        if not work_order_id:
            raise ValueError("work_order.id is required")

        run = self.store.start_run(work_order_id=work_order_id)
        ctx = StageContext(work_order=work_order)
        state: SwarmState = {
            "ctx": ctx,
            "last_result": None,
            "halt": False,
            "run_status": "running",
            "error": None,
            "output": {},
        }

        # Execute with either compiled LangGraph graph or fallback graph.
        final_state = self.graph.invoke(state)

        # Persist deterministic stage events from ctx.state.
        self._persist_ctx_state(run.run_id, work_order_id, ctx)

        final_status = final_state.get("run_status") or "completed"
        if final_status == "running":
            final_status = "completed"
        final_stage = "publish" if "publish" in ctx.state else "policy"
        self.store.finish_run(run.run_id, status=final_status, current_stage=final_stage)
        return {
            "run_id": run.run_id,
            "work_order_id": work_order_id,
            "status": final_status,
            "current_stage": final_stage,
            "publish": ctx.state.get("publish"),
        }

    def _persist_ctx_state(self, run_id: str, work_order_id: str, ctx: StageContext) -> None:
        stage_order = ["context", "monday_context", "draft", "qa", "policy", "publish"]
        for stage in stage_order:
            if stage not in ctx.state:
                continue
            payload = ctx.state[stage]
            needs_human_review = bool(payload.get("needs_human_review")) if isinstance(payload, dict) else False
            if stage == "policy" and isinstance(payload, dict):
                needs_human_review = bool(payload.get("needs_human_review"))
            if stage == "qa" and isinstance(payload, dict):
                needs_human_review = payload.get("qa_status") != "pass"
            result = StageResult(
                stage=stage,
                payload=payload if isinstance(payload, dict) else {"value": payload},
                needs_human_review=needs_human_review,
            )
            self.store.append_event(run_id, result)
            self.store.persist_artifact(run_id, work_order_id, result)
