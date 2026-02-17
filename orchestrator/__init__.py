"""Durable orchestration scaffold for the TapDash email swarm."""

from .config import OrchestratorConfig
from .runtime import DurableOrchestrator
from .stages import StageContext, StageResult, default_legacy_stages
from .store import InMemoryRunStore, PostgresRunStore

__all__ = [
    "DurableOrchestrator",
    "InMemoryRunStore",
    "OrchestratorConfig",
    "PostgresRunStore",
    "StageContext",
    "StageResult",
    "default_legacy_stages",
]
