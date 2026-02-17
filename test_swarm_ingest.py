#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path

from swarm_ingest import ActionableSwarmIngestor
from swarm_langgraph.queue import InMemorySwarmJobQueue


class SwarmIngestTests(unittest.TestCase):
    def test_ingest_once_reads_new_rows_and_tracks_offset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            actionable = root / "actionable.jsonl"
            state = root / "ingest_state.json"
            actionable.write_text(
                "\n".join(
                    [
                        json.dumps({"work_order": {"id": "wo_1", "sender": "a@example.com"}}),
                        json.dumps({"not_work_order": True}),
                        json.dumps({"work_order": {"id": "wo_2", "sender": "b@example.com"}}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            queue = InMemorySwarmJobQueue()
            ingestor = ActionableSwarmIngestor(queue=queue, actionable_path=actionable, state_path=state)

            first = ingestor.ingest_once()
            second = ingestor.ingest_once()

            self.assertEqual(first["rows_read"], 3)
            self.assertEqual(first["rows_enqueued"], 2)
            self.assertEqual(first["rows_skipped"], 1)
            self.assertEqual(second["rows_read"], 0)
            self.assertEqual(len(queue.jobs), 2)

    def test_ingest_handles_truncated_file_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            actionable = root / "actionable.jsonl"
            state = root / "ingest_state.json"
            actionable.write_text(
                json.dumps({"work_order": {"id": "wo_old", "sender": "a@example.com"}}) + "\n",
                encoding="utf-8",
            )
            queue = InMemorySwarmJobQueue()
            ingestor = ActionableSwarmIngestor(queue=queue, actionable_path=actionable, state_path=state)
            ingestor.ingest_once()

            actionable.write_text(
                json.dumps({"work_order": {"id": "wo_new", "sender": "new@example.com"}}) + "\n",
                encoding="utf-8",
            )
            result = ingestor.ingest_once()

            self.assertEqual(result["rows_enqueued"], 1)
            self.assertEqual(queue.jobs[-1].work_order_id, "wo_new")


if __name__ == "__main__":
    unittest.main()
