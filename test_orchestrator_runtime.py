#!/usr/bin/env python3

import unittest

from orchestrator.runtime import DurableOrchestrator
from orchestrator.stages import default_legacy_stages
from orchestrator.store import InMemoryRunStore


class OrchestratorRuntimeTests(unittest.TestCase):
    def test_run_work_order_completes_and_records_events(self) -> None:
        work_order = {
            "id": "wo_orch_1",
            "sender": "person@example.com",
            "subject": "Need help with onboarding timeline",
            "body": "Can we review next steps?",
            "labels": ["support"],
            "created_at": "2026-02-17T00:00:00+00:00",
        }
        store = InMemoryRunStore()
        orchestrator = DurableOrchestrator(
            store=store,
            stages=default_legacy_stages(),
        )
        result = orchestrator.run_work_order(work_order)

        self.assertEqual(result["work_order_id"], "wo_orch_1")
        self.assertIn(result["status"], {"completed", "needs_human_review"})
        self.assertEqual(result["current_stage"], "publish")
        self.assertGreaterEqual(len(store.events), 8)
        self.assertEqual(store.events[0]["stage"], "tier")
        self.assertEqual(store.events[-1]["stage"], "publish")

    def test_run_work_order_requires_id(self) -> None:
        store = InMemoryRunStore()
        orchestrator = DurableOrchestrator(
            store=store,
            stages=default_legacy_stages(),
        )
        with self.assertRaises(ValueError):
            orchestrator.run_work_order({"subject": "Missing id"})


if __name__ == "__main__":
    unittest.main()
