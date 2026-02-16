#!/usr/bin/env python3
"""Process inbound work orders into actionable vs rejected streams."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORK_ORDER_STORE = Path(os.environ.get("WORK_ORDER_STORE", "/home/jacob/work_orders.jsonl"))
STATE_DIR = Path(os.environ.get("INTAKE_STATE_DIR", "/home/jacob/intake_state"))
PROCESSED_KEYS_PATH = STATE_DIR / "processed_keys.json"
ACTIONABLE_PATH = STATE_DIR / "actionable_work_orders.jsonl"
REJECTED_PATH = STATE_DIR / "rejected_work_orders.jsonl"
STATS_PATH = STATE_DIR / "intake_stats.json"

NOISE_SENDER_TOKENS = (
    "no-reply",
    "noreply",
    "do-not-reply",
    "donotreply",
    "notifications@",
)
NOISE_SUBJECT_TOKENS = (
    "newsletter",
    "weekly digest",
    "unsubscribe",
    "your receipt",
    "promo",
    "webinar",
)
PLACEHOLDER_VALUES = {
    "sender email",
    "subject",
    "outlook message id",
}


@dataclass
class IntakeDecision:
    status: str
    reason: str
    key: str


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, separators=(",", ":")) + "\n")


def _dedupe_key(order: dict[str, Any]) -> str:
    event_id = str(order.get("email_event_id") or "").strip()
    if event_id:
        return f"event:{event_id}"
    return f"id:{order.get('id', '')}"


def _has_placeholder_mapping(order: dict[str, Any]) -> bool:
    sender = str(order.get("sender", "")).strip().lower()
    subject = str(order.get("subject", "")).strip().lower()
    event_id = str(order.get("email_event_id", "")).strip().lower()
    return sender in PLACEHOLDER_VALUES or subject in PLACEHOLDER_VALUES or event_id in PLACEHOLDER_VALUES


def _is_noise(order: dict[str, Any]) -> bool:
    sender = str(order.get("sender", "")).strip().lower()
    subject = str(order.get("subject", "")).strip().lower()
    if any(token in sender for token in NOISE_SENDER_TOKENS):
        return True
    if any(token in subject for token in NOISE_SUBJECT_TOKENS):
        return True
    return False


def decide(order: dict[str, Any], seen_keys: set[str]) -> IntakeDecision:
    key = _dedupe_key(order)
    if key in seen_keys:
        return IntakeDecision(status="rejected", reason="duplicate", key=key)
    if _has_placeholder_mapping(order):
        return IntakeDecision(status="rejected", reason="invalid_mapping", key=key)
    if _is_noise(order):
        return IntakeDecision(status="rejected", reason="likely_noise", key=key)
    return IntakeDecision(status="actionable", reason="accepted", key=key)


def process_once(work_order_store: Path = WORK_ORDER_STORE) -> dict[str, int]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    seen = set(_load_json(PROCESSED_KEYS_PATH, {"keys": []}).get("keys", []))

    stats = {
        "processed": 0,
        "actionable": 0,
        "rejected_duplicate": 0,
        "rejected_invalid_mapping": 0,
        "rejected_likely_noise": 0,
    }

    for order in _iter_jsonl(work_order_store):
        stats["processed"] += 1
        decision = decide(order, seen)

        record = {
            "processed_at": _utc_now(),
            "decision": decision.status,
            "reason": decision.reason,
            "dedupe_key": decision.key,
            "work_order": order,
        }

        if decision.status == "actionable":
            stats["actionable"] += 1
            _append_jsonl(ACTIONABLE_PATH, record)
        elif decision.reason == "duplicate":
            stats["rejected_duplicate"] += 1
            _append_jsonl(REJECTED_PATH, record)
        elif decision.reason == "invalid_mapping":
            stats["rejected_invalid_mapping"] += 1
            _append_jsonl(REJECTED_PATH, record)
        else:
            stats["rejected_likely_noise"] += 1
            _append_jsonl(REJECTED_PATH, record)

        seen.add(decision.key)

    _save_json(PROCESSED_KEYS_PATH, {"keys": sorted(seen)})
    _save_json(STATS_PATH, {"updated_at": _utc_now(), "stats": stats})
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Process inbound work orders.")
    parser.add_argument(
        "--store",
        type=Path,
        default=WORK_ORDER_STORE,
        help="Path to work orders JSONL file",
    )
    args = parser.parse_args()

    stats = process_once(work_order_store=args.store)
    print(json.dumps(stats, separators=(",", ":")))


if __name__ == "__main__":
    main()
