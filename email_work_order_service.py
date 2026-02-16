#!/usr/bin/env python3
"""Inbound email event monitor that creates work orders with preliminary labels."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

STORE_PATH = Path(os.environ.get("WORK_ORDER_STORE", "work_orders.jsonl"))
PORT = int(os.environ.get("PORT", "8080"))
ZAPIER_SHARED_SECRET = os.environ.get("ZAPIER_SHARED_SECRET", "").strip()


LABEL_RULES: dict[str, tuple[str, ...]] = {
    "billing": ("invoice", "billing", "payment", "charge", "refund"),
    "support": ("help", "issue", "problem", "error", "unable", "cannot"),
    "urgent": ("urgent", "asap", "immediately", "outage", "down", "critical"),
    "sales": ("quote", "pricing", "demo", "purchase", "trial"),
    "account": ("login", "password", "reset", "access", "locked"),
}


@dataclass
class WorkOrder:
    id: str
    created_at: str
    source: str
    sender: str
    subject: str
    labels: list[str]
    status: str
    email_event_id: str | None = None


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9']+", text.lower()))


def preliminary_labels(sender: str, subject: str, body: str) -> list[str]:
    text_tokens = _tokenize(f"{subject} {body}")
    labels: set[str] = set()

    for label, keywords in LABEL_RULES.items():
        if any(keyword in text_tokens for keyword in keywords):
            labels.add(label)

    sender_domain = sender.split("@")[-1].lower() if "@" in sender else ""
    if sender_domain.endswith(".gov"):
        labels.add("government")
    if sender_domain.endswith(".edu"):
        labels.add("education")
    if sender_domain in {"gmail.com", "yahoo.com", "outlook.com"}:
        labels.add("consumer")

    if not labels:
        labels.add("general")

    return sorted(labels)


def create_work_order(email_event: dict[str, Any]) -> WorkOrder:
    sender = str(email_event.get("sender", "")).strip()
    subject = str(email_event.get("subject", "")).strip()
    body = str(email_event.get("body", "")).strip()
    event_id = email_event.get("event_id")

    work_order = WorkOrder(
        id=f"wo_{uuid4().hex[:12]}",
        created_at=datetime.now(tz=timezone.utc).isoformat(),
        source="inbound_email",
        sender=sender,
        subject=subject,
        labels=preliminary_labels(sender=sender, subject=subject, body=body),
        status="new",
        email_event_id=str(event_id) if event_id is not None else None,
    )
    _persist_work_order(work_order)
    return work_order


def normalize_zapier_email_event(payload: dict[str, Any]) -> dict[str, Any]:
    sender = str(
        payload.get("from_email")
        or payload.get("from")
        or payload.get("sender")
        or ""
    ).strip()
    subject = str(payload.get("subject") or payload.get("topic") or "").strip()
    body = str(
        payload.get("body_plain")
        or payload.get("plain_body")
        or payload.get("body")
        or payload.get("text")
        or ""
    ).strip()
    # Prefer Zapier-provided unique identifiers when present.
    # Some email triggers re-use Outlook message IDs across test sends, which
    # would cause our downstream dedupe to drop legitimately new events.
    event_id = (
        payload.get("zap_event_id")
        or payload.get("zap_meta_human_now")
        or payload.get("zap_id")
        or payload.get("event_id")
        or payload.get("message_id")
        or payload.get("messageId")
        or payload.get("id")
    )
    return {
        "event_id": str(event_id) if event_id is not None else None,
        "sender": sender,
        "subject": subject,
        "body": body,
    }


def _webhook_secret_valid(headers: Any) -> bool:
    if not ZAPIER_SHARED_SECRET:
        return True
    supplied = str(headers.get("X-Webhook-Secret", "")).strip()
    return supplied == ZAPIER_SHARED_SECRET


def _persist_work_order(order: WorkOrder) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STORE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(order), separators=(",", ":")) + "\n")


class EmailEventHandler(BaseHTTPRequestHandler):
    server_version = "EmailWorkOrderService/1.0"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path not in {"/email-events", "/zapier/email-forward"}:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        if not _webhook_secret_valid(self.headers):
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid webhook secret"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(content_length)
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
            return

        if not isinstance(parsed, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "payload must be an object"})
            return

        if self.path == "/zapier/email-forward":
            parsed = normalize_zapier_email_event(parsed)

        order = create_work_order(parsed)
        self._send_json(HTTPStatus.CREATED, {"work_order": asdict(order)})

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
    server = ThreadingHTTPServer(("0.0.0.0", PORT), EmailEventHandler)
    print(f"Listening on http://0.0.0.0:{PORT} (store={STORE_PATH})")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
