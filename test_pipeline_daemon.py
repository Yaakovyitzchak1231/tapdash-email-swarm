#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pipeline_daemon
from precedent_memory import PrecedentMatch


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
                with patch.object(
                    pipeline_daemon,
                    "quality_gate_agent",
                    return_value={
                        "quality_pass": True,
                        "quality_status": "pass",
                        "quality_issues": [],
                        "quality_signals": {},
                    },
                ):
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

    def test_qa_agent_fails_on_low_confidence_and_tone_fact_issues(self) -> None:
        work_order = {
            "id": "wo_low_quality",
            "sender": "person@example.com",
            "subject": "Follow up",
        }
        draft = {
            "work_order_id": "wo_low_quality",
            "to": "person@example.com",
            "draft_subject": "Re: Follow up",
            "draft_body": "Reply",
            "confidence": 0.22,
            "draft_agent": "openai",
        }
        tone_checked = {"tone_ok": False, "revised_draft": "Reply"}
        fact_checked = {"fact_status": "needs_review"}

        qa = pipeline_daemon.qa_agent(
            work_order=work_order,
            draft=draft,
            tone_checked=tone_checked,
            fact_checked=fact_checked,
        )

        self.assertFalse(qa["qa_pass"])
        self.assertEqual(qa["qa_status"], "needs_review")
        self.assertEqual(qa["qa_score"], 22)
        self.assertIn("style_violation", qa["qa_reasons"])
        self.assertIn("fact_gate_needs_review", qa["qa_reasons"])
        self.assertIn("quality_gate_needs_review", qa["qa_reasons"])
        self.assertIn("missing_actionable_cta", qa["qa_reasons"])

    def test_policy_agent_auto_publish_override_vs_escalation(self) -> None:
        work_order = {
            "id": "wo_policy_branch",
            "sender": "ops@example.com",
            "labels": ["support"],
        }
        draft = {"confidence": 0.9}
        qa_result = {"qa_pass": False}
        fact_checked = {"fact_status": "needs_review"}

        with patch.object(
            pipeline_daemon,
            "lookup_precedent",
            return_value=PrecedentMatch(
                found=True,
                decision="auto_publish",
                confidence=0.95,
                key="example.com|support|B",
                sample_size=4,
            ),
        ):
            auto_publish = pipeline_daemon.policy_agent(
                work_order=work_order,
                decision_tier="B",
                decision_reason="tier_b_safe_operational_default",
                draft=draft,
                qa_result={**qa_result, "quality_status": "pass", "quality_issues": []},
                fact_checked=fact_checked,
            )
        self.assertFalse(auto_publish["needs_human_review"])
        self.assertEqual(auto_publish["reason"], "auto_publish_allowed")

        with patch.object(
            pipeline_daemon,
            "lookup_precedent",
            return_value=PrecedentMatch(
                found=False,
                decision="unknown",
                confidence=0.0,
                key="example.com|support|B",
                sample_size=0,
            ),
        ):
            escalated = pipeline_daemon.policy_agent(
                work_order=work_order,
                decision_tier="B",
                decision_reason="tier_b_safe_operational_default",
                draft=draft,
                qa_result={**qa_result, "quality_status": "pass", "quality_issues": []},
                fact_checked=fact_checked,
            )
        self.assertTrue(escalated["needs_human_review"])
        self.assertEqual(escalated["reason"], "tier_or_fact_or_qa_or_confidence")

    def test_publish_agent_blocks_when_policy_needs_review(self) -> None:
        publish_row = pipeline_daemon.publish_agent(
            work_order={"id": "wo_blocked"},
            draft={"to": "person@example.com", "draft_subject": "Re: Hi"},
            tone_checked={"revised_draft": "Hi"},
            qa_result={"qa_status": "needs_review"},
            fact_checked={"fact_status": "needs_review"},
            policy_result={"needs_human_review": True},
        )
        self.assertIsNone(publish_row)

    def test_qa_short_confirmation_false_positive_guard(self) -> None:
        work_order = {
            "id": "wo_short_confirm",
            "sender": "a@x.io",
            "subject": "ok",
        }
        draft = {
            "work_order_id": "wo_short_confirm",
            "to": "person@example.com",
            "draft_subject": "Re: Confirmed",
            "draft_body": "Confirmed. Please confirm Tuesday works.",
            "confidence": 0.84,
            "draft_agent": "openai",
        }
        tone_checked = {
            "tone_ok": True,
            "revised_draft": "Confirmed. Please confirm Tuesday works.",
        }
        fact_checked = {"fact_status": "pass"}

        qa = pipeline_daemon.qa_agent(
            work_order=work_order,
            draft=draft,
            tone_checked=tone_checked,
            fact_checked=fact_checked,
        )

        self.assertTrue(qa["qa_pass"])
        self.assertEqual(qa["qa_status"], "pass")
        self.assertIn("style_compliant", qa["qa_reasons"])
        self.assertIn("fact_gate_pass", qa["qa_reasons"])
        self.assertIn("quality_gate_pass", qa["qa_reasons"])


if __name__ == "__main__":
    unittest.main()
