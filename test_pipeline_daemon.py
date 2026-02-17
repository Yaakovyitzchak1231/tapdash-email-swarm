#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_draft_agent_uses_openai_when_available(self) -> None:
        work_order = {
            "id": "wo_test_openai",
            "sender": "person@example.com",
            "subject": "Need a proposal",
            "body": "Can you send details?",
            "labels": ["sales"],
        }
        context = pipeline_daemon.context_agent(work_order)

        fake_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "draft_subject": "Re: Need a proposal",
                                "draft_body": "Hi there, here are details and next steps.",
                                "confidence": 0.91,
                                "rationale": "Uses provided sender intent and asks a clear CTA.",
                                "citations": ["crm:contact", "thread:latest"],
                            }
                        )
                    }
                }
            ]
        }

        with patch.object(pipeline_daemon, "OPENAI_API_KEY", "sk-test"):
            with patch("pipeline_daemon.requests.post") as mock_post:
                mock_post.return_value.raise_for_status.return_value = None
                mock_post.return_value.json.return_value = fake_response

                draft = pipeline_daemon.draft_agent(
                    work_order=work_order,
                    context=context,
                    policy_tier="B",
                )

        self.assertEqual(draft["draft_agent"], "openai")
        self.assertEqual(draft["draft_subject"], "Re: Need a proposal")
        self.assertGreaterEqual(draft["confidence"], 0.9)
        self.assertEqual(draft["to"], "person@example.com")


if __name__ == "__main__":
    unittest.main()
