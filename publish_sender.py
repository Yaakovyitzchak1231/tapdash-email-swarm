#!/usr/bin/env python3
"""Poll draft_publish_payloads.jsonl and forward publish payloads to a webhook."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests

PIPELINE_DIR = Path(os.environ.get("PIPELINE_DIR", "/home/jacob/pipeline_out"))
STATE_PATH = PIPELINE_DIR / "publish_sender_state.json"
PUBLISH_FILE = PIPELINE_DIR / "draft_publish_payloads.jsonl"
WEBHOOK_URL = os.environ.get("PUBLISH_WEBHOOK_URL", "").strip()
INTERVAL_SECONDS = int(os.environ.get("PUBLISH_INTERVAL_SECONDS", "15"))


def _load_state() -> set[str]:
    if not STATE_PATH.exists():
        return set()
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return set(str(x) for x in data.get("sent_ids", []))
    except Exception:
        return set()


def _save_state(sent_ids: set[str]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"sent_ids": sorted(sent_ids)}, indent=2), encoding="utf-8"
    )


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
        except Exception:
            continue
    return rows


def send_payload(payload: dict[str, Any]) -> bool:
    if not WEBHOOK_URL:
        print("publish_sender: WEBHOOK_URL not set; skipping send")
        return False
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=5)
        if resp.status_code >= 400:
            print(f"publish_sender: webhook failed {resp.status_code} {resp.text[:200]}")
            return False
        return True
    except Exception as exc:
        print(f"publish_sender: exception {exc}")
        return False


def process_once() -> int:
    sent_ids = _load_state()
    count = 0
    for row in _iter_jsonl(PUBLISH_FILE):
        wo_id = str(row.get("work_order_id") or "").strip()
        if not wo_id or wo_id in sent_ids:
            continue
        if send_payload(row):
            sent_ids.add(wo_id)
            count += 1
    _save_state(sent_ids)
    return count


def main() -> None:
    print(
        f"publish_sender started; watching {PUBLISH_FILE} every {INTERVAL_SECONDS}s; webhook set={bool(WEBHOOK_URL)}"
    )
    while True:
        try:
            processed = process_once()
            if processed:
                print(f"publish_sender: forwarded {processed} payload(s)")
        except Exception as exc:
            print(f"publish_sender: loop error {exc}")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
