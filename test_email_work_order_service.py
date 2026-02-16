import json
import tempfile
import unittest
from pathlib import Path

import email_work_order_service as svc


class EmailWorkOrderServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        svc.STORE_PATH = Path(self.tmp.name) / "orders.jsonl"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_preliminary_labels_urgent_billing(self) -> None:
        labels = svc.preliminary_labels(
            sender="ops@acme.com",
            subject="URGENT billing issue",
            body="Payment error on invoice 123",
        )
        self.assertIn("urgent", labels)
        self.assertIn("billing", labels)
        self.assertIn("support", labels)

    def test_preliminary_labels_domain_heuristics(self) -> None:
        labels = svc.preliminary_labels(
            sender="student@university.edu",
            subject="Need login reset",
            body="Account locked",
        )
        self.assertIn("education", labels)
        self.assertIn("account", labels)

    def test_create_work_order_persists_jsonl(self) -> None:
        order = svc.create_work_order(
            {
                "event_id": "evt_1",
                "sender": "person@gmail.com",
                "subject": "Can I get a quote?",
                "body": "Need pricing for 20 seats",
            }
        )
        self.assertEqual(order.email_event_id, "evt_1")
        self.assertEqual(order.source, "inbound_email")

        lines = svc.STORE_PATH.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        saved = json.loads(lines[0])
        self.assertEqual(saved["id"], order.id)
        self.assertIn("sales", saved["labels"])
        self.assertIn("consumer", saved["labels"])

    def test_normalize_zapier_email_event(self) -> None:
        normalized = svc.normalize_zapier_email_event(
            {
                "messageId": "msg_77",
                "from_email": "owner@tapdash.co",
                "subject": "Pricing question",
                "body_plain": "Can you confirm annual pricing?",
            }
        )
        self.assertEqual(normalized["event_id"], "msg_77")
        self.assertEqual(normalized["sender"], "owner@tapdash.co")
        self.assertEqual(normalized["subject"], "Pricing question")


if __name__ == "__main__":
    unittest.main()
