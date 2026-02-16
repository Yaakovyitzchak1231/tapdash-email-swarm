#!/usr/bin/env python3
"""Tiered escalation policy for email drafting."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_POLICY_PATH = Path("/home/jacob/config/escalation_policy.json")


DEFAULT_POLICY: dict[str, Any] = {
    "tiers": {
        "A": {
            "name": "ack_or_scheduling",
            "description": "Acknowledgment and scheduling language only.",
            "auto_publish_allowed": True,
        },
        "B": {
            "name": "safe_operational",
            "description": "Operational phrasing without hard claims.",
            "auto_publish_allowed": True,
        },
        "C": {
            "name": "high_risk_claims",
            "description": "Pricing/legal/security/compliance/guarantees.",
            "auto_publish_allowed": False,
        },
    },
    "triggers": {
        "tier_c_keywords": [
            "price",
            "pricing",
            "quote",
            "discount",
            "contract",
            "msa",
            "dpa",
            "legal",
            "liability",
            "security",
            "soc 2",
            "hipaa",
            "gdpr",
            "guarantee",
            "guaranteed",
            "warranty",
        ],
        "tier_c_patterns": [
            r"\$\\s*\\d+",
            r"\\b\\d+%\\b",
        ],
        "tier_a_keywords": [
            "thank",
            "received",
            "share times",
            "time window",
            "schedule",
            "next step",
        ],
    },
}


@dataclass
class PolicyDecision:
    tier: str
    auto_publish_allowed: bool
    reason: str


def ensure_default_policy(path: Path = DEFAULT_POLICY_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_POLICY, indent=2), encoding="utf-8")
    return path


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    ensure_default_policy(path)
    return json.loads(path.read_text(encoding="utf-8"))


def classify_text(text: str, policy: dict[str, Any]) -> PolicyDecision:
    lowered = text.lower()
    triggers = policy.get("triggers", {})
    tier_c_keywords = [k.lower() for k in triggers.get("tier_c_keywords", [])]
    tier_c_patterns = triggers.get("tier_c_patterns", [])
    tier_a_keywords = [k.lower() for k in triggers.get("tier_a_keywords", [])]

    for keyword in tier_c_keywords:
        if keyword and keyword in lowered:
            return PolicyDecision("C", False, f"tier_c_keyword:{keyword}")

    for pattern in tier_c_patterns:
        if re.search(pattern, text):
            return PolicyDecision("C", False, f"tier_c_pattern:{pattern}")

    if any(keyword in lowered for keyword in tier_a_keywords):
        return PolicyDecision("A", True, "tier_a_ack_scheduling")

    return PolicyDecision("B", True, "tier_b_safe_operational_default")
