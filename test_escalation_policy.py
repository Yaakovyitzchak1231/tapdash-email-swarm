#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

from escalation_policy import classify_text, ensure_default_policy, load_policy


class EscalationPolicyTests(unittest.TestCase):
    def test_default_policy_bootstrap_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policy.json"
            ensure_default_policy(path)
            policy = load_policy(path)
            self.assertIn("tiers", policy)
            self.assertIn("triggers", policy)

    def test_classify_tier_c_keyword(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            policy = load_policy(Path(td) / "policy.json")
            decision = classify_text("Can you send pricing and legal terms?", policy)
            self.assertEqual(decision.tier, "C")
            self.assertFalse(decision.auto_publish_allowed)

    def test_classify_tier_a_ack(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            policy = load_policy(Path(td) / "policy.json")
            decision = classify_text("Thanks, we received your message. Share time windows.", policy)
            self.assertEqual(decision.tier, "A")
            self.assertTrue(decision.auto_publish_allowed)


if __name__ == "__main__":
    unittest.main()
