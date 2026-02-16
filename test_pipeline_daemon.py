#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path

import pipeline_daemon


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


class PipelineDaemonTests(unittest.TestCase):
    def test_run_once_processes_new_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            actionable = root / "actionable.jsonl"
            pipeline_dir = root / "pipeline_out"
            state_path = pipeline_dir / "daemon_state.json"

            _write_jsonl(
                actionable,
                [
                    {
                        "decision": "actionable",
                        "work_order": {
                            "id": "wo_test_1",
                            "sender": "person@example.com",
                            "subject": "Thanks, received. Share times.",
                            "labels": ["support"],
                            "created_at": "2026-02-16T00:00:00+00:00",
                        },
                    }
                ],
            )

            # Patch module globals for isolated test paths.
            old_actionable = pipeline_daemon.ACTIONABLE_PATH
            old_pipeline_dir = pipeline_daemon.PIPELINE_DIR
            old_state_path = pipeline_daemon.STATE_PATH
            try:
                pipeline_daemon.ACTIONABLE_PATH = actionable
                pipeline_daemon.PIPELINE_DIR = pipeline_dir
                pipeline_daemon.STATE_PATH = state_path
                processed = pipeline_daemon.run_once(actionable_path=actionable)
            finally:
                pipeline_daemon.ACTIONABLE_PATH = old_actionable
                pipeline_daemon.PIPELINE_DIR = old_pipeline_dir
                pipeline_daemon.STATE_PATH = old_state_path

            self.assertEqual(processed, 1)
            self.assertTrue((pipeline_dir / "drafts.jsonl").exists())
            self.assertTrue((pipeline_dir / "fact_checked.jsonl").exists())
            self.assertTrue((pipeline_dir / "escalations.jsonl").exists())

            publish_rows = (pipeline_dir / "draft_publish_payloads.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(publish_rows), 1)


if __name__ == "__main__":
    unittest.main()
