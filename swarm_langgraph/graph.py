from __future__ import annotations

from typing import Any, Callable

from .nodes import SwarmNodes
from .state import SwarmState

NodeFn = Callable[[SwarmState], dict[str, Any]]


class FallbackSwarmGraph:
    """Sequential fallback used when LangGraph dependency is unavailable."""

    def __init__(self, nodes: SwarmNodes) -> None:
        self.nodes = nodes
        self._order: list[NodeFn] = [
            nodes.tier_agent,
            nodes.context_agent,
            nodes.draft_agent,
            nodes.tone_agent,
            nodes.fact_agent,
            nodes.qa_agent,
            nodes.policy_agent,
            nodes.publish_agent,
        ]

    def invoke(self, state: SwarmState) -> SwarmState:
        current = dict(state)
        for fn in self._order:
            update = fn(current)  # type: ignore[arg-type]
            current.update(update)
            if current.get("halt"):
                break
        return current  # type: ignore[return-value]


def build_swarm_graph(nodes: SwarmNodes | None = None) -> Any:
    nodes = nodes or SwarmNodes()
    try:
        from langgraph.graph import END, START, StateGraph
    except Exception:
        return FallbackSwarmGraph(nodes)

    graph = StateGraph(SwarmState)
    graph.add_node("tier_agent", nodes.tier_agent)
    graph.add_node("context_agent", nodes.context_agent)
    graph.add_node("draft_agent", nodes.draft_agent)
    graph.add_node("tone_agent", nodes.tone_agent)
    graph.add_node("fact_agent", nodes.fact_agent)
    graph.add_node("qa_agent", nodes.qa_agent)
    graph.add_node("policy_agent", nodes.policy_agent)
    graph.add_node("publish_agent", nodes.publish_agent)

    graph.add_edge(START, "tier_agent")
    graph.add_edge("tier_agent", "context_agent")
    graph.add_edge("context_agent", "draft_agent")
    graph.add_edge("draft_agent", "tone_agent")
    graph.add_edge("tone_agent", "fact_agent")
    graph.add_edge("fact_agent", "qa_agent")
    graph.add_edge("qa_agent", "policy_agent")

    def route_after_policy(state: SwarmState) -> str:
        if state.get("halt"):
            return END
        return "publish_agent"

    graph.add_conditional_edges("policy_agent", route_after_policy)
    graph.add_edge("publish_agent", END)
    return graph.compile()
