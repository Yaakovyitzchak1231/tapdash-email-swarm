#!/usr/bin/env python3
"""Scaffold runner for the durable orchestrator path.

This script does not replace the production daemon yet.
Use it to validate the Postgres-backed orchestration flow on sample work orders.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from orchestrator import DurableOrchestrator, InMemoryRunStore, PostgresRunStore, default_legacy_stages
from orchestrator.config import OrchestratorConfig


def _read_first_actionable(path: Path) -> dict[str, Any]:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if isinstance(row, dict) and row.get("work_order"):
            work_order = row.get("work_order")
            if isinstance(work_order, dict):
                return work_order
    raise RuntimeError(f"No actionable work order found in {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run durable orchestrator scaffold once.")
    parser.add_argument(
        "--work-order-json",
        default="",
        help="Optional inline work order JSON. If omitted, uses --actionable-path first row.",
    )
    parser.add_argument(
        "--actionable-path",
        default="/home/jacob/intake_state/actionable_work_orders.jsonl",
        help="Path to actionable JSONL file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use in-memory storage instead of Postgres.",
    )
    args = parser.parse_args()

    if args.work_order_json:
        work_order = json.loads(args.work_order_json)
    else:
        work_order = _read_first_actionable(Path(args.actionable_path))

    cfg = OrchestratorConfig.from_env()
    if args.dry_run:
        store = InMemoryRunStore()
    else:
        store = PostgresRunStore(cfg.database_url)
        store.ensure_schema()

    orchestrator = DurableOrchestrator(store=store, stages=default_legacy_stages())
    result = orchestrator.run_work_order(work_order)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
