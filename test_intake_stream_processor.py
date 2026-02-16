import json
import tempfile
import unittest
from pathlib import Path

import intake_stream_processor as isp


class IntakeStreamProcessorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        isp.STATE_DIR = base / "state"
        isp.PROCESSED_KEYS_PATH = isp.STATE_DIR / "processed_keys.json"
        isp.ACTIONABLE_PATH = isp.STATE_DIR / "actionable_work_orders.jsonl"
        isp.REJECTED_PATH = isp.STATE_DIR / "rejected_work_orders.jsonl"
        isp.STATS_PATH = isp.STATE_DIR / "intake_stats.json"
        self.store = base / "work_orders.jsonl"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_rows(self, rows: list[dict]) -> None:
        with self.store.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

    def test_process_once_filters_and_dedupes(self) -> None:
        self._write_rows(
            [
                {
                    "id": "wo_1",
                    "sender": "person@acme.com",
                    "subject": "Need demo",
                    "email_event_id": "evt_1",
                },
                {
                    "id": "wo_2",
                    "sender": "no-reply@mailer.com",
                    "subject": "Weekly digest",
                    "email_event_id": "evt_2",
                },
                {
                    "id": "wo_3",
                    "sender": "Sender Email",
                    "subject": "subject",
                    "email_event_id": "Outlook message id",
                },
                {
                    "id": "wo_4",
                    "sender": "person@acme.com",
                    "subject": "Need demo",
                    "email_event_id": "evt_1",
                },
            ]
        )

        stats = isp.process_once(self.store)

        self.assertEqual(stats["processed"], 4)
        self.assertEqual(stats["actionable"], 1)
        self.assertEqual(stats["rejected_likely_noise"], 1)
        self.assertEqual(stats["rejected_invalid_mapping"], 1)
        self.assertEqual(stats["rejected_duplicate"], 1)

        actionable_lines = isp.ACTIONABLE_PATH.read_text(encoding="utf-8").splitlines()
        rejected_lines = isp.REJECTED_PATH.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(actionable_lines), 1)
        self.assertEqual(len(rejected_lines), 3)


if __name__ == "__main__":
    unittest.main()
