#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path

import review_actions_service as ras


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


class ReviewActionsServiceTests(unittest.TestCase):
    def test_apply_review_action_approve_writes_publish_and_precedent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pipeline = root / "pipeline_out"
            work_orders = root / "work_orders.jsonl"
            memory = root / "memory" / "precedents.jsonl"

            _write_jsonl(
                pipeline / "escalations.jsonl",
                [
                    {
                        "work_order_id": "wo_1",
                        "needs_human_review": True,
                        "policy_tier": "B",
                    }
                ],
            )
            _write_jsonl(
                pipeline / "tone_checked.jsonl",
                [
                    {
                        "work_order_id": "wo_1",
                        "to": "a@example.com",
                        "draft_subject": "Re: Hello",
                        "revised_draft": "Hi there",
                    }
                ],
            )
            _write_jsonl(
                work_orders,
                [
                    {
                        "id": "wo_1",
                        "sender": "a@example.com",
                        "labels": ["sales"],
                    }
                ],
            )

            old_pipeline = ras.PIPELINE_DIR
            old_work_orders = ras.WORK_ORDER_STORE
            old_review_path = ras.REVIEW_ACTIONS_PATH
            old_esc = ras.ESCALATIONS_PATH
            old_pub = ras.PUBLISH_PATH
            old_tone = ras.TONE_PATH
            try:
                ras.PIPELINE_DIR = pipeline
                ras.WORK_ORDER_STORE = work_orders
                ras.REVIEW_ACTIONS_PATH = pipeline / "review_actions.jsonl"
                ras.ESCALATIONS_PATH = pipeline / "escalations.jsonl"
                ras.PUBLISH_PATH = pipeline / "draft_publish_payloads.jsonl"
                ras.TONE_PATH = pipeline / "tone_checked.jsonl"

                # Patch precedent target by monkeypatching function call site.
                from precedent_memory import append_precedent as real_append

                def patched_append(sender, labels, tier, decision):  # type: ignore[no-redef]
                    return real_append(sender, labels, tier, decision, path=memory)

                ras.append_precedent = patched_append  # type: ignore[assignment]

                result = ras.apply_review_action(
                    {"work_order_id": "wo_1", "action": "approve", "reviewer": "yaakov"}
                )
            finally:
                ras.PIPELINE_DIR = old_pipeline
                ras.WORK_ORDER_STORE = old_work_orders
                ras.REVIEW_ACTIONS_PATH = old_review_path
                ras.ESCALATIONS_PATH = old_esc
                ras.PUBLISH_PATH = old_pub
                ras.TONE_PATH = old_tone

            self.assertTrue(result["ok"])
            self.assertTrue(result["publish_payload_written"])
            self.assertTrue((pipeline / "draft_publish_payloads.jsonl").exists())
            self.assertTrue(memory.exists())

    def test_edit_approve_requires_edited_body(self) -> None:
        with self.assertRaises(ValueError):
            ras.apply_review_action({"work_order_id": "wo_x", "action": "edit_approve"})


if __name__ == "__main__":
    unittest.main()
