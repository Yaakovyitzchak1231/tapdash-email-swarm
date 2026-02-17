#!/usr/bin/env python3
"""Dispatch publish artifacts from Postgres to webhook."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    import psycopg


@dataclass
class PublishQueueRow:
    row_id: int
    work_order_id: str
    payload: dict[str, Any]
    attempt: int


def _should_send(payload: dict[str, Any]) -> bool:
    raw = payload.get("send", True)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(raw)


class SwarmPublishDispatcher:
    def __init__(
        self,
        database_url: str,
        webhook_url: str,
        auto_send_enabled: bool,
        max_attempts: int = 5,
    ) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is required for SwarmPublishDispatcher.")
        self.database_url = database_url
        self.webhook_url = webhook_url.strip()
        self.auto_send_enabled = auto_send_enabled
        self.max_attempts = max(1, int(max_attempts))

    def _connect(self) -> "psycopg.Connection":
        import psycopg

        return psycopg.connect(self.database_url)

    def claim_next(self) -> PublishQueueRow | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    with candidate as (
                        select id
                        from publish_queue
                        where dispatch_status = 'queued'
                        order by created_at asc
                        for update skip locked
                        limit 1
                    )
                    update publish_queue p
                    set dispatch_status = 'running',
                        dispatch_attempts = p.dispatch_attempts + 1
                    from candidate c
                    where p.id = c.id
                    returning p.id, p.work_order_id, p.payload, p.dispatch_attempts
                    """
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            return None
        return PublishQueueRow(
            row_id=int(row[0]),
            work_order_id=str(row[1]),
            payload=row[2] if isinstance(row[2], dict) else {},
            attempt=int(row[3]),
        )

    def mark_dispatched(self, row_id: int, note: str = "") -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update publish_queue
                    set dispatch_status = 'dispatched',
                        dispatched_at = now(),
                        last_error = %s
                    where id = %s
                    """,
                    (note or None, row_id),
                )
            conn.commit()

    def mark_retry_or_dead_letter(self, row_id: int, attempt: int, error: str) -> str:
        if attempt >= self.max_attempts:
            status = "dead_letter"
        else:
            status = "queued"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update publish_queue
                    set dispatch_status = %s,
                        last_error = %s
                    where id = %s
                    """,
                    (status, error[:1000], row_id),
                )
            conn.commit()
        return status

    def _post(self, payload: dict[str, Any]) -> tuple[bool, str]:
        if not self.webhook_url:
            return False, "webhook_not_configured"
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=8)
            if resp.status_code >= 400:
                return False, f"webhook_http_{resp.status_code}"
            return True, ""
        except Exception as exc:
            return False, f"webhook_exception:{type(exc).__name__}"

    def process_once(self) -> dict[str, Any]:
        row = self.claim_next()
        if not row:
            return {"status": "empty"}

        should_send = _should_send(row.payload)
        if not should_send:
            self.mark_dispatched(row.row_id, note="send_false")
            return {"status": "skipped", "work_order_id": row.work_order_id, "reason": "send_false"}

        if not self.auto_send_enabled:
            self.mark_dispatched(row.row_id, note="auto_send_disabled")
            return {
                "status": "skipped",
                "work_order_id": row.work_order_id,
                "reason": "auto_send_disabled",
            }

        ok, err = self._post(row.payload)
        if ok:
            self.mark_dispatched(row.row_id)
            return {"status": "dispatched", "work_order_id": row.work_order_id}

        next_status = self.mark_retry_or_dead_letter(row.row_id, attempt=row.attempt, error=err)
        return {
            "status": next_status,
            "work_order_id": row.work_order_id,
            "error": err,
        }
