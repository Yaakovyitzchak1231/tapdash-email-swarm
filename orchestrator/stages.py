from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from escalation_policy import classify_text, load_policy
from pipeline_daemon import (
    context_agent,
    draft_agent,
    fact_agent,
    policy_agent,
    publish_agent,
    qa_agent,
    tone_agent,
)

from .models import StageResult


@dataclass
class StageContext:
    work_order: dict[str, Any]
    state: dict[str, Any] = field(default_factory=dict)


class Stage(Protocol):
    name: str

    def run(self, ctx: StageContext) -> StageResult: ...


class TierStage:
    name = "tier"

    def run(self, ctx: StageContext) -> StageResult:
        policy = load_policy()
        decision = classify_text(
            f"{ctx.work_order.get('subject', '')} {ctx.work_order.get('sender', '')}",
            policy,
        )
        payload = {"tier": decision.tier, "reason": decision.reason}
        ctx.state["decision"] = payload
        return StageResult(stage=self.name, payload=payload)


class ContextStage:
    name = "context"

    def run(self, ctx: StageContext) -> StageResult:
        row = context_agent(ctx.work_order)
        ctx.state["context"] = row
        return StageResult(stage=self.name, payload=row)


class DraftStage:
    name = "draft"

    def run(self, ctx: StageContext) -> StageResult:
        decision = ctx.state["decision"]
        row = draft_agent(
            work_order=ctx.work_order,
            context=ctx.state["context"],
            policy_tier=decision["tier"],
        )
        ctx.state["draft"] = row
        return StageResult(stage=self.name, payload=row)


class ToneStage:
    name = "tone"

    def run(self, ctx: StageContext) -> StageResult:
        row = tone_agent(ctx.state["draft"])
        ctx.state["tone"] = row
        return StageResult(stage=self.name, payload=row)


class FactStage:
    name = "fact"

    def run(self, ctx: StageContext) -> StageResult:
        decision = ctx.state["decision"]
        row = fact_agent(
            draft=ctx.state["tone"],
            decision_tier=decision["tier"],
            wo_id=str(ctx.work_order.get("id")),
        )
        ctx.state["fact"] = row
        return StageResult(stage=self.name, payload=row)


class QAStage:
    name = "qa"

    def run(self, ctx: StageContext) -> StageResult:
        row = qa_agent(
            work_order=ctx.work_order,
            draft=ctx.state["draft"],
            tone_checked=ctx.state["tone"],
            fact_checked=ctx.state["fact"],
        )
        ctx.state["qa"] = row
        needs_human_review = row.get("qa_status") != "pass"
        return StageResult(
            stage=self.name,
            payload=row,
            needs_human_review=needs_human_review,
        )


class PolicyStage:
    name = "policy"

    def run(self, ctx: StageContext) -> StageResult:
        decision = ctx.state["decision"]
        row = policy_agent(
            work_order=ctx.work_order,
            decision_tier=decision["tier"],
            decision_reason=decision["reason"],
            draft=ctx.state["draft"],
            qa_result=ctx.state["qa"],
            fact_checked=ctx.state["fact"],
        )
        ctx.state["policy"] = row
        return StageResult(
            stage=self.name,
            payload=row,
            needs_human_review=bool(row.get("needs_human_review")),
        )


class PublishStage:
    name = "publish"

    def run(self, ctx: StageContext) -> StageResult:
        row = publish_agent(
            work_order=ctx.work_order,
            draft=ctx.state["draft"],
            tone_checked=ctx.state["tone"],
            qa_result=ctx.state["qa"],
            fact_checked=ctx.state["fact"],
            policy_result=ctx.state["policy"],
        )
        payload = row or {"status": "skipped", "reason": "needs_human_review"}
        ctx.state["publish"] = payload
        return StageResult(stage=self.name, payload=payload)


def default_legacy_stages() -> list[Stage]:
    return [
        TierStage(),
        ContextStage(),
        DraftStage(),
        ToneStage(),
        FactStage(),
        QAStage(),
        PolicyStage(),
        PublishStage(),
    ]
