#!/usr/bin/env python3

import os
import unittest
from unittest.mock import patch

from swarm_langgraph import graph_agents as ga


class SwarmGraphAgentsTests(unittest.TestCase):
    def test_graph_coordinator_handles_missing_config(self) -> None:
        with patch.dict(
            os.environ,
            {"GRAPH_TENANT_ID": "", "GRAPH_CLIENT_ID": "", "GRAPH_CLIENT_SECRET": ""},
            clear=False,
        ):
            result = ga.graph_coordinator_agent({"id": "wo1", "sender": "x@example.com"})
        self.assertFalse(result["enabled"])
        self.assertIn("graph_not_configured", result["errors"])

    def test_graph_coordinator_requires_thread_identifiers(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GRAPH_TENANT_ID": "tenant",
                "GRAPH_CLIENT_ID": "client",
                "GRAPH_CLIENT_SECRET": "secret",
            },
            clear=False,
        ):
            result = ga.graph_coordinator_agent({"id": "wo1"})
        self.assertTrue(result["enabled"])
        self.assertIn("graph_missing_message_or_conversation_id", result["errors"])

    def test_graph_coordinator_returns_thread_context(self) -> None:
        messages = [
            {
                "id": "m1",
                "conversationId": "c1",
                "subject": "Re: Deal",
                "receivedDateTime": "2026-02-17T12:00:00Z",
                "from": "alice@example.com",
                "to": ["yaakov@tapdash.co"],
                "bodyPreview": "Following up",
                "webLink": "https://graph.microsoft.com/messages/m1",
            }
        ]
        with patch.dict(
            os.environ,
            {
                "GRAPH_TENANT_ID": "tenant",
                "GRAPH_CLIENT_ID": "client",
                "GRAPH_CLIENT_SECRET": "secret",
            },
            clear=False,
        ):
            with patch("swarm_langgraph.graph_agents._fetch_access_token", return_value="token"):
                with patch("swarm_langgraph.graph_agents._fetch_thread_messages", return_value=messages):
                    result = ga.graph_coordinator_agent({"id": "wo2", "conversation_id": "c1"})

        self.assertTrue(result["enabled"])
        self.assertEqual(result["match_confidence"], "high")
        self.assertEqual(result["thread_context"]["message_count"], 1)
        self.assertIn("alice@example.com", result["thread_context"]["participants"])


if __name__ == "__main__":
    unittest.main()
