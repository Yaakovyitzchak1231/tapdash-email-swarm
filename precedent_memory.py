#!/usr/bin/env python3
"""Simple precedent memory for approval decisions."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_PRECEDENT_PATH = Path("/home/jacob/memory/precedents.jsonl")


@dataclass
class PrecedentMatch:
    found: bool
    decision: str
    confidence: float
    key: str
    sample_size: int


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _make_key(sender: str, labels: list[str], tier: str) -> str:
    domain = sender.split("@")[-1].lower() if "@" in sender else sender.lower()
    label_key = ",".join(sorted(labels))
    return f"{domain}|{label_key}|{tier}"


def append_precedent(
    sender: str,
    labels: list[str],
    tier: str,
    decision: str,
    path: Path = DEFAULT_PRECEDENT_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": _now(),
        "key": _make_key(sender=sender, labels=labels, tier=tier),
        "sender": sender,
        "labels": labels,
        "tier": tier,
        "decision": decision,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def lookup_precedent(
    sender: str,
    labels: list[str],
    tier: str,
    path: Path = DEFAULT_PRECEDENT_PATH,
    min_confidence: float = 0.7,
    min_samples: int = 2,
) -> PrecedentMatch:
    key = _make_key(sender=sender, labels=labels, tier=tier)
    rows = [row for row in _read_jsonl(path) if row.get("key") == key]
    if not rows:
        return PrecedentMatch(False, "unknown", 0.0, key, 0)

    counts = Counter(str(row.get("decision", "unknown")) for row in rows)
    decision, count = counts.most_common(1)[0]
    confidence = count / len(rows)
    enough_samples = len(rows) >= min_samples
    high_confidence = confidence >= min_confidence

    if enough_samples and high_confidence:
        return PrecedentMatch(True, decision, confidence, key, len(rows))
    return PrecedentMatch(False, decision, confidence, key, len(rows))
