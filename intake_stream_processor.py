#!/usr/bin/env python3
"""Process inbound work orders into actionable vs rejected streams."""

from __future__ import annotations

import argparse
import json
import os
import time
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
SWARM_DIRECT_ENQUEUE_ENABLED = os.environ.get("SWARM_DIRECT_ENQUEUE_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SWARM_QUEUE_WORKER_ID = os.environ.get("SWARM_QUEUE_WORKER_ID", "intake-enqueue").strip()


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
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


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
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
        except Exception:
            continue
    return rows


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, separators=(",", ":")) + "\n")


def _build_swarm_queue():
    if not SWARM_DIRECT_ENQUEUE_ENABLED:
        return None
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return None
    try:
        from swarm_langgraph.queue import PostgresSwarmJobQueue

        return PostgresSwarmJobQueue(database_url=database_url, worker_id=SWARM_QUEUE_WORKER_ID)
    except Exception as exc:
        print(f"intake_stream_processor: failed to initialize swarm queue: {exc}")
        return None


def _dedupe_key(order: dict[str, Any]) -> str:
    event_id = str(order.get("email_event_id") or "").strip()
    if event_id:
        return f"event:{event_id}"
    return f"id:{order.get('id', '')}"


def _has_placeholder_mapping(order: dict[str, Any]) -> bool:
    sender = str(order.get("sender", "")).strip().lower()
    subject = str(order.get("subject", "")).strip().lower()
    event_id = str(order.get("email_event_id", "")).strip().lower()
    placeholders = {
        "sender email",
        "subject",
        "outlook message id",
    }
    return sender in placeholders or subject in placeholders or event_id in placeholders


def _is_noise(order: dict[str, Any]) -> bool:
    sender = str(order.get("sender", "")).strip().lower()
    subject = str(order.get("subject", "")).strip().lower()
    noise_senders = (
        "no-reply",
        "noreply",
        "do-not-reply",
        "donotreply",
        "notifications@",
    )
    noise_subjects = (
        "newsletter",
        "weekly digest",
        "unsubscribe",
        "your receipt",
        "promo",
        "webinar",
    )
    if any(token in sender for token in noise_senders):
        return True
    if any(token in subject for token in noise_subjects):
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
    swarm_queue = _build_swarm_queue()

    stats = {
        "processed": 0,
        "actionable": 0,
        "enqueued_swarm_jobs": 0,
        "enqueue_errors": 0,
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
            if swarm_queue is not None:
                try:
                    swarm_queue.enqueue(work_order_id=str(order.get("id", "")), payload=order)
                    stats["enqueued_swarm_jobs"] += 1
                except Exception as exc:
                    stats["enqueue_errors"] += 1
                    print(
                        f"intake_stream_processor: enqueue failed for work_order_id={order.get('id')}: {type(exc).__name__}"
                    )
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


def run_loop(interval_seconds: int) -> None:
    print(f"intake_stream_processor started: polling every {interval_seconds}s")
    while True:
        try:
            stats = process_once()
            if stats["actionable"] > 0:
                print(f"processed {stats['actionable']} new actionable work orders at {_utc_now()}")
        except Exception as exc:
            print(f"Error in intake loop: {exc}")
        time.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Process inbound work orders.")
    parser.add_argument(
        "--store",
        type=Path,
        default=WORK_ORDER_STORE,
        help="Path to work orders JSONL file",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=None,
        help="Polling interval in seconds for daemon mode",
    )
    args = parser.parse_args()

    if args.interval_seconds:
        run_loop(args.interval_seconds)
    else:
        stats = process_once(work_order_store=args.store)
        print(json.dumps(stats, separators=(",", ":")))


if __name__ == "__main__":
    main()



if __name__ == "__main__":
    main()
