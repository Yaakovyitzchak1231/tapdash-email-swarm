#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

from precedent_memory import append_precedent, lookup_precedent


class PrecedentMemoryTests(unittest.TestCase):
    def test_lookup_no_data(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "precedents.jsonl"
            result = lookup_precedent("a@example.com", ["sales"], "A", path=path)
            self.assertFalse(result.found)
            self.assertEqual(result.sample_size, 0)

    def test_lookup_confident_match(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "precedents.jsonl"
            append_precedent("a@example.com", ["sales"], "A", "approve", path=path)
            append_precedent("a@example.com", ["sales"], "A", "approve", path=path)
            append_precedent("a@example.com", ["sales"], "A", "approve", path=path)
            result = lookup_precedent("a@example.com", ["sales"], "A", path=path)
            self.assertTrue(result.found)
            self.assertEqual(result.decision, "approve")
            self.assertGreaterEqual(result.confidence, 0.7)


if __name__ == "__main__":
    unittest.main()
