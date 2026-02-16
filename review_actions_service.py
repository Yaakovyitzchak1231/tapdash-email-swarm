#!/usr/bin/env python3
"""Human review actions for escalated drafts."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from precedent_memory import append_precedent

PORT = int(os.environ.get("REVIEW_PORT", "8090"))

PIPELINE_DIR = Path(os.environ.get("PIPELINE_DIR", "/home/jacob/pipeline_out"))
WORK_ORDER_STORE = Path(os.environ.get("WORK_ORDER_STORE", "/home/jacob/work_orders.jsonl"))
REVIEW_ACTIONS_PATH = PIPELINE_DIR / "review_actions.jsonl"
ESCALATIONS_PATH = PIPELINE_DIR / "escalations.jsonl"
PUBLISH_PATH = PIPELINE_DIR / "draft_publish_payloads.jsonl"
TONE_PATH = PIPELINE_DIR / "tone_checked.jsonl"

ALLOWED_ACTIONS = {"approve", "edit_approve", "reject"}


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")


def _latest_by_work_order(path: Path, work_order_id: str) -> dict[str, Any] | None:
    for row in reversed(_read_jsonl(path)):
        if str(row.get("work_order_id", "")) == work_order_id:
            return row
    return None


def _work_order_for_id(work_order_id: str) -> dict[str, Any] | None:
    for row in reversed(_read_jsonl(WORK_ORDER_STORE)):
        if str(row.get("id", "")) == work_order_id:
            return row
    return None


def _publish_exists(work_order_id: str) -> bool:
    return any(str(row.get("work_order_id", "")) == work_order_id for row in _read_jsonl(PUBLISH_PATH))


def _build_publish_payload(work_order_id: str, edited_body: str | None) -> dict[str, Any] | None:
    tone = _latest_by_work_order(TONE_PATH, work_order_id)
    if not tone:
        return None
    body = edited_body if edited_body else str(tone.get("revised_draft") or tone.get("draft_body") or "")
    return {
        "work_order_id": work_order_id,
        "to": tone.get("to", ""),
        "subject": tone.get("draft_subject", ""),
        "body": body,
        "provenance": {
            "source": "human_review_action",
            "tone_source": str(TONE_PATH),
        },
        "created_at": _now(),
    }


def _decision_for_action(action: str) -> str:
    if action in {"approve", "edit_approve"}:
        return "approve"
    return "reject"


def apply_review_action(payload: dict[str, Any]) -> dict[str, Any]:
    work_order_id = str(payload.get("work_order_id", "")).strip()
    action = str(payload.get("action", "")).strip()
    reviewer = str(payload.get("reviewer", "human")).strip()
    edited_body = payload.get("edited_body")
    if edited_body is not None:
        edited_body = str(edited_body)

    if not work_order_id:
        raise ValueError("work_order_id is required")
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"action must be one of: {', '.join(sorted(ALLOWED_ACTIONS))}")
    if action == "edit_approve" and not edited_body:
        raise ValueError("edited_body is required for edit_approve")

    escalation = _latest_by_work_order(ESCALATIONS_PATH, work_order_id)
    if not escalation:
        raise ValueError("no escalation found for work_order_id")

    work_order = _work_order_for_id(work_order_id) or {}
    tier = str(escalation.get("policy_tier", "B"))
    labels = work_order.get("labels", []) if isinstance(work_order.get("labels", []), list) else []
    sender = str(work_order.get("sender", ""))
    decision = _decision_for_action(action)
    append_precedent(sender=sender, labels=labels, tier=tier, decision=decision)

    action_row = {
        "work_order_id": work_order_id,
        "action": action,
        "reviewer": reviewer,
        "edited_body": edited_body,
        "created_at": _now(),
        "policy_tier": tier,
        "decision": decision,
    }
    _append_jsonl(REVIEW_ACTIONS_PATH, action_row)

    publish_written = False
    if action in {"approve", "edit_approve"} and not _publish_exists(work_order_id):
        publish_payload = _build_publish_payload(work_order_id, edited_body=edited_body)
        if publish_payload:
            _append_jsonl(PUBLISH_PATH, publish_payload)
            publish_written = True

    return {
        "ok": True,
        "work_order_id": work_order_id,
        "action": action,
        "publish_payload_written": publish_written,
        "precedent_decision": decision,
        "policy_tier": tier,
    }


class ReviewActionsHandler(BaseHTTPRequestHandler):
    server_version = "ReviewActionsService/1.0"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if self.path.startswith("/escalations"):
            rows = _read_jsonl(ESCALATIONS_PATH)
            self._send_json(HTTPStatus.OK, {"count": len(rows), "rows": rows[-50:]})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/review-action":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
            return
        if not isinstance(payload, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "payload must be object"})
            return
        try:
            result = apply_review_action(payload)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._send_json(HTTPStatus.OK, result)

    def _send_json(self, code: HTTPStatus, data: dict[str, Any]) -> None:
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")


def run_server() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), ReviewActionsHandler)
    print(f"Listening on http://0.0.0.0:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
