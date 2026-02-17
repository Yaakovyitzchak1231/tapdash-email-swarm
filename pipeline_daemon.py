#!/usr/bin/env python3
"""Auto-run pipeline from actionable work orders."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from escalation_policy import classify_text, load_policy
from precedent_memory import lookup_precedent

INTAKE_STATE_DIR = Path(os.environ.get("INTAKE_STATE_DIR", "/home/jacob/intake_state"))
ACTIONABLE_PATH = INTAKE_STATE_DIR / "actionable_work_orders.jsonl"
PIPELINE_DIR = Path(os.environ.get("PIPELINE_DIR", "/home/jacob/pipeline_out"))
STATE_PATH = PIPELINE_DIR / "daemon_state.json"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_TIMEOUT_SECONDS = int(os.environ.get("OPENAI_TIMEOUT_SECONDS", "25"))
DRAFT_MIN_CONFIDENCE = float(os.environ.get("DRAFT_MIN_CONFIDENCE", "0.65"))
AUTO_SEND_ENABLED = os.environ.get("AUTO_SEND_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
SIGNATURE_BLOCK = os.environ.get("SIGNATURE_BLOCK", "Best,\nYaakov\nyaakov@tapdash.co")


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"processed_work_order_ids": []}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def context_agent(work_order: dict[str, Any]) -> dict[str, Any]:
    return {
        "work_order_id": work_order.get("id"),
        "sender": work_order.get("sender", ""),
        "subject": work_order.get("subject", ""),
        "labels": work_order.get("labels", []),
        "work_order": work_order,
        "context": {
            "master_status": "partial",
            "critical_gaps": [
                "No per-contact CRM join in current local batch.",
                "No full Outlook thread history attached for this event.",
            ],
            "outlook_summary": {
                "thread_count": 0,
                "message_count": 0,
                "participants": [work_order.get("sender", "")],
                "latest_timestamp": work_order.get("created_at"),
            },
            "crm_enriched_fields": {},
            "indexed_sources": [
                "email_thread_normalizer/marketing_docs/about.txt",
                "email_thread_normalizer/marketing_docs/pricing.txt",
            ],
        },
        "assembled_at": _now(),
    }


def _build_template_draft(work_order: dict[str, Any], policy_tier: str) -> dict[str, Any]:
    sender = work_order.get("sender", "there")
    subject = work_order.get("subject", "")
    if policy_tier == "A":
        body = (
            f"Hi {sender},\n\n"
            "Thanks for reaching out. We received your message. "
            "Please share two or three time windows this week and we will confirm one.\n\n"
            f"{SIGNATURE_BLOCK}"
        )
    else:
        body = (
            f"Hi {sender},\n\n"
            "Thanks for reaching out. We received your message and can help with next steps. "
            "Share your goal and preferred timeline, and we will route this to the right team.\n\n"
            f"{SIGNATURE_BLOCK}"
        )
    return {
        "work_order_id": work_order.get("id"),
        "to": sender,
        "draft_subject": f"Re: {subject}",
        "draft_body": body,
        "status": "draft",
        "generated_at": _now(),
        "draft_agent": "template_fallback",
        "confidence": 0.8,
        "citations": [],
        "rationale": "Fallback template used because LLM drafting was unavailable.",
    }


def _extract_json_string(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _clean_confidence(value: Any, default: float = 0.5) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if numeric < 0.0:
        return 0.0
    if numeric > 1.0:
        return 1.0
    return numeric


def _openai_draft(work_order: dict[str, Any], context: dict[str, Any], policy_tier: str) -> dict[str, Any]:
    sender = work_order.get("sender", "there")
    subject = work_order.get("subject", "")
    messages = [
        {
            "role": "system",
            "content": (
                "You draft concise business email replies. "
                "Tone rules: professional, concise, friendly undertone, clear CTA, no em dashes. "
                "Never use placeholders like [Your Name], [Company], or bracketed template fields. "
                f"Always end with this exact signature block: '{SIGNATURE_BLOCK}'. "
                "Return only JSON with keys: draft_subject, draft_body, confidence, rationale, citations."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "policy_tier": policy_tier,
                    "sender": sender,
                    "subject": subject,
                    "labels": work_order.get("labels", []),
                    "message_body": work_order.get("body", ""),
                    "context": context.get("context", {}),
                },
                separators=(",", ":"),
            ),
        },
    ]
    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "email_draft",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "draft_subject": {"type": "string"},
                        "draft_body": {"type": "string"},
                        "confidence": {"type": "number"},
                        "rationale": {"type": "string"},
                        "citations": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["draft_subject", "draft_body", "confidence", "rationale", "citations"],
                    "additionalProperties": False,
                },
            },
        },
    }
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=OPENAI_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    parsed = response.json()
    choices = parsed.get("choices", [])
    if not choices:
        raise RuntimeError("No choices returned by OpenAI.")
    message = choices[0].get("message", {})
    raw_content = _extract_json_string(message.get("content", ""))
    if not raw_content:
        raise RuntimeError("No completion content returned by OpenAI.")
    draft_json = json.loads(raw_content)
    draft_subject = str(draft_json.get("draft_subject") or f"Re: {subject}")
    draft_body = str(draft_json.get("draft_body") or "")
    if not draft_body.strip():
        raise RuntimeError("OpenAI returned an empty draft body.")
    return {
        "work_order_id": work_order.get("id"),
        "to": sender,
        "draft_subject": draft_subject,
        "draft_body": draft_body,
        "status": "draft",
        "generated_at": _now(),
        "draft_agent": "openai",
        "confidence": _clean_confidence(draft_json.get("confidence"), default=0.6),
        "citations": draft_json.get("citations", []),
        "rationale": str(draft_json.get("rationale", "")),
    }


def draft_agent(work_order: dict[str, Any], context: dict[str, Any], policy_tier: str) -> dict[str, Any]:
    if not OPENAI_API_KEY:
        return _build_template_draft(work_order, policy_tier=policy_tier)
    try:
        return _openai_draft(work_order=work_order, context=context, policy_tier=policy_tier)
    except Exception as exc:  # noqa: BLE001
        fallback = _build_template_draft(work_order, policy_tier=policy_tier)
        fallback["rationale"] = f"Fallback template used after LLM draft error: {type(exc).__name__}."
        return fallback


def tone_agent(draft: dict[str, Any]) -> dict[str, Any]:
    revised = str(draft.get("draft_body", ""))
    had_em_dash = "—" in revised
    if had_em_dash:
        revised = revised.replace("—", "-")
    tone_notes = "Professional, concise, friendly undertone. No em-dashes."
    if had_em_dash:
        tone_notes += " Replaced em dash with hyphen."
    tone_checked = dict(draft)
    tone_checked.update(
        {
            "tone_ok": True,
            "tone_notes": tone_notes,
            "revised_draft": revised,
        }
    )
    return tone_checked


def fact_agent(draft: dict[str, Any], decision_tier: str, wo_id: str) -> dict[str, Any]:
    fact_checked = dict(draft)
    if decision_tier == "C":
        fact_checked.update(
            {
                "fact_status": "needs_review",
                "fact_notes": [
                    "High-risk claim category detected by policy tier C.",
                    "Human review required for pricing/legal/security/compliance claims.",
                ],
                "citations": draft.get("citations", []),
            }
        )
        return fact_checked
    fact_checked.update(
        {
            "fact_status": "pass",
            "fact_notes": ["No high-risk factual claims detected by tier policy."],
            "citations": draft.get("citations", [])
            or [{"source": "work_orders.jsonl", "evidence": f"work_order_id={wo_id}"}],
        }
    )
    return fact_checked


def qa_agent(draft: dict[str, Any], tone_checked: dict[str, Any], fact_checked: dict[str, Any]) -> dict[str, Any]:
    confidence = _clean_confidence(draft.get("confidence"), default=0.5)
    tone_ok = bool(tone_checked.get("tone_ok"))
    fact_ok = fact_checked.get("fact_status") == "pass"
    qa_pass = tone_ok and confidence >= 0.5
    qa_score = int(round((confidence * 100)))
    qa_reasons = ["style_compliant"] if tone_ok else ["style_violation"]
    if fact_ok:
        qa_reasons.append("fact_gate_pass")
    else:
        qa_reasons.append("fact_gate_needs_review")
    qa_result = dict(draft)
    qa_result.update(
        {
            "qa_score": qa_score,
            "qa_pass": qa_pass,
            "qa_status": "pass" if qa_pass else "needs_review",
            "qa_reasons": qa_reasons,
            "qa_source_input": str(PIPELINE_DIR / "drafts.jsonl"),
            "qa_fallback_used": draft.get("draft_agent") != "openai",
        }
    )
    return qa_result


def policy_agent(
    work_order: dict[str, Any],
    decision_tier: str,
    decision_reason: str,
    draft: dict[str, Any],
    qa_result: dict[str, Any],
    fact_checked: dict[str, Any],
) -> dict[str, Any]:
    precedent = lookup_precedent(
        sender=work_order.get("sender", ""),
        labels=work_order.get("labels", []),
        tier=decision_tier,
    )
    has_auto_precedent = precedent.found and precedent.decision in {"approve", "auto_publish"}
    draft_confidence = _clean_confidence(draft.get("confidence"), default=0.5)
    needs_human_review = (
        decision_tier == "C"
        or fact_checked["fact_status"] != "pass"
        or not qa_result["qa_pass"]
        or draft_confidence < DRAFT_MIN_CONFIDENCE
    )
    if decision_tier in {"A", "B"} and has_auto_precedent and draft_confidence >= DRAFT_MIN_CONFIDENCE:
        needs_human_review = False
    return {
        "needs_human_review": needs_human_review,
        "reason": (
            "tier_or_fact_or_qa_or_confidence"
            if needs_human_review
            else "auto_publish_allowed"
        ),
        "confidence": "high" if not needs_human_review else "medium",
        "policy_tier": decision_tier,
        "policy_reason": decision_reason,
        "precedent_key": precedent.key,
        "precedent_found": precedent.found,
        "precedent_confidence": precedent.confidence,
        "draft_confidence": draft_confidence,
        "detected_at": _now(),
    }


def publish_agent(
    work_order: dict[str, Any],
    draft: dict[str, Any],
    tone_checked: dict[str, Any],
    qa_result: dict[str, Any],
    fact_checked: dict[str, Any],
    policy_result: dict[str, Any],
) -> dict[str, Any] | None:
    if policy_result["needs_human_review"]:
        return None
    publish_row = {
        "work_order_id": str(work_order.get("id")),
        "to": draft["to"],
        "subject": draft["draft_subject"],
        "body": tone_checked["revised_draft"],
        "provenance": {
            "policy_tier": policy_result["policy_tier"],
            "qa_status": qa_result["qa_status"],
            "fact_status": fact_checked["fact_status"],
            "draft_agent": draft.get("draft_agent"),
            "draft_confidence": policy_result["draft_confidence"],
            "auto_send_enabled": AUTO_SEND_ENABLED,
        },
        "created_at": _now(),
        "send": AUTO_SEND_ENABLED,
    }
    for key in (
        "message_id",
        "conversation_id",
        "from_addr",
        "to_addrs",
        "cc_addrs",
        "in_reply_to",
        "references",
        "email_event_id",
    ):
        if key in work_order:
            publish_row[key] = work_order.get(key)
    return publish_row


def process_work_order(work_order: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
    wo_id = str(work_order.get("id"))

    context = context_agent(work_order)
    _append_jsonl(PIPELINE_DIR / "context_packs.jsonl", context)

    decision = classify_text(
        f"{work_order.get('subject','')} {work_order.get('sender','')}",
        policy,
    )
    draft = draft_agent(work_order, context=context, policy_tier=decision.tier)
    # Threading metadata passthrough if present on the work order
    for key in (
        "message_id",
        "conversation_id",
        "from_addr",
        "to_addrs",
        "cc_addrs",
        "in_reply_to",
        "references",
        "email_event_id",
    ):
        if key in work_order:
            draft[key] = work_order.get(key)
    _append_jsonl(PIPELINE_DIR / "drafts.jsonl", draft)

    tone_checked = tone_agent(draft)
    _append_jsonl(PIPELINE_DIR / "tone_checked.jsonl", tone_checked)

    fact_checked = fact_agent(
        draft=tone_checked,
        decision_tier=decision.tier,
        wo_id=wo_id,
    )
    _append_jsonl(PIPELINE_DIR / "fact_checked.jsonl", fact_checked)

    qa_result = qa_agent(
        draft=draft,
        tone_checked=tone_checked,
        fact_checked=fact_checked,
    )
    _append_jsonl(PIPELINE_DIR / "qa_results.jsonl", qa_result)

    policy_result = policy_agent(
        work_order=work_order,
        decision_tier=decision.tier,
        decision_reason=decision.reason,
        draft=draft,
        qa_result=qa_result,
        fact_checked=fact_checked,
    )
    escalation_row = dict(policy_result)
    escalation_row.update(
        {
        "work_order_id": wo_id,
            "agent_trace": [
                "context_agent",
                "draft_agent",
                "tone_agent",
                "fact_agent",
                "qa_agent",
                "policy_agent",
            ],
        }
    )
    _append_jsonl(PIPELINE_DIR / "escalations.jsonl", escalation_row)

    publish_row = publish_agent(
        work_order=work_order,
        draft=draft,
        tone_checked=tone_checked,
        qa_result=qa_result,
        fact_checked=fact_checked,
        policy_result=policy_result,
    )
    if publish_row:
        _append_jsonl(PIPELINE_DIR / "draft_publish_payloads.jsonl", publish_row)

    return {
        "work_order_id": wo_id,
        "policy_tier": decision.tier,
        "needs_human_review": policy_result["needs_human_review"],
    }


def run_once(actionable_path: Path = ACTIONABLE_PATH) -> int:
    policy = load_policy()
    state = _load_state()
    processed_ids = set(str(x) for x in state.get("processed_work_order_ids", []))
    processed_now = 0

    for record in _read_jsonl(actionable_path):
        work_order = record.get("work_order") if isinstance(record, dict) else None
        if not isinstance(work_order, dict):
            continue
        wo_id = str(work_order.get("id", "")).strip()
        if not wo_id or wo_id in processed_ids:
            continue
        process_work_order(work_order=work_order, policy=policy)
        processed_ids.add(wo_id)
        processed_now += 1

    state["processed_work_order_ids"] = sorted(processed_ids)
    state["updated_at"] = _now()
    _save_state(state)
    return processed_now


def run_loop(interval_seconds: int) -> None:
    print(f"pipeline_daemon started: polling every {interval_seconds}s")
    while True:
        count = run_once()
        if count:
            print(f"processed {count} new work_order(s) at {_now()}")
        time.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run pipeline daemon.")
    parser.add_argument("--once", action="store_true", help="Process one pass and exit")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=10,
        help="Polling interval in seconds for daemon mode",
    )
    args = parser.parse_args()

    if args.once:
        count = run_once()
        print(json.dumps({"processed_new": count}, separators=(",", ":")))
        return
    run_loop(interval_seconds=args.interval_seconds)


if __name__ == "__main__":
    main()
