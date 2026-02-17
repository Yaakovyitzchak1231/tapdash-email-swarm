#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import publish_sender as ps


class PublishSenderTests(unittest.TestCase):
    def test_process_once_skips_when_send_false(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pfile = root / "draft_publish_payloads.jsonl"
            state = root / "publish_sender_state.json"
            pfile.write_text(
                json.dumps({"work_order_id": "wo_1", "send": False}) + "\n",
                encoding="utf-8",
            )

            old_publish = ps.PUBLISH_FILE
            old_state = ps.STATE_PATH
            try:
                ps.PUBLISH_FILE = pfile
                ps.STATE_PATH = state
                with patch("publish_sender.send_payload") as send_payload:
                    count = ps.process_once()
                    send_payload.assert_not_called()
            finally:
                ps.PUBLISH_FILE = old_publish
                ps.STATE_PATH = old_state

            self.assertEqual(count, 0)
            sent_ids = json.loads(state.read_text(encoding="utf-8")).get("sent_ids", [])
            self.assertEqual(sent_ids, ["wo_1"])


if __name__ == "__main__":
    unittest.main()
