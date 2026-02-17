#!/usr/bin/env python3

import unittest
from datetime import timedelta

from orchestrator.store import InMemoryRunStore
from swarm_langgraph.queue import InMemorySwarmJobQueue
from swarm_langgraph.queue import _now
from swarm_langgraph.supervisor import SwarmSupervisor
from swarm_langgraph.worker import SwarmWorker


class SwarmLangGraphTests(unittest.TestCase):
    def test_supervisor_runs_work_order(self) -> None:
        work_order = {
            "id": "wo_swarm_1",
            "sender": "ops@example.com",
            "subject": "Need onboarding support",
            "body": "Can you share two slots this week?",
            "labels": ["support"],
            "created_at": "2026-02-17T00:00:00+00:00",
        }
        store = InMemoryRunStore()
        supervisor = SwarmSupervisor(store=store)

        result = supervisor.run_work_order(work_order)

        self.assertEqual(result["work_order_id"], "wo_swarm_1")
        self.assertIn(result["status"], {"completed", "needs_human_review"})
        self.assertIn(result["current_stage"], {"policy", "publish"})
        self.assertGreaterEqual(len(store.events), 3)

    def test_worker_retries_and_dead_letters(self) -> None:
        class _FailingSupervisor:
            def run_work_order(self, work_order):
                raise RuntimeError("boom")

        queue = InMemorySwarmJobQueue()
        payload = {"id": "wo_fail_1", "sender": "x@example.com", "subject": "test", "body": "test"}
        queue.enqueue(work_order_id="wo_fail_1", payload=payload)
        worker = SwarmWorker(supervisor=_FailingSupervisor(), queue=queue, max_attempts=2)

        first = worker.process_once()
        self.assertIsNotNone(first)
        self.assertEqual(first["status"], "retry")

        second = worker.process_once()
        self.assertIsNotNone(second)
        self.assertEqual(second["status"], "dead_letter")

        job = queue.jobs[0]
        self.assertEqual(job.status, "dead_letter")

    def test_worker_reaper_recovers_stale_running_job(self) -> None:
        class _NoopSupervisor:
            def run_work_order(self, work_order):
                return {"ok": True}

        queue = InMemorySwarmJobQueue()
        payload = {"id": "wo_stale_1", "sender": "x@example.com", "subject": "test", "body": "test"}
        queue.enqueue(work_order_id="wo_stale_1", payload=payload)
        worker = SwarmWorker(supervisor=_NoopSupervisor(), queue=queue, max_attempts=3)
        claimed = queue.claim_next()
        self.assertIsNotNone(claimed)
        queue.jobs[0].locked_at = _now() - timedelta(hours=1)

        recovered = worker.recover_stale_once(stale_after_seconds=60)
        self.assertEqual(recovered, 1)
        self.assertEqual(queue.jobs[0].status, "queued")


if __name__ == "__main__":
    unittest.main()
