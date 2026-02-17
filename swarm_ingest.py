#!/usr/bin/env python3
"""Ingest actionable work orders into the swarm job queue."""

from __future__ import annotations

import json
from hashlib import sha1
from pathlib import Path
from typing import Any, Protocol


class SwarmEnqueueQueue(Protocol):
    def enqueue(self, work_order_id: str, payload: dict[str, Any]) -> str: ...


class ActionableSwarmIngestor:
    def __init__(self, queue: SwarmEnqueueQueue, actionable_path: Path, state_path: Path) -> None:
        self.queue = queue
        self.actionable_path = actionable_path
        self.state_path = state_path

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"offset": 0, "mtime_ns": 0, "start_sig": ""}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            return {
                "offset": int(payload.get("offset", 0)),
                "mtime_ns": int(payload.get("mtime_ns", 0)),
                "start_sig": str(payload.get("start_sig", "")),
            }
        except Exception:
            return {"offset": 0, "mtime_ns": 0, "start_sig": ""}

    def _save_state(self, offset: int, mtime_ns: int, start_sig: str) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(
                {
                    "offset": max(0, int(offset)),
                    "mtime_ns": max(0, int(mtime_ns)),
                    "start_sig": start_sig,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _extract_work_order(row: dict[str, Any]) -> dict[str, Any] | None:
        work_order = row.get("work_order")
        if not isinstance(work_order, dict):
            return None
        work_order_id = str(work_order.get("id") or "").strip()
        if not work_order_id:
            return None
        return work_order

    def ingest_once(self) -> dict[str, int]:
        stats = {
            "rows_read": 0,
            "rows_enqueued": 0,
            "rows_skipped": 0,
        }
        if not self.actionable_path.exists():
            return stats

        state = self._load_state()
        offset = int(state.get("offset", 0))
        previous_mtime_ns = int(state.get("mtime_ns", 0))
        previous_start_sig = str(state.get("start_sig", ""))
        stat = self.actionable_path.stat()
        file_size = stat.st_size
        mtime_ns = int(stat.st_mtime_ns)
        start_sig = self._start_signature()
        if offset > file_size or start_sig != previous_start_sig or (
            file_size <= offset and mtime_ns != previous_mtime_ns
        ):
            offset = 0

        with self.actionable_path.open("r", encoding="utf-8") as f:
            f.seek(offset)
            chunk = f.read()
            new_offset = f.tell()

        if not chunk:
            self._save_state(new_offset, mtime_ns=mtime_ns, start_sig=start_sig)
            return stats

        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            stats["rows_read"] += 1
            try:
                row = json.loads(line)
            except Exception:
                stats["rows_skipped"] += 1
                continue
            if not isinstance(row, dict):
                stats["rows_skipped"] += 1
                continue
            work_order = self._extract_work_order(row)
            if not work_order:
                stats["rows_skipped"] += 1
                continue
            work_order_id = str(work_order["id"])
            self.queue.enqueue(work_order_id=work_order_id, payload=work_order)
            stats["rows_enqueued"] += 1

        self._save_state(new_offset, mtime_ns=mtime_ns, start_sig=start_sig)
        return stats

    def _start_signature(self) -> str:
        with self.actionable_path.open("rb") as f:
            sample = f.read(256)
        return sha1(sample).hexdigest()
