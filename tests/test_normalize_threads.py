import json
import tempfile
import unittest
from pathlib import Path

from email_thread_normalizer.normalize_threads import (
    canonical_thread_records,
    load_records,
    normalize_subject,
    strip_quote_and_signature_noise,
)


class NormalizeThreadsTests(unittest.TestCase):
    def test_subject_normalization(self):
        self.assertEqual(normalize_subject("Re: FWD: Re: Launch Plan"), "Launch Plan")

    def test_quote_and_signature_noise_removed(self):
        text = """Let's ship this on Friday.

Best regards,
Alex
--
Alex Doe
Senior PM
On Tue, Feb 1, 2026 at 10:00 AM Sam <sam@example.com> wrote:
> Old quoted content
"""
        cleaned = strip_quote_and_signature_noise(text)
        self.assertEqual(cleaned, "Let's ship this on Friday.\n\nBest regards,")

    def test_canonical_thread_records(self):
        records = [
            {
                "thread_id": "thread-1",
                "message_id": "m2",
                "from": "Sam <sam@example.com>",
                "to": "Alex <alex@example.com>",
                "subject": "Re: Re: Budget",
                "date": "2026-02-01T10:00:00",
                "body": "Looks good.\n\nSent from my iPhone",
            },
            {
                "thread_id": "thread-1",
                "message_id": "m1",
                "from": "Alex <alex@example.com>",
                "to": "Sam <sam@example.com>",
                "subject": "Budget",
                "date": "2026-01-31T09:00:00",
                "body": "Draft attached.\n\nOn Mon, Jan 31, 2026 at 9:00 AM Sam <sam@example.com> wrote:\n> previous",
            },
        ]

        threads = canonical_thread_records(records)
        self.assertEqual(len(threads), 1)
        thread = threads[0]

        self.assertEqual(thread["thread_id"], "thread-1")
        self.assertEqual(thread["subject"], "Budget")
        self.assertEqual(thread["message_count"], 2)
        self.assertEqual(thread["messages"][0]["message_id"], "m1")
        self.assertEqual(thread["messages"][1]["message_id"], "m2")
        self.assertIn("alex@example.com", thread["participants"])
        self.assertIn("sam@example.com", thread["participants"])

    def test_jsonl_loading(self):
        data = '{"thread_id":"t1","body":"x"}\n{"thread_id":"t2","body":"y"}\n'
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "input.jsonl"
            p.write_text(data, encoding="utf-8")
            records = load_records(p)
            self.assertEqual(len(records), 2)

    def test_json_array_loading(self):
        payload = [{"thread_id": "t1", "body": "x"}]
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "input.json"
            p.write_text(json.dumps(payload), encoding="utf-8")
            records = load_records(p)
            self.assertEqual(len(records), 1)


if __name__ == "__main__":
    unittest.main()
