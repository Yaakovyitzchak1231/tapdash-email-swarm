#!/usr/bin/env python3
"""Swarm worker runner for LangGraph + Postgres queue mode."""

from __future__ import annotations

import argparse
import json
import os
import time

from orchestrator.store import InMemoryRunStore, PostgresRunStore
from swarm_langgraph.queue import InMemorySwarmJobQueue, PostgresSwarmJobQueue
from swarm_langgraph.supervisor import SwarmSupervisor
from swarm_langgraph.worker import SwarmWorker


def main() -> int:
    parser = argparse.ArgumentParser(description="Run swarm worker loop.")
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit.")
    parser.add_argument("--interval-seconds", type=int, default=10, help="Poll interval for queue jobs.")
    parser.add_argument("--dry-run", action="store_true", help="Use in-memory queue/store only.")
    args = parser.parse_args()

    if args.dry_run:
        queue = InMemorySwarmJobQueue()
        store = InMemoryRunStore()
    else:
        database_url = os.environ.get("DATABASE_URL", "").strip()
        store = PostgresRunStore(database_url=database_url)
        store.ensure_schema()
        queue = PostgresSwarmJobQueue(database_url=database_url)

    supervisor = SwarmSupervisor(store=store)
    worker = SwarmWorker(supervisor=supervisor, queue=queue)

    if args.once:
        result = worker.process_once()
        print(json.dumps(result or {"status": "empty"}, indent=2, sort_keys=True))
        return 0

    while True:
        result = worker.process_once()
        if result:
            print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        else:
            time.sleep(max(1, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
