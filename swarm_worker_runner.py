#!/usr/bin/env python3
"""Swarm worker runner for LangGraph + Postgres queue mode."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from orchestrator.store import InMemoryRunStore, PostgresRunStore
from swarm_ingest import ActionableSwarmIngestor
from swarm_langgraph.queue import InMemorySwarmJobQueue, PostgresSwarmJobQueue
from swarm_langgraph.supervisor import SwarmSupervisor
from swarm_langgraph.worker import SwarmWorker
from swarm_publish_dispatcher import SwarmPublishDispatcher


def main() -> int:
    parser = argparse.ArgumentParser(description="Run swarm worker loop.")
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit.")
    parser.add_argument("--interval-seconds", type=int, default=10, help="Poll interval for queue jobs.")
    parser.add_argument("--dry-run", action="store_true", help="Use in-memory queue/store only.")
    parser.add_argument(
        "--stale-timeout-seconds",
        type=int,
        default=int(os.environ.get("SWARM_STALE_TIMEOUT_SECONDS", "900")),
        help="Timeout for stale running jobs before recovery.",
    )
    args = parser.parse_args()

    intake_state_dir = Path(os.environ.get("INTAKE_STATE_DIR", "/home/jacob/intake_state"))
    actionable_path = Path(os.environ.get("SWARM_ACTIONABLE_PATH", str(intake_state_dir / "actionable_work_orders.jsonl")))
    ingest_state_path = Path(os.environ.get("SWARM_INGEST_STATE_PATH", str(intake_state_dir / "swarm_ingest_state.json")))
    enable_ingest = os.environ.get("SWARM_ENABLE_INGEST", "true").strip().lower() in {"1", "true", "yes", "on"}
    enable_dispatch = os.environ.get("SWARM_ENABLE_DISPATCH", "true").strip().lower() in {"1", "true", "yes", "on"}
    auto_send_enabled = os.environ.get("AUTO_SEND_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    publish_webhook_url = os.environ.get("PUBLISH_WEBHOOK_URL", "").strip()
    dispatch_max_attempts = int(os.environ.get("SWARM_PUBLISH_MAX_ATTEMPTS", "5"))

    dispatcher = None
    if args.dry_run:
        queue = InMemorySwarmJobQueue()
        store = InMemoryRunStore()
    else:
        database_url = os.environ.get("DATABASE_URL", "").strip()
        store = PostgresRunStore(database_url=database_url)
        store.ensure_schema()
        queue = PostgresSwarmJobQueue(database_url=database_url)
        if enable_dispatch:
            dispatcher = SwarmPublishDispatcher(
                database_url=database_url,
                webhook_url=publish_webhook_url,
                auto_send_enabled=auto_send_enabled,
                max_attempts=dispatch_max_attempts,
            )

    supervisor = SwarmSupervisor(store=store)
    worker = SwarmWorker(supervisor=supervisor, queue=queue)
    ingestor = (
        ActionableSwarmIngestor(
            queue=queue,
            actionable_path=actionable_path,
            state_path=ingest_state_path,
        )
        if enable_ingest
        else None
    )

    if args.once:
        ingest_stats = ingestor.ingest_once() if ingestor else {"rows_read": 0, "rows_enqueued": 0, "rows_skipped": 0}
        recovered = worker.recover_stale_once(stale_after_seconds=max(1, args.stale_timeout_seconds))
        result = worker.process_once()
        dispatch_result = dispatcher.process_once() if dispatcher else {"status": "disabled"}
        print(
            json.dumps(
                {
                    "ingest": ingest_stats,
                    "recovered_stale_jobs": recovered,
                    "worker": result or {"status": "empty"},
                    "dispatch": dispatch_result,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    while True:
        if ingestor:
            ingest_stats = ingestor.ingest_once()
            if ingest_stats.get("rows_enqueued", 0):
                print(json.dumps({"swarm_ingest": ingest_stats}, separators=(",", ":"), sort_keys=True))
        recovered = worker.recover_stale_once(stale_after_seconds=max(1, args.stale_timeout_seconds))
        if recovered:
            print(json.dumps({"swarm_reaper_recovered": recovered}, separators=(",", ":"), sort_keys=True))
        result = worker.process_once()
        if result:
            print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        dispatch_result = dispatcher.process_once() if dispatcher else None
        if dispatch_result and dispatch_result.get("status") not in {"empty", "disabled"}:
            print(json.dumps({"swarm_dispatch": dispatch_result}, separators=(",", ":"), sort_keys=True))
        if not result and (not dispatch_result or dispatch_result.get("status") in {"empty", "disabled"}):
            time.sleep(max(1, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
