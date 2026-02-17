#!/usr/bin/env python3

import unittest

from swarm_publish_dispatcher import PublishQueueRow, SwarmPublishDispatcher


class _FakeDispatcher(SwarmPublishDispatcher):
    def __init__(
        self,
        row: PublishQueueRow | None,
        *,
        auto_send_enabled: bool = True,
        post_ok: bool = True,
        max_attempts: int = 3,
    ) -> None:
        self._row = row
        self.auto_send_enabled = auto_send_enabled
        self.max_attempts = max_attempts
        self.webhook_url = "https://example.com/hook"
        self._post_ok = post_ok
        self.dispatched_notes: list[str] = []
        self.retry_calls: list[tuple[int, int, str]] = []

    def claim_next(self) -> PublishQueueRow | None:
        row = self._row
        self._row = None
        return row

    def mark_dispatched(self, row_id: int, note: str = "") -> None:
        self.dispatched_notes.append(note)

    def mark_retry_or_dead_letter(self, row_id: int, attempt: int, error: str) -> str:
        self.retry_calls.append((row_id, attempt, error))
        return "dead_letter" if attempt >= self.max_attempts else "queued"

    def _post(self, payload):  # type: ignore[override]
        if self._post_ok:
            return True, ""
        return False, "failed"


class SwarmPublishDispatcherTests(unittest.TestCase):
    def test_process_once_skips_send_false(self) -> None:
        dispatcher = _FakeDispatcher(
            PublishQueueRow(row_id=1, work_order_id="wo1", payload={"send": False}, attempt=1)
        )
        result = dispatcher.process_once()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "send_false")
        self.assertEqual(dispatcher.dispatched_notes, ["send_false"])

    def test_process_once_skips_when_auto_send_disabled(self) -> None:
        dispatcher = _FakeDispatcher(
            PublishQueueRow(row_id=2, work_order_id="wo2", payload={"send": True}, attempt=1),
            auto_send_enabled=False,
        )
        result = dispatcher.process_once()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "auto_send_disabled")
        self.assertEqual(dispatcher.dispatched_notes, ["auto_send_disabled"])

    def test_process_once_dispatches_when_post_succeeds(self) -> None:
        dispatcher = _FakeDispatcher(
            PublishQueueRow(row_id=3, work_order_id="wo3", payload={"send": True}, attempt=1)
        )
        result = dispatcher.process_once()
        self.assertEqual(result["status"], "dispatched")
        self.assertEqual(dispatcher.dispatched_notes, [""])

    def test_process_once_retries_or_dead_letters_on_failure(self) -> None:
        retry_dispatcher = _FakeDispatcher(
            PublishQueueRow(row_id=4, work_order_id="wo4", payload={"send": True}, attempt=1),
            post_ok=False,
            max_attempts=3,
        )
        retry_result = retry_dispatcher.process_once()
        self.assertEqual(retry_result["status"], "queued")

        dead_dispatcher = _FakeDispatcher(
            PublishQueueRow(row_id=5, work_order_id="wo5", payload={"send": True}, attempt=3),
            post_ok=False,
            max_attempts=3,
        )
        dead_result = dead_dispatcher.process_once()
        self.assertEqual(dead_result["status"], "dead_letter")


if __name__ == "__main__":
    unittest.main()
