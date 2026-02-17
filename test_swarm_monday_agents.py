#!/usr/bin/env python3

import unittest
from unittest.mock import patch

from swarm_langgraph import monday_agents as ma
from swarm_langgraph.nodes import SwarmNodes
from swarm_langgraph.state import SwarmState
from orchestrator.stages import StageContext


class SwarmMondayAgentsTests(unittest.TestCase):
    def test_monday_coordinator_extracts_deal_and_updates(self) -> None:
        fake_boards = [
            {
                "id": "b1",
                "name": "Deals",
                "items_page": {
                    "items": [
                        {
                            "id": "i1",
                            "name": "Acme Renewal",
                            "updated_at": "2026-02-17T00:00:00Z",
                            "column_values": [
                                {"id": "email", "text": "mario@acme.com"},
                                {"id": "status", "text": "Proposal Sent"},
                            ],
                            "updates": [
                                {
                                    "id": "u1",
                                    "body": "Client asked for final legal redlines.",
                                    "created_at": "2026-02-16T12:00:00Z",
                                }
                            ],
                        }
                    ]
                },
            }
        ]
        with patch.object(ma, "MONDAY_API_TOKEN", "token"):
            with patch.object(ma, "MONDAY_BOARD_IDS", "18397429943"):
                with patch.object(ma, "_boards_with_items_and_updates", return_value=fake_boards):
                    result = ma.monday_coordinator_agent({"sender": "mario@acme.com"})

        self.assertTrue(result["enabled"])
        self.assertEqual(result["match_confidence"], "high")
        self.assertEqual(result["crm_context"]["deal_status"], "Proposal Sent")
        self.assertEqual(result["crm_context"]["latest_update"]["id"], "u1")

    def test_monday_coordinator_handles_missing_config(self) -> None:
        with patch.object(ma, "MONDAY_API_TOKEN", ""):
            result = ma.monday_coordinator_agent({"sender": "x@example.com"})
        self.assertFalse(result["enabled"])
        self.assertIn("monday_not_configured", result["errors"])

    def test_swarm_node_merges_monday_context_into_base_context(self) -> None:
        nodes = SwarmNodes()
        ctx = StageContext(
            work_order={"id": "wo1", "sender": "mario@acme.com"},
            state={
                "context": {
                    "context": {"crm_enriched_fields": {}},
                }
            },
        )
        state: SwarmState = {
            "ctx": ctx,
            "last_result": None,
            "halt": False,
            "run_status": "running",
            "error": None,
            "output": {},
        }
        monday_payload = {
            "enabled": True,
            "crm_context": {"deal_status": "Qualified", "matched_item_id": "i1"},
        }
        with patch("swarm_langgraph.nodes.monday_coordinator_agent", return_value=monday_payload):
            nodes.monday_coordinator_agent(state)

        self.assertEqual(ctx.state["monday_context"]["crm_context"]["deal_status"], "Qualified")
        merged = ctx.state["context"]["context"]["crm_enriched_fields"]
        self.assertEqual(merged["deal_status"], "Qualified")
        self.assertEqual(
            ctx.state["context"]["context"]["external_context"]["monday"]["crm_context"]["deal_status"],
            "Qualified",
        )

    def test_swarm_node_merges_graph_context_into_base_context(self) -> None:
        nodes = SwarmNodes()
        ctx = StageContext(
            work_order={"id": "wo1", "sender": "mario@acme.com", "conversation_id": "conv_1"},
            state={"context": {"context": {"crm_enriched_fields": {}}}},
        )
        state: SwarmState = {
            "ctx": ctx,
            "last_result": None,
            "halt": False,
            "run_status": "running",
            "error": None,
            "output": {},
        }
        graph_payload = {
            "enabled": True,
            "thread_context": {"message_count": 2, "participants": ["mario@acme.com"]},
        }
        with patch("swarm_langgraph.nodes.graph_coordinator_agent", return_value=graph_payload):
            nodes.graph_coordinator_agent(state)

        self.assertEqual(ctx.state["graph_context"]["thread_context"]["message_count"], 2)
        self.assertEqual(ctx.state["context"]["context"]["graph_thread"]["thread_context"]["message_count"], 2)


if __name__ == "__main__":
    unittest.main()
