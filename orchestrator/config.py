from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class OrchestratorConfig:
    database_url: str
    auto_send_enabled: bool
    min_confidence: float

    @classmethod
    def from_env(cls) -> "OrchestratorConfig":
        database_url = os.environ.get("DATABASE_URL", "").strip()
        auto_send_enabled = os.environ.get("AUTO_SEND_ENABLED", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        min_confidence = float(os.environ.get("DRAFT_MIN_CONFIDENCE", "0.65"))
        return cls(
            database_url=database_url,
            auto_send_enabled=auto_send_enabled,
            min_confidence=min_confidence,
        )
