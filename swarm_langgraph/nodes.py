from __future__ import annotations

from typing import Any

from orchestrator.stages import (
    ContextStage,
    DraftStage,
    FactStage,
    PolicyStage,
    PublishStage,
    QAStage,
    TierStage,
    ToneStage,
)

from .monday_agents import monday_coordinator_agent
from .state import SwarmState


class SwarmNodes:
    """Specialist swarm nodes with deterministic handoff order."""

    def __init__(self) -> None:
        self._tier = TierStage()
        self._context = ContextStage()
        self._draft = DraftStage()
        self._tone = ToneStage()
        self._fact = FactStage()
        self._qa = QAStage()
        self._policy = PolicyStage()
        self._publish = PublishStage()

    def tier_agent(self, state: SwarmState) -> dict[str, Any]:
        result = self._tier.run(state["ctx"])
        return {"last_result": result}

    def context_agent(self, state: SwarmState) -> dict[str, Any]:
        result = self._context.run(state["ctx"])
        return {"last_result": result}

    def monday_coordinator_agent(self, state: SwarmState) -> dict[str, Any]:
        ctx = state["ctx"]
        monday_context = monday_coordinator_agent(ctx.work_order)
        ctx.state["monday_context"] = monday_context

        base_context = ctx.state.get("context")
        if isinstance(base_context, dict):
            context_obj = base_context.setdefault("context", {})
            if isinstance(context_obj, dict):
                crm_enriched_fields = context_obj.setdefault("crm_enriched_fields", {})
                if isinstance(crm_enriched_fields, dict):
                    crm_enriched_fields.update(monday_context.get("crm_context", {}))
                context_obj["monday_swarm"] = monday_context
        return {"last_result": None}

    def draft_agent(self, state: SwarmState) -> dict[str, Any]:
        result = self._draft.run(state["ctx"])
        return {"last_result": result}

    def tone_agent(self, state: SwarmState) -> dict[str, Any]:
        result = self._tone.run(state["ctx"])
        return {"last_result": result}

    def fact_agent(self, state: SwarmState) -> dict[str, Any]:
        result = self._fact.run(state["ctx"])
        return {"last_result": result}

    def qa_agent(self, state: SwarmState) -> dict[str, Any]:
        result = self._qa.run(state["ctx"])
        return {"last_result": result}

    def policy_agent(self, state: SwarmState) -> dict[str, Any]:
        result = self._policy.run(state["ctx"])
        halt = bool(result.needs_human_review)
        run_status = "needs_human_review" if halt else "running"
        return {"last_result": result, "halt": halt, "run_status": run_status}

    def publish_agent(self, state: SwarmState) -> dict[str, Any]:
        result = self._publish.run(state["ctx"])
        return {
            "last_result": result,
            "output": {"publish": state["ctx"].state.get("publish")},
            "run_status": state.get("run_status", "completed"),
        }
